"""Login CIEC al SAT: portal → form de captcha → POST en esa misma URL → WS-Fed."""

from __future__ import annotations

import base64
import re
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
from requests.cookies import RequestsCookieJar

from satmasivo.http import sat_session
from satmasivo.sat_ws import SatError

PORTAL = "https://portalcfdi.facturaelectronica.sat.gob.mx/"
AUTH_LOGIN = (
    "https://cfdiau.sat.gob.mx/nidp/app/login"
    "?id=SATUPCFDiCon&sid=0&option=credential&sid=0"
)
AUTH_CIEC = (
    "https://cfdiau.sat.gob.mx/nidp/wsfed/ep"
    "?id=SATUPCFDiCon&sid=0&option=credential&sid=0"
)
TIMEOUT = (15, 40)
CAPTCHA_RE = re.compile(
    r"data:image/(?:jpeg|jpg|png|gif);base64,([A-Za-z0-9+/=\s]+)",
    re.I,
)


def extract_captcha(html: str) -> bytes:
    m = CAPTCHA_RE.search(html or "")
    if not m:
        raise SatError("El SAT no mandó captcha. Reintenta Home.")
    blob = re.sub(r"\s+", "", m.group(1))
    return base64.b64decode(blob)


def looks_like_login(html: str) -> bool:
    return "Ecom_User_ID" in (html or "") and "userCaptcha" in (html or "")


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[tuple[str, str, dict[str, str]]] = []
        self.action = ""
        self.method = "get"
        self.fields: dict[str, str] = {}
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "form":
            if self._in_form:
                self.forms.append((self.action, self.method, dict(self.fields)))
            self._in_form = True
            self.action = ad.get("action", "")
            self.method = (ad.get("method") or "get").lower()
            self.fields = {}
            return
        if not self._in_form or tag.lower() != "input":
            return
        name = ad.get("name")
        if not name:
            return
        self.fields[name] = ad.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._in_form:
            self.forms.append((self.action, self.method, dict(self.fields)))
            self._in_form = False

    def finish(self) -> None:
        if self._in_form:
            self.forms.append((self.action, self.method, dict(self.fields)))
            self._in_form = False


def parse_auto_form(html: str) -> tuple[str, str, dict[str, str]] | None:
    p = _FormParser()
    p.feed(html or "")
    p.finish()
    for action, method, fields in p.forms:
        names = {n.lower() for n in fields}
        if "wresult" in names or "samlresponse" in names:
            return action, method, fields
    return None


def parse_login_form(html: str) -> tuple[str, dict[str, str]] | None:
    p = _FormParser()
    p.feed(html or "")
    p.finish()
    for action, _method, fields in p.forms:
        if "Ecom_User_ID" in fields and "userCaptcha" in fields:
            return action, fields
    return None


def logged_in_portal(html: str, final_url: str, rfc: str = "") -> bool:
    url = (final_url or "").lower()
    if "cfdiau.sat.gob.mx" in url or "/nidp/" in url:
        return False
    if "portalcfdi.facturaelectronica.sat.gob.mx" not in url:
        return False
    if looks_like_login(html):
        return False
    text = html or ""
    if rfc and f"RFC Autenticado: {rfc}" in text:
        return True
    if "RFC Autenticado:" in text:
        return True
    low = text.lower()
    if "logout.aspx" in low or "consultareceptor" in low or "consultaemisor" in low:
        return True
    return "salir" in low and "rfc" in low


@dataclass
class CiecClient:
    rfc: str = ""
    captcha: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        self.sess = sat_session(insecure=True)
        self._lock = threading.Lock()
        self._auth_url = AUTH_CIEC

    def _new_sess(self) -> None:
        self.sess = sat_session(insecure=True)

    def _fresh_socket(self) -> None:
        """Misma cookies, TCP nuevo. El keep-alive del SAT se queda muerto y el POST cuelga 40s."""
        jar = RequestsCookieJar()
        jar.update(self.sess.cookies)
        try:
            self.sess.close()
        except Exception:
            pass
        self.sess = sat_session(insecure=True)
        self.sess.cookies.update(jar)

    def start(self) -> bytes:
        with self._lock:
            self._new_sess()
            last = None
            for url in (PORTAL, AUTH_CIEC, AUTH_LOGIN):
                try:
                    r = self.sess.get(url, timeout=TIMEOUT, allow_redirects=True)
                    last = r
                    if looks_like_login(r.text):
                        self.captcha = extract_captcha(r.text)
                        parsed = parse_login_form(r.text)
                        if parsed and parsed[0]:
                            self._auth_url = urljoin(r.url, parsed[0])
                        else:
                            self._auth_url = r.url
                        return self.captcha
                except Exception as exc:
                    last = exc
                    continue
            if last is not None and hasattr(last, "text"):
                raise SatError(
                    f"El SAT no entregó el login ({last.status_code}, {len(last.content)} bytes)."
                )
            raise SatError(f"El SAT no respondió el login: {last}")

    def _post_wsfed_once(self, html: str, current_url: str) -> tuple[str, str]:
        parsed = parse_auto_form(html)
        if not parsed:
            return html, current_url
        action, method, fields = parsed
        if not action:
            return html, current_url
        url = urljoin(current_url, action)
        if method == "get":
            r = self.sess.get(url, params=fields, timeout=TIMEOUT, allow_redirects=True)
        else:
            r = self.sess.post(url, data=fields, timeout=TIMEOUT, allow_redirects=True)
        return r.text, r.url

    def _reject_login(self, html: str, msg: str) -> None:
        try:
            self.captcha = extract_captcha(html)
        except SatError:
            self.captcha = b""
        raise SatError(msg)

    def login(self, rfc: str, password: str, captcha: str) -> str:
        rfc = rfc.strip().upper()
        with self._lock:
            payload = {
                "option": "credential",
                "submit": "Enviar",
                "Ecom_User_ID": rfc,
                "Ecom_Password": password,
                "userCaptcha": captcha.strip(),
            }
            self._fresh_socket()
            try:
                r = self.sess.post(
                    self._auth_url or AUTH_CIEC,
                    data=payload,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                raise SatError(
                    "No hubo respuesta del login (conexión vieja o SAT callado). "
                    "Pulsa Otro captcha y Enviar otra vez."
                ) from exc
            html, url = r.text, r.url
            if looks_like_login(html):
                self._reject_login(html, "RFC, contraseña o captcha incorrectos.")
            html, url = self._post_wsfed_once(html, url)
            html, url = self._post_wsfed_once(html, url)
            if not logged_in_portal(html, url, rfc):
                try:
                    pr = self.sess.get(PORTAL, timeout=TIMEOUT, allow_redirects=True)
                    html, url = pr.text, pr.url
                    html, url = self._post_wsfed_once(html, url)
                except Exception as exc:
                    raise SatError(f"El SAT no cerró el login: {exc}") from exc
            if not logged_in_portal(html, url, rfc):
                if looks_like_login(html):
                    self._reject_login(html, "RFC, contraseña o captcha incorrectos.")
                raise SatError(
                    "El SAT aceptó el login pero no abrió el portal. Reintenta Home."
                )
            self.rfc = rfc
            return rfc

    def cookie_tuples(self) -> list[tuple[str, str, str, str]]:
        out: list[tuple[str, str, str, str]] = []
        for c in self.sess.cookies:
            out.append((c.name, c.value, c.domain or "", c.path or "/"))
        return out
