"""Sesión del portal SAT (CIEC): AJAX ConsultaReceptor/Emisor + RecuperaCfdi."""

from __future__ import annotations

import re
import io
import zipfile
import uuid as uuidlib
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
PAGE_RE = re.compile(
    r"__doPostBack\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]Page\$(\d+)['\"]",
    re.I,
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0"
)
AJAX_HEADERS = {
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}
XML_WORKERS = 10
XML_WAVES = 40


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
    if "|" not in raw[:80] and "AccionCfdi" not in raw and "tblResult" not in raw:
        return raw
    chunks = [
        p
        for p in raw.split("|")
        if "AccionCfdi" in p
        or "tblResult" in p
        or "<table" in p.lower()
        or "Folio Fiscal" in p
        or "gvCfdi" in p
        or UUID_RE.search(p)
    ]
    return "\n".join(chunks) if chunks else raw


def parse_sat_delta(source: str) -> dict[str, str]:
    """Respuesta AJAX del SAT: |len|type|name|value|…"""
    parts = (source or "").split("|")
    wanted = {
        "__EVENTTARGET",
        "__EVENTARGUMENT",
        "__LASTFOCUS",
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
    }
    out: dict[str, str] = {}
    i = 0
    while i < len(parts):
        name = parts[i]
        if name in wanted and i + 1 < len(parts):
            out[name] = parts[i + 1]
        i += 1
    return out


def _response_text(r: requests.Response) -> str:
    raw = r.content or b""
    head = raw[:500].lower()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"charset=utf-16" in head:
        return raw.decode("utf-16", errors="replace")
    text = r.text or ""
    if "charset=utf-16" in text[:500].lower() and "\x00" in raw[:80].decode("latin-1", errors="ignore"):
        return raw.decode("utf-16", errors="replace")
    return text.replace("charset=utf-16", "charset=utf-8")


AJAX_RDO_FECHAS = {
    "__ASYNCPOST": "true",
    "__EVENTARGUMENT": "",
    "__EVENTTARGET": "ctl00$MainContent$RdoFechas",
    "__LASTFOCUS": "",
    "ctl00$MainContent$FiltroCentral": "RdoFechas",
    "ctl00$ScriptManager1": "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$RdoFechas",
}


def query_filters() -> dict[str, str]:
    return {
        "ctl00$MainContent$BtnBusqueda": "Buscar CFDI",
        "ctl00$MainContent$DdlEstadoComprobante": "-1",
        "ctl00$MainContent$ddlComplementos": "-1",
        "ctl00$MainContent$TxtRfcReceptor": "",
        "ctl00$MainContent$TxtRfcTercero": "",
    }


def extract_accion_urls(html: str, base: str = PORTAL) -> list[str]:
    html = (
        (html or "")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("\\/", "/")
    )
    urls: list[str] = []
    for raw in ACCION_RE.findall(html):
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
        "User-Agent": UA,
        "Referer": url,
        "Origin": "https://portalcfdi.facturaelectronica.sat.gob.mx",
        "Accept": "*/*",
    }
    r = sess.post(url, data=data, headers=headers, timeout=90, allow_redirects=True)
    return _response_text(r)


def _select_fechas(sess: requests.Session, url: str, fields: dict[str, str]) -> dict[str, str]:
    post = dict(fields)
    post.update(AJAX_RDO_FECHAS)
    html = _ajax(sess, url, post)
    fields.update(parse_sat_delta(html))
    return fields


def _buscar_html(
    sess: requests.Session,
    url: str,
    fields: dict[str, str],
    extra: dict[str, str],
    *,
    style: str = "phpcfdi",
) -> str:
    post = dict(fields)
    post.update(AJAX_RDO_FECHAS)
    post.update(query_filters())
    post.update(extra)
    if style == "btn":
        post["__EVENTTARGET"] = ""
        post["ctl00$ScriptManager1"] = "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$BtnBusqueda"
    return _ajax(sess, url, post)


def _buscar_full(sess: requests.Session, url: str, fields: dict[str, str], extra: dict[str, str]) -> str:
    post = dict(fields)
    post.update(query_filters())
    post["ctl00$MainContent$FiltroCentral"] = "RdoFechas"
    post.update(extra)
    post.pop("__ASYNCPOST", None)
    post.pop("ctl00$ScriptManager1", None)
    r = sess.post(
        url,
        data=post,
        headers={"Referer": url, "User-Agent": UA, "Origin": "https://portalcfdi.facturaelectronica.sat.gob.mx"},
        timeout=90,
        allow_redirects=True,
    )
    return _response_text(r)


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


def clone_session(sess: requests.Session) -> requests.Session:
    s = sat_session(insecure=True)
    s.headers.update({"User-Agent": UA, "Referer": PORTAL})
    for c in sess.cookies:
        if c.value is None:
            continue
        s.cookies.set(c.name, c.value, domain=c.domain or ".sat.gob.mx", path=c.path or "/")
    return s


def plan_xml_jobs(hrefs: list[str], uuids: list[str]) -> list[tuple[str, str]]:
    pending = {u.upper() for u in uuids}
    jobs: list[tuple[str, str]] = []
    for href in hrefs:
        jobs.append(("href", href))
        found = UUID_RE.search(href)
        if found:
            pending.discard(found.group(0).upper())
    for u in pending:
        jobs.append(("uuid", u))
    return jobs


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


class _ResultRows(HTMLParser):
    """Filas de la tabla SAT: primer UUID = folio, AccionCfdi = liga."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, str]] = []
        self._in_tr = 0
        self._uuids: list[str] = []
        self._hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "tr":
            self._in_tr += 1
            if self._in_tr == 1:
                self._uuids = []
                self._hrefs = []
        if self._in_tr < 1:
            return
        for key in ("onclick", "href"):
            val = ad.get(key, "")
            if not val:
                continue
            for raw in ACCION_RE.findall(val):
                self._hrefs.append(raw.replace("\\/", "/"))
            if re.search(r"RecuperaCfdi|Recuperacion|DescargaXml", val, re.I) and not val.startswith("javascript:"):
                self._hrefs.append(val)

    def handle_data(self, data: str) -> None:
        if self._in_tr:
            self._uuids.extend(u.upper() for u in UUID_RE.findall(data or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "tr" or self._in_tr < 1:
            return
        self._in_tr -= 1
        if self._in_tr:
            return
        if not self._uuids:
            return
        href = ""
        if self._hrefs:
            raw = self._hrefs[0]
            href = raw if raw.startswith("http") else urljoin(PORTAL, raw.lstrip("/"))
        self.rows.append((self._uuids[0], href))


def extract_table_rows(html: str, base: str = PORTAL) -> list[tuple[str, str]]:
    html = html_from_delta(html or "")
    html = (
        html.replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("\\/", "/")
    )
    p = _ResultRows()
    try:
        p.feed(html)
    except Exception:
        p.rows = []
    if p.rows:
        return p.rows
    out: list[tuple[str, str]] = []
    for row in re.findall(r"<tr\b[^>]*>.*?</tr>", html, flags=re.I | re.S):
        uids = [u.upper() for u in UUID_RE.findall(row)]
        hrefs = extract_accion_urls(row, base)
        if uids:
            out.append((uids[0], hrefs[0] if hrefs else ""))
    return out


def extract_folio_map(html: str, base: str = PORTAL) -> dict[str, str]:
    """UUID de la fila → liga AccionCfdi. Solo si hay botón."""
    out: dict[str, str] = {}
    for uid, href in extract_table_rows(html, base):
        if href:
            out.setdefault(uid, href)
    return out


def extract_download_targets(html: str, base: str = PORTAL) -> tuple[list[str], list[str]]:
    rows = extract_table_rows(html, base)
    uuids = list(dict.fromkeys(u for u, _ in rows))
    hrefs = list(dict.fromkeys(h for _, h in rows if h))
    if uuids or hrefs:
        return uuids, hrefs
    html = html_from_delta(html or "")
    hrefs = extract_accion_urls(html, base)
    parser = _LinkParser()
    parser.feed(html)
    for raw in parser.hrefs:
        if not raw or raw.startswith("javascript:"):
            continue
        if re.search(r"RecuperaCfdi|Recuperacion|DescargaXml", raw, re.I):
            hrefs.append(urljoin(base, raw))
    hrefs = list(dict.fromkeys(hrefs))
    found: list[str] = []
    for h in hrefs:
        found.extend(u.upper() for u in UUID_RE.findall(h))
    return list(dict.fromkeys(found)), hrefs


def looks_like_xml(data: bytes) -> bool:
    sample = data[:4096] if data else b""
    if sample[:2] == b"PK":
        return True
    low = sample.lower()
    if b"\x00" in sample[:80]:
        try:
            low = sample.decode("utf-16", errors="ignore").lower().encode("utf-8", errors="ignore")
        except Exception:
            pass
    return b"<?xml" in low or b"cfdi:comprobante" in low or b"<comprobante" in low


def _xml_bytes(data: bytes) -> bytes | None:
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    raw = zf.read(name)
                    if looks_like_xml(raw) and raw[:2] != b"PK":
                        return raw
        except zipfile.BadZipFile:
            return None
        return None
    return data if looks_like_xml(data) else None


def download_url(sess: requests.Session, url: str, dest_dir: Path, referer: str = PORTAL) -> Path | None:
    if not url:
        return None
    r = sess.get(
        url,
        timeout=(10, 45),
        allow_redirects=True,
        headers={"Referer": referer, "User-Agent": UA, "Accept": "*/*"},
    )
    if r.status_code >= 400 or not r.content:
        return None
    body = _xml_bytes(r.content)
    if body is None:
        return None
    text = body.decode("utf-8", errors="ignore")
    if "\x00" in body[:80].decode("latin-1", errors="ignore"):
        text = body.decode("utf-16", errors="ignore")
    found = UUID_RE.search(text)
    name = found.group(0).upper() + ".xml" if found else f"cfdi-{uuidlib.uuid4().hex[:12]}.xml"
    path = dest_dir / name
    path.write_bytes(body)
    return path


def cfdi_fecha(path: Path) -> date | None:
    raw = path.read_bytes()[:8192]
    m = re.search(br'Fecha="([0-9]{4}-[0-9]{2}-[0-9]{2})', raw)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).decode(), "%Y-%m-%d").date()
    except ValueError:
        return None


def keep_xml(path: Path, ini: date, fin: date) -> bool:
    d = cfdi_fecha(path)
    if d is None:
        return True
    if ini > fin:
        ini, fin = fin, ini
    return ini <= d <= fin


def recover_by_uuid(sess: requests.Session, uuid: str, dest_dir: Path, sentido: str = "recibidas") -> Path | None:
    """Busca el folio en el portal y baja el AccionCfdi. No adivina RecuperaCfdi?uuid=."""
    url = CONSULTA.get(sentido, CONSULTA["recibidas"])
    try:
        r = sess.get(url, timeout=40, allow_redirects=True, headers={"Referer": PORTAL, "User-Agent": UA})
        fields = parse_form(r.text)
        fields.update(parse_sat_delta(r.text))
        fields.update(
            {
                "__ASYNCPOST": "true",
                "__EVENTARGUMENT": "",
                "__EVENTTARGET": "ctl00$MainContent$RdoFolioFiscal",
                "__LASTFOCUS": "",
                "ctl00$MainContent$FiltroCentral": "RdoFolioFiscal",
                "ctl00$ScriptManager1": "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$RdoFolioFiscal",
            }
        )
        html = _ajax(sess, url, fields)
        fields.update(parse_sat_delta(html))
        fields.update(query_filters())
        fields["ctl00$MainContent$FiltroCentral"] = "RdoFolioFiscal"
        fields["ctl00$MainContent$TxtUUID"] = uuid.lower()
        fields["ctl00$MainContent$BtnBusqueda"] = "Buscar CFDI"
        fields["__EVENTTARGET"] = ""
        fields["__EVENTARGUMENT"] = ""
        fields["__ASYNCPOST"] = "true"
        fields["ctl00$ScriptManager1"] = "ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$BtnBusqueda"
        html = _ajax(sess, url, fields)
        _u, hrefs = _collect(html)
        for href in hrefs:
            got = download_url(sess, href, dest_dir)
            if got:
                return got
    except Exception:
        return None
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


def extract_result_pages(html: str) -> list[tuple[str, str]]:
    return list(dict.fromkeys(PAGE_RE.findall(html or "")))


def _page_html(sess: requests.Session, url: str, fields: dict[str, str], target: str, page: str) -> str:
    post = dict(fields)
    post.update(AJAX_RDO_FECHAS)
    post["__EVENTTARGET"] = target
    post["__EVENTARGUMENT"] = f"Page${page}"
    post["ctl00$ScriptManager1"] = f"ctl00$MainContent$UpnlResultados|{target}"
    return _ajax(sess, url, post)


def _collect(html: str) -> tuple[list[str], list[str]]:
    return extract_download_targets(html_from_delta(html))


def _search_once(
    sess: requests.Session,
    url: str,
    fields: dict[str, str],
    extra: dict[str, str],
) -> tuple[list[str], list[str], str, dict[str, str], dict[str, str]]:
    last = ""
    uuids: list[str] = []
    hrefs: list[str] = []
    blob = ""
    for style in ("phpcfdi", "btn"):
        last = _buscar_html(sess, url, fields, extra, style=style)
        fields.update(parse_sat_delta(last))
        uuids, hrefs = _collect(last)
        blob = last
        if uuids or hrefs:
            break
    else:
        last = _buscar_full(sess, url, fields, extra)
        fields.update(parse_sat_delta(last))
        uuids, hrefs = _collect(last)
        blob = last
    seen_pages = {"1"}
    queue = extract_result_pages(last)
    while queue:
        target, page = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        html = _page_html(sess, url, fields, target, page)
        fields.update(parse_sat_delta(html))
        u, h = _collect(html)
        uuids.extend(u)
        hrefs.extend(h)
        last = html
        blob += "\n" + html
        for item in extract_result_pages(html):
            if item[1] not in seen_pages:
                queue.append(item)
    fmap = extract_folio_map(blob)
    extra_links = extract_accion_urls(blob)
    hrefs.extend(extra_links)
    if fmap:
        uuids = list(dict.fromkeys(list(fmap) + uuids))
        hrefs = list(dict.fromkeys(list(fmap.values()) + hrefs))
    else:
        hrefs = list(dict.fromkeys(hrefs))
    return list(dict.fromkeys(uuids)), hrefs, last, fields, fmap


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
    progress=None,
) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)

    def note(**ev) -> None:
        if progress:
            progress(ev)

    if sess is None:
        if not cookies:
            raise SatError("La ventana no entregó cookies del SAT. Recarga e inicia sesión.")
        sess = session_from_cookies(cookies)
    note(phase="consulta", msg="Abriendo consulta SAT…", done=0, total=1)
    url = CONSULTA.get(sentido, CONSULTA["recibidas"])
    probe_session(sess, sentido)

    uuids: list[str] = []
    hrefs: list[str] = []
    folio_href: dict[str, str] = {}
    last_html = ""
    written: list[Path] = []
    have: set[str] = set()
    days = _days(fecha_ini, fecha_fin)
    ini_d, fin_d = days[0], days[-1]

    def mark(got: Path) -> None:
        if not keep_xml(got, ini_d, fin_d):
            got.unlink(missing_ok=True)
            return
        uid = got.stem.upper()
        if uid not in have:
            written.append(got)
            have.add(uid)
        note(
            phase="xml",
            done=len(have),
            total=max(len(uuids), len(have), 1),
            uuid=uid,
            ok=True,
            msg=f"{len(have)} XML  {uid}",
        )

    def open_form() -> dict[str, str]:
        r0 = sess.get(url, timeout=40, allow_redirects=True, headers={"User-Agent": UA, "Referer": PORTAL})
        if not logged_in(r0.text, r0.url):
            raise SatError("Se cayó la sesión SAT. Entra otra vez en Home.")
        fields = parse_form(r0.text)
        if not fields:
            raise SatError("El portal no entregó el formulario de consulta. Reentra en Home.")
        return _select_fechas(sess, url, fields)

    def pull(fields: dict[str, str], day: date, end: date | None = None) -> tuple[list[str], dict[str, str], dict[str, str]]:
        nonlocal last_html
        extra = date_filters(sentido, day, end or day)
        u, h, last_html, fields, fmap = _search_once(sess, url, fields, extra)
        uuids.extend(u)
        hrefs.extend(h)
        folio_href.update(fmap)
        links = list(dict.fromkeys([x for x in list(fmap.values()) + h if x]))
        return links, fields, fmap

    def grab(links: list[str], label: str) -> None:
        n = len(links)
        for j, link in enumerate(links, 1):
            note(
                phase="xml",
                done=len(have),
                total=max(n, 1),
                ok=False,
                msg=f"{label}  {j}/{n} ligas · {len(have)} XML",
            )
            try:
                got = download_url(sess, link, dest, referer=url)
            except Exception:
                got = None
            if got:
                mark(got)

    fields = open_form()
    ndays = len(days)

    if sentido == "emitidas" and ndays > 1:
        note(phase="consulta", msg=f"Emitidas {ini_d} → {fin_d}", done=0, total=1)
        links, fields, fmap = pull(fields, ini_d, fin_d)
        found = len(links) or len(fmap)
        if 0 < found < 500:
            note(phase="consulta", found=found, msg=f"Rango: {found} folios")
            grab(links, "rango")
        else:
            fields = open_form()
            for i, day in enumerate(days, 1):
                note(
                    phase="consulta",
                    day=str(day),
                    day_i=i,
                    days=ndays,
                    done=i,
                    total=ndays,
                    msg=f"Buscando {day}  ({i}/{ndays})",
                )
                try:
                    links, fields, fmap = pull(fields, day, day)
                except SatError:
                    fields = open_form()
                    links, fields, fmap = pull(fields, day, day)
                if links:
                    grab(links, str(day))
    else:
        for i, day in enumerate(days, 1):
            note(
                phase="consulta",
                day=str(day),
                day_i=i,
                days=ndays,
                done=i,
                total=ndays,
                found=len(uuids),
                msg=f"Buscando {day}  ({i}/{ndays})",
            )
            try:
                links, fields, fmap = pull(fields, day, day)
            except SatError:
                fields = open_form()
                links, fields, fmap = pull(fields, day, day)
            found = len(links) or len(fmap)
            if found:
                note(
                    phase="consulta",
                    day=str(day),
                    found=found,
                    msg=f"{day}: {found} folios, {len(links)} ligas",
                )
            grab(links, str(day))

    if extra_html:
        u2, h2 = extract_download_targets(extra_html)
        uuids.extend(u2)
        for link in h2:
            try:
                got = download_url(sess, link, dest, referer=url)
            except Exception:
                got = None
            if got:
                mark(got)
    if extra_hrefs:
        for link in extra_hrefs:
            try:
                got = download_url(sess, link, dest, referer=url)
            except Exception:
                got = None
            if got:
                mark(got)

    uuids = list(dict.fromkeys(u.upper() for u in uuids))
    if not written:
        snippet = re.sub(r"\s+", " ", last_html or "")[:180]
        raise SatError(
            f"No bajó ningún XML ({len(uuids)} folios en la búsqueda). {snippet}"
        )
    note(phase="listo", done=len(written), total=max(len(uuids), len(written)), msg=f"{len(written)} XML listos")
    return written
