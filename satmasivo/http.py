"""HTTPS que acepta el TLS viejo del SAT."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from satmasivo.tlsenv import OPENSSL_CIPHERS


class SatTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers(OPENSSL_CIPHERS)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers(OPENSSL_CIPHERS)
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


def sat_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", SatTLSAdapter())
    return s
