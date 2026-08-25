"""Revisa releases de GitHub e instala el .deb nuevo."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

from satmasivo import __version__
from satmasivo.config import load_config, save_config

REPO = "hatysquarepants0310/satmasivo"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE = Path.home() / ".cache" / "satmasivo" / "updates"


@dataclass
class Release:
    tag: str
    version: str
    notes: str
    deb_url: str
    deb_name: str


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


def check_latest(current: str | None = None) -> Release | None:
    current = current or __version__
    headers = {"Accept": "application/vnd.github+json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(API, headers=headers, timeout=20)
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
    deb_url = deb_name = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.endswith(".deb"):
            deb_url = str(asset.get("url") or "")
            deb_name = name
            break
    if not deb_url:
        raise RuntimeError(f"El release {tag} no trae .deb")
    return Release(
        tag=tag,
        version=version,
        notes=str(data.get("body") or ""),
        deb_url=deb_url,
        deb_name=deb_name,
    )


def download_deb(rel: Release) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / rel.deb_name
    headers = {
        "Accept": "application/octet-stream",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(rel.deb_url, headers=headers, timeout=120, stream=True) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(1024 * 64):
                if chunk:
                    fh.write(chunk)
        tmp.replace(dest)
    if not dest.read_bytes()[:7] == b"!<arch>":
        dest.unlink(missing_ok=True)
        raise RuntimeError("El archivo bajado no es un .deb válido")
    return dest


def install_deb(path: Path) -> None:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    pkexec = shutil.which("pkexec") or "/usr/bin/pkexec"
    cmd = [
        pkexec,
        "/usr/bin/apt-get",
        "install",
        "-y",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"apt exit {proc.returncode}")
