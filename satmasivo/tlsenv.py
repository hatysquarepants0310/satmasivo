"""TLS del SAT: cfdiau ofrece DHE-1024 y la cadena a veces no cierra.

Aplicar ANTES de importar gi / glib-networking.
No uses setdefault: un launcher viejo dejaría la prioridad mala.
"""

from __future__ import annotations

import os
import ssl

# Aceptar DHE-1024 y perfiles débiles. El SAT no ofrece otra cosa en cfdiau.
GNUTLS_PRIORITY = "NORMAL:%COMPAT:%PROFILE_VERY_WEAK"
OPENSSL_CIPHERS = "DEFAULT:@SECLEVEL=1"


def apply() -> None:
    os.environ["G_TLS_GNUTLS_PRIORITY"] = GNUTLS_PRIORITY
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")


def openssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.set_ciphers(OPENSSL_CIPHERS)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def is_sat_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host == "sat.gob.mx" or host.endswith(".sat.gob.mx")
