from pathlib import Path

from satmasivo.update import (
    Release,
    bootstrap,
    bootstrap_update,
    ensure_windows_install,
    is_newer,
    is_packaged,
    parse_version,
    pick_asset,
    shortcut_ps,
    win_install_dir,
    win_installed_exe,
    write_replace_bat,
)


def test_version_newer():
    assert parse_version("v1.1.0") == (1, 1, 0)
    assert is_newer("1.5.21", "1.5.20")
    assert not is_newer("1.5.20", "1.5.21")
    assert not is_newer("1.5.21", "1.5.21")


def test_pick_asset_exe_and_deb():
    data = {
        "assets": [
            {"name": "satmasivo_1.5.21_all.deb", "url": "https://api.example/deb"},
            {"name": "satmasivo.exe", "url": "https://api.example/exe"},
        ]
    }
    name, url = pick_asset(data, "exe")
    assert name == "satmasivo.exe"
    assert url.endswith("/exe")
    name, url = pick_asset(data, "deb")
    assert name.endswith(".deb")
    assert url.endswith("/deb")
    assert pick_asset({"assets": []}, "exe") == ("", "")


def test_is_packaged_source_tree():
    assert is_packaged() is False


def test_bootstrap_skips_source_tree(monkeypatch):
    monkeypatch.setattr("satmasivo.update.is_packaged", lambda: False)
    monkeypatch.setattr("satmasivo.update.ensure_windows_install", lambda: False)

    def boom():
        raise AssertionError("no debe consultar release desde el checkout")

    monkeypatch.setattr("satmasivo.update.check_latest", boom)
    assert bootstrap() is False


def test_bootstrap_skips_when_current(monkeypatch):
    monkeypatch.setattr("satmasivo.update.is_packaged", lambda: True)
    monkeypatch.setattr("satmasivo.update.check_latest", lambda: None)
    assert bootstrap_update() is False


def test_bootstrap_applies_and_relaunches_linux(monkeypatch):
    called = {}
    rel = Release(
        tag="v1.5.21",
        version="1.5.21",
        notes="",
        asset_url="https://api.example/deb",
        asset_name="satmasivo_1.5.21_all.deb",
        kind="deb",
    )
    monkeypatch.setattr("satmasivo.update.is_packaged", lambda: True)
    monkeypatch.setattr("satmasivo.update.check_latest", lambda: rel)
    monkeypatch.setattr("satmasivo.update.apply_update", lambda r: called.setdefault("tag", r.tag))
    monkeypatch.setattr("satmasivo.update._is_windows", lambda: False)
    monkeypatch.setattr("satmasivo.update.relaunch", lambda: called.setdefault("re", True))
    assert bootstrap_update() is True
    assert called["tag"] == "v1.5.21"
    assert called["re"] is True


def test_bootstrap_windows_does_not_relaunch_here(monkeypatch):
    called = {}
    rel = Release(
        tag="v1.5.21",
        version="1.5.21",
        notes="",
        asset_url="https://api.example/exe",
        asset_name="satmasivo.exe",
        kind="exe",
    )
    monkeypatch.setattr("satmasivo.update.is_packaged", lambda: True)
    monkeypatch.setattr("satmasivo.update.check_latest", lambda: rel)
    monkeypatch.setattr("satmasivo.update.apply_update", lambda r: called.setdefault("ok", True))
    monkeypatch.setattr("satmasivo.update._is_windows", lambda: True)

    def boom():
        raise AssertionError("en Windows relanza el .bat, no execv")

    monkeypatch.setattr("satmasivo.update.relaunch", boom)
    assert bootstrap_update() is True
    assert called["ok"] is True


def test_bootstrap_network_fail_abre_igual(monkeypatch):
    monkeypatch.setattr("satmasivo.update.is_packaged", lambda: True)

    def boom():
        raise RuntimeError("timeout")

    monkeypatch.setattr("satmasivo.update.check_latest", boom)
    assert bootstrap_update() is False


def test_win_install_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert win_install_dir() == tmp_path / "Programs" / "SATMasivo"
    assert win_installed_exe() == tmp_path / "Programs" / "SATMasivo" / "satmasivo.exe"


def test_ensure_windows_install_noop_fuera_de_windows(monkeypatch):
    monkeypatch.setattr("satmasivo.update._is_windows", lambda: False)
    assert ensure_windows_install() is False


def test_ensure_windows_install_copia_y_abre_instalado(monkeypatch, tmp_path):
    downloaded = tmp_path / "Downloads" / "satmasivo.exe"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"MZ-download")
    dest_dir = tmp_path / "Programs" / "SATMasivo"
    called = {}

    monkeypatch.setattr("satmasivo.update._is_windows", lambda: True)
    monkeypatch.setattr("satmasivo.update.sys.frozen", True, raising=False)
    monkeypatch.setattr("satmasivo.update.sys.executable", str(downloaded))
    monkeypatch.setattr("satmasivo.update.win_installed_exe", lambda: dest_dir / "satmasivo.exe")
    monkeypatch.setattr("satmasivo.update.win_start_menu_lnk", lambda: tmp_path / "Start" / "SAT Masivo.lnk")
    monkeypatch.setattr("satmasivo.update.win_desktop_lnk", lambda: tmp_path / "Desktop" / "SAT Masivo.lnk")

    def fake_shortcut(lnk, target):
        called.setdefault("lnks", []).append((Path(lnk).name, Path(target)))
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        Path(lnk).write_text("lnk", encoding="utf-8")

    monkeypatch.setattr("satmasivo.update.write_shortcut", fake_shortcut)
    monkeypatch.setattr(
        "satmasivo.update.subprocess.Popen",
        lambda args, **kw: called.setdefault("popen", args),
    )
    assert ensure_windows_install() is True
    installed = dest_dir / "satmasivo.exe"
    assert installed.read_bytes() == b"MZ-download"
    assert called["popen"][0] == str(installed)
    names = [n for n, _ in called["lnks"]]
    assert "SAT Masivo.lnk" in names
    assert len(called["lnks"]) == 2


def test_ensure_windows_install_ya_instalado_no_relanza(monkeypatch, tmp_path):
    dest = tmp_path / "Programs" / "SATMasivo" / "satmasivo.exe"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"MZ")
    start = tmp_path / "SAT Masivo.lnk"
    start.write_text("lnk", encoding="utf-8")
    monkeypatch.setattr("satmasivo.update._is_windows", lambda: True)
    monkeypatch.setattr("satmasivo.update.sys.frozen", True, raising=False)
    monkeypatch.setattr("satmasivo.update.sys.executable", str(dest))
    monkeypatch.setattr("satmasivo.update.win_installed_exe", lambda: dest)
    monkeypatch.setattr("satmasivo.update.win_start_menu_lnk", lambda: start)
    monkeypatch.setattr(
        "satmasivo.update.subprocess.Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe relanzar")),
    )
    assert ensure_windows_install() is False


def test_shortcut_ps_apunta_al_instalado():
    lnk = Path("C:/Users/x/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/SAT Masivo.lnk")
    target = Path("C:/Users/x/AppData/Local/Programs/SATMasivo/satmasivo.exe")
    ps = shortcut_ps(lnk, target)
    assert "SAT Masivo.lnk" in ps
    assert "SATMasivo" in ps
    assert "satmasivo.exe" in ps
    assert "CreateShortcut" in ps


def test_replace_bat_pisa_el_instalado(tmp_path):
    src = tmp_path / "cache" / "satmasivo.exe"
    dst = tmp_path / "Programs" / "SATMasivo" / "satmasivo.exe"
    src.parent.mkdir()
    src.write_bytes(b"MZ")
    dst.parent.mkdir(parents=True)
    bat = write_replace_bat(src, dst)
    text = bat.read_text(encoding="utf-8")
    assert f'move /y "{src}" "{dst}"' in text
    assert f'start "" "{dst}"' in text
    assert "SATMasivo" in text
    assert "%N% lss 30" in text


def test_bootstrap_instala_windows_antes_de_update(monkeypatch):
    called = {}
    monkeypatch.setattr("satmasivo.update.ensure_windows_install", lambda: True)

    def boom():
        raise AssertionError("si se está instalando, no actualices en este proceso")

    monkeypatch.setattr("satmasivo.update.bootstrap_update", boom)
    assert bootstrap() is True
    called.clear()
