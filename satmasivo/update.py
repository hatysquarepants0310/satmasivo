"""Revisa releases de GitHub. Linux: apt del .deb. Windows: instala en el usuario y reemplaza ese .exe."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from satmasivo import __version__
from satmasivo.config import load_config, save_config

REPO = "hatysquarepants0310/satmasivo"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
WIN_APP_NAME = "SAT Masivo"
WIN_EXE_NAME = "satmasivo.exe"


def _cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "satmasivo" / "updates"
    return Path.home() / ".cache" / "satmasivo" / "updates"


CACHE = _cache_dir()


def _is_windows() -> bool:
    return os.name == "nt"


@dataclass
class Release:
    tag: str
    version: str
    notes: str
    asset_url: str
    asset_name: str
    kind: str  # deb | exe


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text.split("-", 1)[0])
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums)


def is_newer(remote: str, current: str) -> bool:
    a, b = parse_version(remote), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def wanted_kind() -> str:
    return "exe" if _is_windows() else "deb"


def is_packaged() -> bool:
    """True en el .deb instalado o en el .exe frozen. El checkout de git no auto-actualiza."""
    if _is_windows():
        return bool(getattr(sys, "frozen", False))
    here = Path(__file__).resolve()
    if "/usr/lib/satmasivo" in str(here):
        return True
    try:
        argv0 = Path(sys.argv[0]).resolve()
    except (OSError, RuntimeError):
        return False
    return argv0 == Path("/usr/bin/satmasivo")


def pick_asset(data: dict, kind: str) -> tuple[str, str]:
    suffix = ".exe" if kind == "exe" else ".deb"
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.lower().endswith(suffix):
            url = str(asset.get("url") or "")
            if url:
                return name, url
    return "", ""


def win_install_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "Programs" / "SATMasivo"


def win_installed_exe() -> Path:
    return win_install_dir() / WIN_EXE_NAME


def win_start_menu_lnk() -> Path:
    roaming = Path(os.environ.get("APPDATA") or Path.home())
    return roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{WIN_APP_NAME}.lnk"


def win_desktop_dir() -> Path:
    for key in ("USERPROFILE", "HOME"):
        base = os.environ.get(key)
        if not base:
            continue
        for name in ("Desktop", "Escritorio"):
            p = Path(base) / name
            if p.is_dir():
                return p
    return Path.home() / "Desktop"


def win_desktop_lnk() -> Path:
    return win_desktop_dir() / f"{WIN_APP_NAME}.lnk"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def shortcut_ps(lnk: Path, target: Path) -> str:
    return (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_ps_quote(str(lnk))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(target.parent))}; "
        f"$s.Description = {_ps_quote(WIN_APP_NAME)}; "
        "$s.Save()"
    )


def write_shortcut(lnk: Path, target: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            shortcut_ps(lnk, target),
        ],
        check=True,
        timeout=30,
        capture_output=True,
        text=True,
    )


def ensure_start_menu(target: Path) -> None:
    lnk = win_start_menu_lnk()
    if lnk.is_file():
        return
    try:
        write_shortcut(lnk, target)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


def _copy_into_install(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        return
    try:
        shutil.copy2(src, dest)
    except OSError:
        if not dest.is_file():
            raise


def ensure_windows_install() -> bool:
    """Copia el .exe a LocalAppData, deja acceso en Inicio y abre esa copia. True = salir."""
    if not _is_windows() or not getattr(sys, "frozen", False):
        return False
    here = Path(sys.executable).resolve()
    dest = win_installed_exe()
    if here == dest.resolve() and dest.is_file():
        ensure_start_menu(dest)
        return False
    _copy_into_install(here, dest)
    if not dest.is_file():
        raise RuntimeError("No se pudo instalar SAT Masivo")
    try:
        write_shortcut(win_start_menu_lnk(), dest)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    try:
        write_shortcut(win_desktop_lnk(), dest)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    subprocess.Popen([str(dest)], close_fds=True)
    return True


def _token() -> str:
    cfg = load_config()
    tok = str(cfg.get("github_token") or "").strip()
    if tok:
        return tok
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("SATMASIVO_GH_TOKEN")
    if env:
        return env.strip()
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.check_output(
                [gh, "auth", "token"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=8,
            )
            return out.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            pass
    return ""


def save_token(token: str) -> None:
    cfg = load_config()
    cfg["github_token"] = token.strip()
    save_config(cfg)


def check_latest(current: str | None = None, timeout: float = 8) -> Release | None:
    current = current or __version__
    headers = {"Accept": "application/vnd.github+json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(API, headers=headers, timeout=timeout)
    if r.status_code in {401, 403, 404}:
        raise PermissionError(
            "Repo privado: pega un token de GitHub (contents:read) "
            "en Actualizar, o inicia sesión con `gh auth login`."
        )
    r.raise_for_status()
    data = r.json()
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("v")
    if not is_newer(version, current):
        return None
    kind = wanted_kind()
    asset_name, asset_url = pick_asset(data, kind)
    suffix = ".exe" if kind == "exe" else ".deb"
    if not asset_url:
        raise RuntimeError(f"El release {tag} no trae {suffix}")
    return Release(
        tag=tag,
        version=version,
        notes=str(data.get("body") or ""),
        asset_url=asset_url,
        asset_name=asset_name,
        kind=kind,
    )


def download_asset(rel: Release) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / rel.asset_name
    headers = {
        "Accept": "application/octet-stream",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(rel.asset_url, headers=headers, timeout=180, stream=True) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(1024 * 64):
                if chunk:
                    fh.write(chunk)
        tmp.replace(dest)
    raw = dest.read_bytes()[:8]
    if rel.kind == "deb" and not raw.startswith(b"!<arch>"):
        dest.unlink(missing_ok=True)
        raise RuntimeError("El archivo bajado no es un .deb válido")
    if rel.kind == "exe" and not raw.startswith(b"MZ"):
        dest.unlink(missing_ok=True)
        raise RuntimeError("El archivo bajado no es un .exe válido")
    return dest


def download_deb(rel: Release) -> Path:
    return download_asset(rel)


def install_deb(path: Path) -> None:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    pkexec = shutil.which("pkexec") or "/usr/bin/pkexec"
    proc = subprocess.run(
        [pkexec, "/usr/bin/apt-get", "install", "-y", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"apt exit {proc.returncode}")


def write_replace_bat(src: Path, dst: Path) -> Path:
    """Espera a que suelte el .exe instalado y lo reemplaza. Relanza esa copia."""
    bat = src.with_suffix(".bat")
    src_s = str(src)
    dst_s = str(dst)
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                "set N=0",
                ":retry",
                "timeout /t 1 /nobreak >nul",
                f'move /y "{src_s}" "{dst_s}"',
                "if not errorlevel 1 goto ok",
                "set /a N+=1",
                "if %N% lss 30 goto retry",
                "exit /b 1",
                ":ok",
                f'start "" "{dst_s}"',
                'del "%~f0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return bat


def install_exe(path: Path, target: Path | None = None) -> None:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    dest = (target or win_installed_exe()).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    bat = write_replace_bat(path, dest)
    subprocess.Popen(["cmd", "/c", str(bat)], close_fds=True)


def relaunch() -> None:
    exe = shutil.which("satmasivo") or "/usr/bin/satmasivo"
    os.execv(exe, [exe])


def apply_update(rel: Release) -> None:
    dest = download_asset(rel)
    if rel.kind == "exe":
        install_exe(dest)
    else:
        install_deb(dest)


def bootstrap_update() -> bool:
    """Al abrir: si hay release más nuevo, lo instala. True = este proceso debe salir."""
    if not is_packaged():
        return False
    try:
        rel = check_latest()
    except Exception:
        return False
    if rel is None:
        return False
    try:
        apply_update(rel)
    except Exception:
        return False
    if not _is_windows():
        try:
            relaunch()
        except Exception:
            return False
    return True


def bootstrap() -> bool:
    """Instala en Windows si hace falta, luego actualiza. True = este proceso debe salir."""
    try:
        if ensure_windows_install():
            return True
    except Exception:
        pass
    return bootstrap_update()
