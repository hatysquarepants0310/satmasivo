"""Login CIEC al SAT: portal → POST credencial → WS-Fed → portalcfdi."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from satmasivo.http import sat_session
from satmasivo.sat_ws import SatError

PORTAL = "https://portalcfdi.facturaelectronica.sat.gob.mx/"
LOGIN_POST = (
    "https://cfdiau.sat.gob.mx/nidp/wsfed/ep"
    "?id=SATUPCFDiCon&sid=0&option=credential&sid=0"
)
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
        if "wresult" in names or "wa" in names or "samlresponse" in names:
            return action, method, fields
    return None


def logged_in_portal(html: str, final_url: str) -> bool:
    url = (final_url or "").lower()
    if "cfdiau.sat.gob.mx" in url or "/nidp/" in url:
        return False
    if "portalcfdi.facturaelectronica.sat.gob.mx" not in url:
        return False
    if looks_like_login(html):
        return False
    low = (html or "").lower()
    if "rfc" in low and "contraseña" in low and "captcha" in low:
        return False
    return True


@dataclass
class CiecClient:
    rfc: str = ""
    captcha: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        self.sess = sat_session(insecure=True)

    def start(self) -> bytes:
        r = self.sess.get(PORTAL, timeout=18, allow_redirects=True)
        if not looks_like_login(r.text):
            r = self.sess.get(LOGIN_POST, timeout=18, allow_redirects=True)
        if not looks_like_login(r.text):
            raise SatError(
                f"El SAT no entregó el login ({r.status_code}, {len(r.content)} bytes)."
            )
        self.captcha = extract_captcha(r.text)
        return self.captcha

    def _follow_wsfed(self, html: str, current_url: str) -> None:
        for _ in range(3):
            parsed = parse_auto_form(html)
            if not parsed:
                break
            action, method, fields = parsed
            if not action:
                break
            url = urljoin(current_url, action)
            if method == "get":
                r = self.sess.get(url, params=fields, timeout=18, allow_redirects=True)
            else:
                r = self.sess.post(url, data=fields, timeout=18, allow_redirects=True)
            html = r.text
            current_url = r.url
            if logged_in_portal(html, current_url):
                return
        r = self.sess.get(PORTAL, timeout=18, allow_redirects=True)
        if not logged_in_portal(r.text, r.url):
            if looks_like_login(r.text):
                try:
                    self.captcha = extract_captcha(r.text)
                except SatError:
                    self.captcha = b""
                raise SatError("RFC, contraseña o captcha incorrectos.")
            raise SatError(
                "El SAT aceptó el login pero no abrió el portal. "
                "Reintenta Home o usa e.firma."
            )

    def login(self, rfc: str, password: str, captcha: str) -> str:
        rfc = rfc.strip().upper()
        r = self.sess.post(
            LOGIN_POST,
            data={
                "option": "credential",
                "Ecom_User_ID": rfc,
                "Ecom_Password": password,
                "userCaptcha": captcha.strip(),
            },
            timeout=18,
            allow_redirects=True,
        )
        if looks_like_login(r.text):
            try:
                self.captcha = extract_captcha(r.text)
            except SatError:
                self.captcha = b""
            raise SatError("RFC, contraseña o captcha incorrectos.")
        self._follow_wsfed(r.text, r.url)
        self.rfc = rfc
        return rfc

    def cookie_tuples(self) -> list[tuple[str, str, str, str]]:
        out: list[tuple[str, str, str, str]] = []
        for c in self.sess.cookies:
            out.append((c.name, c.value, c.domain or "", c.path or "/"))
        return out
