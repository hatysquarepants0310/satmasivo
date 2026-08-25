"""TLS del SAT: cfdiau ofrece DHE-1024 y GnuTLS/OpenSSL 3 lo rechazan.

Hay que aplicar esto ANTES de importar gi / glib-networking.
"""

from __future__ import annotations

import os
import ssl

# Prefer ECDHE (el SAT sí lo tiene). Si cae a DHE-1024, bajar el piso.
GNUTLS_PRIORITY = "NORMAL:-DHE-RSA:-DHE-DSS:%COMPAT:%PROFILE_VERY_WEAK"
OPENSSL_CIPHERS = "DEFAULT:@SECLEVEL=1"


def apply() -> None:
    os.environ.setdefault("G_TLS_GNUTLS_PRIORITY", GNUTLS_PRIORITY)
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")


def openssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.set_ciphers(OPENSSL_CIPHERS)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx
