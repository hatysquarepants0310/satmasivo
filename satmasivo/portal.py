"""Sesión del portal SAT (CIEC). Usa cookies de la ventana; no pide ni guarda la contraseña."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

from satmasivo.sat_ws import SatError

PORTAL = "https://portalcfdi.facturaelectronica.sat.gob.mx/"
CONSULTA = {
    "recibidas": urljoin(PORTAL, "ConsultaReceptor.aspx"),
    "emitidas": urljoin(PORTAL, "ConsultaEmisor.aspx"),
}
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def session_from_cookies(cookies: list[tuple[str, str, str, str]]) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": PORTAL})
    for name, value, domain, path in cookies:
        s.cookies.set(name, value, domain=domain or ".sat.gob.mx", path=path or "/")
    return s


def logged_in(html: str, final_url: str) -> bool:
    url = final_url.lower()
    if "cfdiau.sat.gob.mx" in url or "/nidp/" in url:
        return False
    if "portalcfdi.facturaelectronica.sat.gob.mx" not in url:
        return False
    low = html.lower()
    if "rfc" in low and "contraseña" in low and "captcha" in low:
        return False
    return True


def extract_download_targets(html: str, base: str = PORTAL) -> tuple[list[str], list[str]]:
    uuids = list(dict.fromkeys(UUID_RE.findall(html)))
    parser = _LinkParser()
    parser.feed(html)
    hrefs: list[str] = []
    for raw in parser.hrefs:
        if not raw or raw.startswith("javascript:"):
            continue
        if re.search(r"Recupera|Descarga|xml|Cfdi|Comprobante", raw, re.I):
            hrefs.append(urljoin(base, raw))
    hrefs = list(dict.fromkeys(hrefs))
    return uuids, hrefs


def looks_like_xml(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<?xml") or b"<cfdi:comprobante" in head or b"<comprobante" in head


def download_url(sess: requests.Session, url: str, dest_dir: Path) -> Path | None:
    r = sess.get(url, timeout=60, allow_redirects=True)
    if r.status_code >= 400 or not r.content:
        return None
    if not looks_like_xml(r.content):
        return None
    name = None
    found = UUID_RE.search(r.content.decode("utf-8", errors="ignore"))
    if found:
        name = found.group(0).upper() + ".xml"
    if not name:
        name = Path(url.split("?")[0]).name
        if not name.lower().endswith(".xml"):
            name = f"cfdi-{len(list(dest_dir.glob('*.xml'))) + 1}.xml"
    path = dest_dir / name
    path.write_bytes(r.content)
    return path


def recover_by_uuid(sess: requests.Session, uuid: str, dest_dir: Path) -> Path | None:
    candidates = [
        urljoin(PORTAL, f"RecuperaCfdi.aspx?folioFiscal={uuid}"),
        urljoin(PORTAL, f"RecuperaCfdi.aspx?uuid={uuid}"),
        urljoin(PORTAL, f"RepresentacionImpresa.aspx?folioFiscal={uuid}"),
    ]
    for url in candidates:
        got = download_url(sess, url, dest_dir)
        if got:
            return got
    return None


def probe_session(sess: requests.Session, sentido: str) -> str:
    url = CONSULTA.get(sentido, CONSULTA["recibidas"])
    r = sess.get(url, timeout=40, allow_redirects=True)
    if not logged_in(r.text, r.url):
        raise SatError(
            "No hay sesión SAT. Entra con RFC + contraseña + captcha "
            "(o e.firma) en la ventana y vuelve a Descargar."
        )
    return r.text


def descargar_con_sesion(
    cookies: list[tuple[str, str, str, str]],
    *,
    sentido: str,
    dest: Path,
    extra_html: str = "",
    extra_hrefs: list[str] | None = None,
) -> list[Path]:
    if not cookies:
        raise SatError("La ventana no entregó cookies del SAT. Recarga e inicia sesión.")
    dest.mkdir(parents=True, exist_ok=True)
    sess = session_from_cookies(cookies)
    html = probe_session(sess, sentido)
    uuids, hrefs = extract_download_targets(html)
    if extra_html:
        u2, h2 = extract_download_targets(extra_html)
        uuids = list(dict.fromkeys(uuids + u2))
        hrefs = list(dict.fromkeys(hrefs + h2))
    if extra_hrefs:
        hrefs = list(dict.fromkeys(hrefs + extra_hrefs))

    written: list[Path] = []
    for href in hrefs:
        got = download_url(sess, href, dest)
        if got:
            written.append(got)
    have = {p.stem.upper() for p in written}
    for uuid in uuids:
        if uuid.upper() in have:
            continue
        got = recover_by_uuid(sess, uuid, dest)
        if got:
            written.append(got)
            have.add(uuid.upper())
    if not written:
        raise SatError(
            "Sesión SAT viva, pero el portal no soltó XML. "
            "En Recibidas/Emitidas pulsa Buscar en la página del SAT "
            "y vuelve a Descargar, o usa e.firma."
        )
    return written
