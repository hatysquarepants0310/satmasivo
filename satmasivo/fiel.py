"""Carga de e.firma (.cer + .key). La contraseña no se escribe a disco."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree


_UNIQUE_ID = x509.ObjectIdentifier("2.5.4.45")


@dataclass
class Fiel:
    certificate: x509.Certificate
    private_key: object
    rfc: str
    cer_der: bytes

    @property
    def cer_b64(self) -> str:
        return base64.b64encode(self.cer_der).decode("ascii")

    @property
    def serial_decimal(self) -> str:
        return str(self.certificate.serial_number)

    @property
    def issuer_rfc4514(self) -> str:
        return self.certificate.issuer.rfc4514_string()

    def sign_sha1(self, data: bytes) -> str:
        sig = self.private_key.sign(data, padding.PKCS1v15(), hashes.SHA1())
        return base64.b64encode(sig).decode("ascii")


def _rfc_from_cert(cert: x509.Certificate) -> str:
    for oid in (_UNIQUE_ID, NameOID.SERIAL_NUMBER):
        attrs = cert.subject.get_attributes_for_oid(oid)
        if attrs:
            raw = attrs[0].value
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            token = raw.replace("\x00", " ").split("/")[0].strip().split()[0]
            if token:
                return token.upper()
    return ""


def load_fiel(cer_path: str | Path, key_path: str | Path, password: str) -> Fiel:
    cer_der = Path(cer_path).read_bytes()
    if b"BEGIN CERTIFICATE" in cer_der:
        cert = x509.load_pem_x509_certificate(cer_der)
        cer_der = cert.public_bytes(serialization.Encoding.DER)
    else:
        cert = x509.load_der_x509_certificate(cer_der)

    key_bytes = Path(key_path).read_bytes()
    pwd = password.encode("utf-8") if password else None
    try:
        key = serialization.load_der_private_key(key_bytes, password=pwd)
    except ValueError:
        key = serialization.load_pem_private_key(key_bytes, password=pwd)

    rfc = _rfc_from_cert(cert)
    if not rfc:
        raise ValueError("No se pudo leer el RFC del certificado FIEL.")
    return Fiel(certificate=cert, private_key=key, rfc=rfc, cer_der=cer_der)


def load_pfx(pfx_path: str | Path, password: str) -> Fiel:
    data = Path(pfx_path).read_bytes()
    key, cert, _ = pkcs12.load_key_and_certificates(data, password.encode("utf-8"))
    if key is None or cert is None:
        raise ValueError("El PFX no contiene e.firma completa.")
    cer_der = cert.public_bytes(serialization.Encoding.DER)
    rfc = _rfc_from_cert(cert)
    if not rfc:
        raise ValueError("No se pudo leer el RFC del certificado FIEL.")
    return Fiel(certificate=cert, private_key=key, rfc=rfc, cer_der=cer_der)


def c14n(el: etree._Element, exclusive: bool = True) -> bytes:
    return etree.tostring(el, method="c14n", exclusive=exclusive, with_comments=False)


def sha1_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha1(data).digest()).decode("ascii")
