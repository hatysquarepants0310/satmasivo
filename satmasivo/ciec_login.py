"""Login CIEC al SAT: portal → POST JS → formulario real. No usa WebKit."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

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


@dataclass
class CiecClient:
    rfc: str = ""
    captcha: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        self.sess = sat_session(insecure=True)

    def start(self) -> bytes:
        self.sess.get(PORTAL, timeout=40, allow_redirects=True)
        r = self.sess.post(LOGIN_POST, data={}, timeout=40, allow_redirects=True)
        if not r.content or looks_like_login(r.text) is False and len(r.content) < 200:
            # a veces el primer GET a portal ya deja el jsp; el POST es el login
            if not looks_like_login(r.text):
                raise SatError(
                    f"El SAT no entregó el login ({r.status_code}, {len(r.content)} bytes)."
                )
        self.captcha = extract_captcha(r.text)
        return self.captcha

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
            timeout=40,
            allow_redirects=True,
        )
        if looks_like_login(r.text):
            try:
                self.captcha = extract_captcha(r.text)
            except SatError:
                self.captcha = b""
            raise SatError("RFC, contraseña o captcha incorrectos.")
        self.rfc = rfc
        return rfc

    def cookie_tuples(self) -> list[tuple[str, str, str, str]]:
        out: list[tuple[str, str, str, str]] = []
        for c in self.sess.cookies:
            out.append((c.name, c.value, c.domain or "", c.path or "/"))
        return out
