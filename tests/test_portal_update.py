from satmasivo.ciec_login import CiecClient, extract_captcha, looks_like_login
from satmasivo.portal import extract_download_targets, looks_like_xml, logged_in
from satmasivo.tlsenv import OPENSSL_CIPHERS, apply, is_sat_host
from satmasivo.update import is_newer, parse_version


def test_extract_uuids_and_recupera():
    html = """
    <html><body>
    <a href="RecuperaCfdi.aspx?folioFiscal=11111111-2222-3333-4444-555555555555">xml</a>
    <span>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</span>
    <a href="javascript:void(0)">x</a>
    </body></html>
    """
    uuids, hrefs = extract_download_targets(html)
    assert "11111111-2222-3333-4444-555555555555" in uuids
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in uuids
    assert any("RecuperaCfdi" in h for h in hrefs)


def test_logged_in_detects_login_page():
    assert not logged_in("RFC contraseña captcha", "https://cfdiau.sat.gob.mx/nidp/app")
    assert logged_in("<html>consulta</html>", "https://portalcfdi.facturaelectronica.sat.gob.mx/ConsultaReceptor.aspx")


def test_looks_like_xml():
    assert looks_like_xml(b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="x"/>')
    assert not looks_like_xml(b"<html>no</html>")


def test_version_newer():
    assert parse_version("v1.1.0") == (1, 1, 0)
    assert is_newer("1.1.0", "1.0.0")
    assert is_newer("1.1.1", "1.1.0")
    assert not is_newer("1.0.0", "1.1.0")
    assert not is_newer("1.0.0", "1.0.0")


def test_tls_apply_sets_gnutls(monkeypatch):
    monkeypatch.delenv("G_TLS_GNUTLS_PRIORITY", raising=False)
    apply()
    assert "PROFILE_VERY_WEAK" in __import__("os").environ["G_TLS_GNUTLS_PRIORITY"]
    assert "-DHE-RSA" not in __import__("os").environ["G_TLS_GNUTLS_PRIORITY"]
    assert "SECLEVEL=1" in OPENSSL_CIPHERS
    assert is_sat_host("cfdiau.sat.gob.mx")
    assert is_sat_host("portalcfdi.facturaelectronica.sat.gob.mx")
    assert not is_sat_host("evil.example")


def test_sat_login_tls():
    from satmasivo.http import sat_session

    r = sat_session(insecure=True).get(
        "https://cfdiau.sat.gob.mx/nidp/wsfed/ep?id=SATUPCFDiCon&sid=0&option=credential&sid=0",
        timeout=25,
        allow_redirects=True,
    )
    assert r.status_code == 200


def test_extract_captcha_and_live_start():
    html = (
        '<img src="data:image/png;base64,aGVsbG8=">'
        '<input name="Ecom_User_ID"><input name="userCaptcha">'
    )
    assert looks_like_login(html)
    assert extract_captcha(html) == b"hello"
    img = CiecClient().start()
    assert len(img) > 80
    from satmasivo.app import _png_bytes

    png = _png_bytes(img)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"



