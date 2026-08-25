"""Sesión del portal SAT (CIEC): AJAX ConsultaReceptor/Emisor + RecuperaCfdi."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

from satmasivo.http import sat_session
from satmasivo.sat_ws import SatError

PORTAL = "https://portalcfdi.facturaelectronica.sat.gob.mx/"
CONSULTA = {
    "recibidas": urljoin(PORTAL, "ConsultaReceptor.aspx"),
    "emitidas": urljoin(PORTAL, "ConsultaEmisor.aspx"),
}
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
ACCION_RE = re.compile(r"AccionCfdi\(['\"]([^'\"]+)['\"]", re.I)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0"
)
AJAX_HEADERS = {
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action = ""
        self.fields: dict[str, str] = {}
        self._select: str | None = None
        self._option_value = ""
        self._option_selected = False
        self._option_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "form" and not self.action:
            self.action = ad.get("action", "")
        if tag.lower() == "input":
            name = ad.get("name")
            if not name:
                return
            typ = ad.get("type", "text").lower()
            if typ in {"checkbox", "radio"} and "checked" not in ad:
                return
            if typ in {"submit", "button", "image"}:
                return
            if name.startswith("ctl00$MainContent$Btn"):
                return
            self.fields[name] = ad.get("value", "")
        if tag.lower() == "select":
            self._select = ad.get("name") or None
            if self._select and self._select not in self.fields:
                self.fields[self._select] = ""
        if tag.lower() == "option" and self._select:
            self._option_value = ad.get("value", "")
            self._option_selected = "selected" in ad
            self._option_text = ""

    def handle_data(self, data: str) -> None:
        if self._select is not None:
            self._option_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "option" and self._select:
            if self._option_selected or not self.fields.get(self._select):
                self.fields[self._select] = self._option_value
            self._option_selected = False
        if tag.lower() == "select":
            self._select = None


def parse_form(html: str) -> dict[str, str]:
    html = (html or "").replace("charset=utf-16", "charset=utf-8")
    p = _FormParser()
    p.feed(html)
    return p.fields


def html_from_delta(source: str) -> str:
    """El SAT manda la tabla dentro de un updatePanel |pipe|."""
    raw = source or ""
    if "AccionCfdi" in raw or "tblResult" in raw:
        chunks = [p for p in raw.split("|") if "AccionCfdi" in p or "tblResult" in p or "<table" in p.lower()]
        return "\n".join(chunks) if chunks else raw
    return raw


def parse_sat_delta(source: str) -> dict[str, str]:
    """Respuesta AJAX del SAT: |len|type|name|value|…"""
    parts = (source or "").split("|")
    wanted = {"__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS", "__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"}
    out: dict[str, str] = {}
    for i, part in enumerate(parts):
        if part in wanted and i + 1 < len(parts):
            out[part] = parts[i + 1]
    return out


def extract_accion_urls(html: str, base: str = PORTAL) -> list[str]:
    urls: list[str] = []
    for raw in ACCION_RE.findall(html or ""):
        cleaned = raw.replace("\\/", "/")
        if cleaned.startswith("http"):
            urls.append(cleaned)
        else:
            urls.append(urljoin(base, cleaned.lstrip("/")))
    return list(dict.fromkeys(urls))


def _sidate(dt: datetime, fmt: str, width: int = 1) -> str:
    return f"{int(dt.strftime(fmt)):0{width}d}"


def _parse_day(text: str) -> date:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return date.today()


def _days(ini: str, fin: str) -> list[date]:
    a = _parse_day(ini)
    b = _parse_day(fin)
    if b < a:
        a, b = b, a
    out: list[date] = []
    cur = a
    while cur <= b:
        out.append(cur)
        cur += timedelta(days=1)
    return out or [date.today()]


def date_filters(sentido: str, day: date, end: date | None = None) -> dict[str, str]:
    start = datetime(day.year, day.month, day.day, 0, 0, 0)
    stop = datetime((end or day).year, (end or day).month, (end or day).day, 23, 59, 59)
    if sentido == "recibidas":
        return {
            "ctl00$MainContent$CldFecha$DdlAnio": start.strftime("%Y"),
            "ctl00$MainContent$CldFecha$DdlMes": _sidate(start, "%m", 1),
            "ctl00$MainContent$CldFecha$DdlDia": _sidate(start, "%d", 2),
            "ctl00$MainContent$CldFecha$DdlHora": _sidate(start, "%H", 1),
            "ctl00$MainContent$CldFecha$DdlMinuto": _sidate(start, "%M", 1),
            "ctl00$MainContent$CldFecha$DdlSegundo": _sidate(start, "%S", 1),
            "ctl00$MainContent$CldFecha$DdlHoraFin": _sidate(stop, "%H", 1),
            "ctl00$MainContent$CldFecha$DdlMinutoFin": _sidate(stop, "%M", 1),
            "ctl00$MainContent$CldFecha$DdlSegundoFin": _sidate(stop, "%S", 1),
        }
    return {
        "ctl00$MainContent$hfInicial": start.strftime("%Y"),
        "ctl00$MainContent$CldFechaInicial2$Calendario_text": start.strftime("%d/%m/%Y"),
        "ctl00$MainContent$CldFechaInicial2$DdlHora": _sidate(start, "%H", 1),
        "ctl00$MainContent$CldFechaInicial2$DdlMinuto": _sidate(start, "%M", 1),
        "ctl00$MainContent$CldFechaInicial2$DdlSegundo": _sidate(start, "%S", 1),
        "ctl00$MainContent$CldFechaFinal2$Calendario_text": stop.strftime("%d/%m/%Y"),
        "ctl00$MainContent$hfFinal": stop.strftime("%Y"),
        "ctl00$MainContent$CldFechaFinal2$DdlHora": _sidate(stop, "%H", 1),
        "ctl00$MainContent$CldFechaFinal2$DdlMinuto": _sidate(stop, "%M", 1),
        "ctl00$MainContent$CldFechaFinal2$DdlSegundo": _sidate(stop, "%S", 1),
    }


def _ajax(sess: requests.Session, url: str, data: dict[str, str]) -> str:
    headers = {
        **AJAX_HEADERS,
        "Referer": url,
        "Origin": "https://portalcfdi.facturaelectronica.sat.gob.mx",
    }
    r = sess.post(url, data=data, headers=headers, timeout=90, allow_redirects=True)
    return r.text or ""


def _select_fechas(sess: requests.Session, url: str, fields: dict[str, str]) -> dict[str, str]:
    post = dict(fields)
    post.update(
        {
            "__ASYNCPOST": "true",
            "__EVENTARGUMENT": "",
            "__EVENTTARGET": "ctl00$MainContent$RdoFechas",
            "__LASTFOCUS": "",
            "ctl00$MainContent$FiltroCentral": "RdoFechas",
            "ctl00$ScriptManager1": "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$RdoFechas",
        }
    )
    html = _ajax(sess, url, post)
    fields.update(parse_sat_delta(html))
    return fields


def _buscar_html(sess: requests.Session, url: str, fields: dict[str, str], extra: dict[str, str]) -> str:
    post = dict(fields)
    post.update(extra)
    post["ctl00$MainContent$BtnBusqueda"] = "Buscar CFDI"
    post["ctl00$MainContent$DdlEstadoComprobante"] = post.get("ctl00$MainContent$DdlEstadoComprobante") or "-1"
    post["__ASYNCPOST"] = "true"
    post["ctl00$ScriptManager1"] = "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$BtnBusqueda"
    post["__EVENTTARGET"] = ""
    return _ajax(sess, url, post)


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
    s = sat_session(insecure=True)
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
    hrefs.extend(extract_accion_urls(html, base))
    hrefs = list(dict.fromkeys(hrefs))
    return uuids, hrefs


def looks_like_xml(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<?xml") or b"<cfdi:comprobante" in head or b"<comprobante" in head


def download_url(sess: requests.Session, url: str, dest_dir: Path) -> Path | None:
    r = sess.get(url, timeout=60, allow_redirects=True, headers={"Referer": PORTAL})
    if r.status_code >= 400 or not r.content:
        return None
    if not looks_like_xml(r.content):
        return None
    found = UUID_RE.search(r.content.decode("utf-8", errors="ignore"))
    name = found.group(0).upper() + ".xml" if found else ""
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
        urljoin(PORTAL, f"Recuperacion/Recuperacion.aspx?folioFiscal={uuid}"),
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
            "en Home y vuelve a Descargar."
        )
    return r.text


def _collect(html: str) -> tuple[list[str], list[str]]:
    return extract_download_targets(html_from_delta(html))


def descargar_con_sesion(
    cookies: list[tuple[str, str, str, str]] | None = None,
    *,
    sentido: str,
    dest: Path,
    extra_html: str = "",
    extra_hrefs: list[str] | None = None,
    sess=None,
    fecha_ini: str = "",
    fecha_fin: str = "",
) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    if sess is None:
        if not cookies:
            raise SatError("La ventana no entregó cookies del SAT. Recarga e inicia sesión.")
        sess = session_from_cookies(cookies)
    html0 = probe_session(sess, sentido).replace("charset=utf-16", "charset=utf-8")
    url = CONSULTA.get(sentido, CONSULTA["recibidas"])
    fields = parse_form(html0)
    if fields:
        fields = _select_fechas(sess, url, fields)

    uuids: list[str] = []
    hrefs: list[str] = []
    days = _days(fecha_ini, fecha_fin)
    for day in days:
        extra = date_filters(sentido, day, day if sentido == "recibidas" else days[-1])
        html = _buscar_html(sess, url, fields, extra)
        fields.update(parse_sat_delta(html))
        u, h = _collect(html)
        uuids.extend(u)
        hrefs.extend(h)
        if sentido == "emitidas":
            break

    if extra_html:
        u2, h2 = extract_download_targets(extra_html)
        uuids.extend(u2)
        hrefs.extend(h2)
    if extra_hrefs:
        hrefs.extend(extra_hrefs)
    uuids = list(dict.fromkeys(uuids))
    hrefs = list(dict.fromkeys(hrefs))

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
        if sentido == "emitidas" and len(days) > 1:
            for day in days:
                html = _buscar_html(sess, url, fields, date_filters("emitidas", day, day))
                fields.update(parse_sat_delta(html))
                u, h = _collect(html)
                for href in h:
                    got = download_url(sess, href, dest)
                    if got:
                        written.append(got)
                have = {p.stem.upper() for p in written}
                for uuid in u:
                    if uuid.upper() in have:
                        continue
                    got = recover_by_uuid(sess, uuid, dest)
                    if got:
                        written.append(got)
                        have.add(uuid.upper())
        if not written:
            raise SatError(
                f"Sesión SAT viva, pero el portal no soltó XML "
                f"({len(uuids)} UUID, {len(hrefs)} ligas). "
                "Prueba un rango más corto o e.firma."
            )
    return written
