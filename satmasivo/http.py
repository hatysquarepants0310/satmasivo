"""HTTPS que acepta el TLS viejo del SAT (DH-1024 y cadena incompleta)."""

from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from satmasivo.tlsenv import OPENSSL_CIPHERS


class SatTLSAdapter(HTTPAdapter):
    def __init__(self, *args, insecure: bool = False, **kwargs):
        self._insecure = insecure
        super().__init__(*args, **kwargs)

    def _ctx(self):
        ctx = create_urllib3_context()
        ctx.set_ciphers(OPENSSL_CIPHERS)
        if self._insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().proxy_manager_for(*args, **kwargs)


def sat_session(*, insecure: bool = False) -> requests.Session:
    s = requests.Session()
    s.mount("https://", SatTLSAdapter(insecure=insecure))
    if insecure:
        s.verify = False
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        }
    )
    return s
