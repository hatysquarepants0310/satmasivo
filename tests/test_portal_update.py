from satmasivo.ciec_login import CiecClient, extract_captcha, looks_like_login, parse_auto_form, parse_login_form
from satmasivo.portal import date_filters, descargar_con_sesion, extract_accion_urls, extract_download_targets, extract_folio_map, extract_result_pages, extract_table_rows, html_from_delta, looks_like_xml, logged_in, parse_sat_delta, plan_xml_jobs, query_filters
from satmasivo.tlsenv import OPENSSL_CIPHERS, apply, is_sat_host
from satmasivo.update import is_newer, parse_version


def test_extract_uuids_and_recupera():
    html = """
    <html><body>
    <a href="RecuperaCfdi.aspx?folioFiscal=11111111-2222-3333-4444-555555555555">xml</a>
    <span onclick="return AccionCfdi('RecuperaCfdi.aspx?Datos=abc','Recuperacion');">dl</span>
    <span>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</span>
    <a href="javascript:void(0)">x</a>
    </body></html>
    """
    uuids, hrefs = extract_download_targets(html)
    assert "11111111-2222-3333-4444-555555555555" in uuids
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" not in uuids
    assert any("RecuperaCfdi" in h for h in hrefs)
    assert any("Datos=abc" in h for h in hrefs)


def test_parse_sat_delta_and_dates():
    raw = "|3|hiddenField|__FOO|foo|88|hiddenField|__VIEWSTATE|VIEWSTATEOK|"
    assert parse_sat_delta(raw)["__VIEWSTATE"] == "VIEWSTATEOK"
    rec = date_filters("recibidas", __import__("datetime").date(2026, 3, 20))
    assert rec["ctl00$MainContent$CldFecha$DdlAnio"] == "2026"
    assert rec["ctl00$MainContent$CldFecha$DdlMes"] == "3"
    assert rec["ctl00$MainContent$CldFecha$DdlDia"] == "20"
    emi = date_filters("emitidas", __import__("datetime").date(2026, 3, 1), __import__("datetime").date(2026, 3, 31))
    assert emi["ctl00$MainContent$CldFechaInicial2$Calendario_text"] == "01/03/2026"
    assert emi["ctl00$MainContent$CldFechaFinal2$Calendario_text"] == "31/03/2026"
    assert extract_accion_urls("return AccionCfdi('foo.aspx?x=1','Recuperacion');")[0].endswith("foo.aspx?x=1")
    qf = query_filters()
    assert qf["ctl00$MainContent$BtnBusqueda"] == "Buscar CFDI"
    assert qf["ctl00$MainContent$ddlComplementos"] == "-1"


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


def test_parse_wsfed_form():
    html = """
    <html><body>
    <form action="https://portalcfdi.facturaelectronica.sat.gob.mx/" method="POST">
    <input type="hidden" name="wa" value="wsignin1.0">
    <input type="hidden" name="wresult" value="<t:RequestSecurityTokenResponse/>">
    <input type="submit" value="Continue">
    </form></body></html>
    """
    parsed = parse_auto_form(html)
    assert parsed is not None
    action, method, fields = parsed
    assert "portalcfdi" in action
    assert method == "post"
    assert fields["wa"] == "wsignin1.0"
    assert "wresult" in fields
    assert parse_auto_form("<html><form><input name=x></form></html>") is None
    two = """
    <form action="/x"><input name="q" value="1"></form>
    <form action="https://portalcfdi.facturaelectronica.sat.gob.mx/" method="POST">
    <input type="hidden" name="wresult" value="tok">
    </form>
    """
    parsed2 = parse_auto_form(two)
    assert parsed2 is not None
    assert parsed2[2]["wresult"] == "tok"
    assert parse_auto_form('<form><input name="wa" value="wsignin1.0"></form>') is None
    login_html = """
    <form action="/nidp/app/login?id=SATUPCFDiCon" method="post">
    <input name="Ecom_User_ID"><input name="Ecom_Password"><input name="userCaptcha">
    </form>
    """
    la = parse_login_form(login_html)
    assert la is not None
    assert "SATUPCFDiCon" in la[0]


def test_html_from_delta():
    raw = "|1|#||4|80|updatePanel|ctl00_Upnl|<table id='ctl00_MainContent_tblResult'><span onclick=\"return AccionCfdi('Recupera.aspx?Datos=z','Recuperacion');\"></span></table>|"
    html = html_from_delta(raw)
    assert "tblResult" in html
    assert extract_accion_urls(html)


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


def test_descarga_acepta_progress():
    import inspect

    assert "progress" in inspect.signature(descargar_con_sesion).parameters


def test_plan_xml_jobs_skips_uuid_already_in_href():
    href = "https://portalcfdi.facturaelectronica.sat.gob.mx/RecuperaCfdi.aspx?folioFiscal=11111111-2222-3333-4444-555555555555"
    jobs = plan_xml_jobs([href], ["11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"])
    kinds = [k for k, _ in jobs]
    assert kinds.count("href") == 1
    assert ("uuid", "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE") in jobs
    assert not any(p.endswith("555555555555") and k == "uuid" for k, p in jobs)


def test_extract_result_pages():
    html = "javascript:__doPostBack('ctl00$MainContent$gvCfdi','Page$2'); __doPostBack('ctl00$MainContent$gvCfdi','Page$3')"
    pages = extract_result_pages(html)
    assert ("ctl00$MainContent$gvCfdi", "2") in pages
    assert ("ctl00$MainContent$gvCfdi", "3") in pages


def test_extract_folio_map_one_per_row():
    html = """
    <table>
    <tr><td>11111111-2222-3333-4444-555555555555</td>
        <td><span onclick="return AccionCfdi('RecuperaCfdi.aspx?Datos=aaa','Recuperacion');"></span></td></tr>
    <tr><td>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</td><td>sin boton</td></tr>
    </table>
    """
    fmap = extract_folio_map(html)
    assert fmap["11111111-2222-3333-4444-555555555555"].endswith("Datos=aaa")
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" not in fmap
    rows = extract_table_rows(html)
    folios = [u for u, _ in rows]
    assert "11111111-2222-3333-4444-555555555555" in folios
    assert "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE" in folios
    uuids, hrefs = extract_download_targets(html)
    assert len(uuids) == 2
    assert len(hrefs) == 1




