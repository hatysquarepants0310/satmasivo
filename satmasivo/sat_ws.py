"""Cliente del Web Service oficial SAT Descarga Masiva v1.5."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import unquote

import requests
from lxml import etree

from satmasivo.fiel import Fiel, c14n, sha1_b64
from satmasivo.http import sat_session

_HTTP = sat_session(insecure=True)

NS_S = "http://schemas.xmlsoap.org/soap/envelope/"
NS_U = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
NS_O = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_AUTH = "http://DescargaMasivaTerceros.gob.mx"
NS_DES = "http://DescargaMasivaTerceros.sat.gob.mx"

HOST_SOL = "https://cfdidescargamasivasolicitud.clouda.sat.gob.mx"
HOST_DES = "https://cfdidescargamasiva.clouda.sat.gob.mx"

AUTH_URL = f"{HOST_SOL}/Autenticacion/Autenticacion.svc"
SOL_URL = f"{HOST_SOL}/SolicitaDescargaService.svc"
VER_URL = f"{HOST_SOL}/VerificaSolicitudDescargaService.svc"
DES_URL = f"{HOST_DES}/DescargaMasivaService.svc"

AUTH_ACTION = "http://DescargaMasivaTerceros.gob.mx/IAutenticacion/Autentica"
SOL_EMIT_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/ISolicitaDescargaService/SolicitaDescargaEmitidos"
SOL_REC_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/ISolicitaDescargaService/SolicitaDescargaRecibidos"
SOL_FOLIO_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/ISolicitaDescargaService/SolicitaDescargaFolio"
VER_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/IVerificaSolicitudDescargaService/VerificaSolicitudDescarga"
DES_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/IDescargaMasivaTercerosService/Descargar"

ESTADO_NOMBRE = {
    1: "Aceptada",
    2: "En proceso",
    3: "Terminada",
    4: "Error",
    5: "Rechazada",
    6: "Vencida",
}


class SatError(RuntimeError):
    pass


@dataclass
class SolicitudResult:
    id_solicitud: str
    codigo: str
    mensaje: str


@dataclass
class VerificaResult:
    codigo: str
    mensaje: str
    estado: int
    estado_nombre: str
    numero_cfdis: int
    paquetes: list[str]


def _post(url: str, action: str, body: bytes, token: str | None = None) -> etree._Element:
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{action}"',
        "Accept-Encoding": "gzip, deflate",
    }
    if token:
        headers["Authorization"] = f'WRAP access_token="{token}"'
    r = _HTTP.post(url, data=body, headers=headers, timeout=90)
    if r.status_code >= 400:
        raise SatError(f"SAT HTTP {r.status_code}: {r.text[:400]}")
    return etree.fromstring(r.content)


def _fault(root: etree._Element) -> None:
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is None:
        return
    code = fault.findtext("faultcode") or ""
    msg = fault.findtext("faultstring") or "Error SOAP del SAT"
    raise SatError(f"{code} {msg}".strip())


def _xml_dsig_enveloped(fiel: Fiel, parent: etree._Element) -> etree._Element:
    digest = sha1_b64(c14n(parent, exclusive=False))
    sig = etree.SubElement(parent, f"{{{NS_DS}}}Signature")
    si = etree.SubElement(sig, f"{{{NS_DS}}}SignedInfo")
    etree.SubElement(
        si,
        f"{{{NS_DS}}}CanonicalizationMethod",
        Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    etree.SubElement(
        si,
        f"{{{NS_DS}}}SignatureMethod",
        Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
    )
    ref = etree.SubElement(si, f"{{{NS_DS}}}Reference", URI="")
    transforms = etree.SubElement(ref, f"{{{NS_DS}}}Transforms")
    etree.SubElement(
        transforms,
        f"{{{NS_DS}}}Transform",
        Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature",
    )
    etree.SubElement(
        ref,
        f"{{{NS_DS}}}DigestMethod",
        Algorithm="http://www.w3.org/2000/09/xmldsig#sha1",
    )
    etree.SubElement(ref, f"{{{NS_DS}}}DigestValue").text = digest
    etree.SubElement(sig, f"{{{NS_DS}}}SignatureValue").text = fiel.sign_sha1(c14n(si, exclusive=False))
    ki = etree.SubElement(sig, f"{{{NS_DS}}}KeyInfo")
    x509 = etree.SubElement(ki, f"{{{NS_DS}}}X509Data")
    iss = etree.SubElement(x509, f"{{{NS_DS}}}X509IssuerSerial")
    etree.SubElement(iss, f"{{{NS_DS}}}X509IssuerName").text = fiel.issuer_rfc4514
    etree.SubElement(iss, f"{{{NS_DS}}}X509SerialNumber").text = fiel.serial_decimal
    etree.SubElement(x509, f"{{{NS_DS}}}X509Certificate").text = fiel.cer_b64
    return sig


class SatMasiva:
    def __init__(self, fiel: Fiel):
        self.fiel = fiel
        self._token: str | None = None
        self._token_exp: datetime | None = None

    def autenticar(self) -> str:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        created = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        expires = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        token_id = f"uuid-{uuid.uuid4()}-1"

        envelope = etree.Element(f"{{{NS_S}}}Envelope", nsmap={"s": NS_S, "u": NS_U})
        header = etree.SubElement(envelope, f"{{{NS_S}}}Header")
        security = etree.SubElement(
            header,
            f"{{{NS_O}}}Security",
            {f"{{{NS_S}}}mustUnderstand": "1"},
            nsmap={"o": NS_O},
        )
        ts = etree.SubElement(security, f"{{{NS_U}}}Timestamp", {f"{{{NS_U}}}Id": "_0"})
        etree.SubElement(ts, f"{{{NS_U}}}Created").text = created
        etree.SubElement(ts, f"{{{NS_U}}}Expires").text = expires
        bst = etree.SubElement(
            security,
            f"{{{NS_O}}}BinarySecurityToken",
            {
                f"{{{NS_U}}}Id": token_id,
                "ValueType": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3",
                "EncodingType": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary",
            },
        )
        bst.text = self.fiel.cer_b64

        sig = etree.SubElement(security, f"{{{NS_DS}}}Signature")
        si = etree.SubElement(sig, f"{{{NS_DS}}}SignedInfo")
        etree.SubElement(
            si,
            f"{{{NS_DS}}}CanonicalizationMethod",
            Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
        )
        etree.SubElement(
            si,
            f"{{{NS_DS}}}SignatureMethod",
            Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
        )
        ref = etree.SubElement(si, f"{{{NS_DS}}}Reference", URI="#_0")
        tr = etree.SubElement(ref, f"{{{NS_DS}}}Transforms")
        etree.SubElement(tr, f"{{{NS_DS}}}Transform", Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
        etree.SubElement(ref, f"{{{NS_DS}}}DigestMethod", Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
        etree.SubElement(ref, f"{{{NS_DS}}}DigestValue").text = sha1_b64(c14n(ts, exclusive=True))
        etree.SubElement(sig, f"{{{NS_DS}}}SignatureValue").text = self.fiel.sign_sha1(c14n(si, exclusive=True))
        ki = etree.SubElement(sig, f"{{{NS_DS}}}KeyInfo")
        str_el = etree.SubElement(ki, f"{{{NS_O}}}SecurityTokenReference")
        etree.SubElement(
            str_el,
            f"{{{NS_O}}}Reference",
            URI=f"#{token_id}",
            ValueType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3",
        )

        body = etree.SubElement(envelope, f"{{{NS_S}}}Body")
        etree.SubElement(body, f"{{{NS_AUTH}}}Autentica")

        root = _post(AUTH_URL, AUTH_ACTION, etree.tostring(envelope, encoding="utf-8", xml_declaration=True))
        _fault(root)
        result = root.find(".//{http://DescargaMasivaTerceros.gob.mx}AutenticaResult")
        if result is None or not result.text:
            raise SatError("El SAT no devolvió token de autenticación.")
        token = unquote(result.text.strip())
        self._token = token
        self._token_exp = datetime.now(timezone.utc) + timedelta(minutes=4)
        return token

    def token(self) -> str:
        now = datetime.now(timezone.utc)
        if not self._token or not self._token_exp or now >= self._token_exp:
            self.autenticar()
        assert self._token
        return self._token

    def solicitar(
        self,
        *,
        sentido: str,
        fecha_inicial: datetime,
        fecha_final: datetime,
        tipo_solicitud: str = "CFDI",
        estado_comprobante: str = "Todos",
        tipo_comprobante: str | None = None,
        folio: str | None = None,
    ) -> SolicitudResult:
        if folio:
            return self._solicitar_folio(folio)

        nsmap = {"soapenv": NS_S, "des": NS_DES}
        env = etree.Element(f"{{{NS_S}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{NS_S}}}Header")
        body = etree.SubElement(env, f"{{{NS_S}}}Body")
        if sentido == "emitidas":
            op = etree.SubElement(body, f"{{{NS_DES}}}SolicitaDescargaEmitidos")
            action = SOL_EMIT_ACTION
            attrs = {
                "RfcEmisor": self.fiel.rfc,
                "RfcSolicitante": self.fiel.rfc,
            }
        else:
            op = etree.SubElement(body, f"{{{NS_DES}}}SolicitaDescargaRecibidos")
            action = SOL_REC_ACTION
            attrs = {
                "RfcReceptor": self.fiel.rfc,
                "RfcSolicitante": self.fiel.rfc,
            }
        attrs.update(
            {
                "FechaInicial": fecha_inicial.strftime("%Y-%m-%dT%H:%M:%S"),
                "FechaFinal": fecha_final.strftime("%Y-%m-%dT%H:%M:%S"),
                "TipoSolicitud": tipo_solicitud,
                "EstadoComprobante": estado_comprobante,
            }
        )
        if tipo_comprobante:
            attrs["TipoComprobante"] = tipo_comprobante
        sol = etree.SubElement(op, f"{{{NS_DES}}}solicitud", attrs)
        _xml_dsig_enveloped(self.fiel, sol)

        root = _post(SOL_URL, action, etree.tostring(env, encoding="utf-8"), self.token())
        _fault(root)
        res = root.find(".//{http://DescargaMasivaTerceros.sat.gob.mx}SolicitaDescargaEmitidosResult")
        if res is None:
            res = root.find(".//{http://DescargaMasivaTerceros.sat.gob.mx}SolicitaDescargaRecibidosResult")
        if res is None:
            # some responses omit namespace prefix variants
            for el in root.iter():
                if el.tag.endswith("Result") and "IdSolicitud" in el.attrib:
                    res = el
                    break
        if res is None:
            raise SatError("Respuesta de solicitud sin resultado.")
        return SolicitudResult(
            id_solicitud=res.get("IdSolicitud", ""),
            codigo=res.get("CodEstatus", ""),
            mensaje=res.get("Mensaje", ""),
        )

    def _solicitar_folio(self, folio: str) -> SolicitudResult:
        nsmap = {"soapenv": NS_S, "des": NS_DES}
        env = etree.Element(f"{{{NS_S}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{NS_S}}}Header")
        body = etree.SubElement(env, f"{{{NS_S}}}Body")
        op = etree.SubElement(body, f"{{{NS_DES}}}SolicitaDescargaFolio")
        sol = etree.SubElement(
            op,
            f"{{{NS_DES}}}solicitud",
            Folio=folio,
            RfcSolicitante=self.fiel.rfc,
        )
        _xml_dsig_enveloped(self.fiel, sol)
        root = _post(SOL_URL, SOL_FOLIO_ACTION, etree.tostring(env, encoding="utf-8"), self.token())
        _fault(root)
        res = None
        for el in root.iter():
            if el.tag.endswith("SolicitaDescargaFolioResult"):
                res = el
                break
        if res is None:
            raise SatError("Respuesta de folio sin resultado.")
        return SolicitudResult(
            id_solicitud=res.get("IdSolicitud", ""),
            codigo=res.get("CodEstatus", ""),
            mensaje=res.get("Mensaje", ""),
        )

    def verificar(self, id_solicitud: str) -> VerificaResult:
        nsmap = {"soapenv": NS_S, "des": NS_DES}
        env = etree.Element(f"{{{NS_S}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{NS_S}}}Header")
        body = etree.SubElement(env, f"{{{NS_S}}}Body")
        op = etree.SubElement(body, f"{{{NS_DES}}}VerificaSolicitudDescarga")
        sol = etree.SubElement(
            op,
            f"{{{NS_DES}}}solicitud",
            IdSolicitud=id_solicitud,
            RfcSolicitante=self.fiel.rfc,
        )
        _xml_dsig_enveloped(self.fiel, sol)
        root = _post(VER_URL, VER_ACTION, etree.tostring(env, encoding="utf-8"), self.token())
        _fault(root)
        res = None
        for el in root.iter():
            if el.tag.endswith("VerificaSolicitudDescargaResult"):
                res = el
                break
        if res is None:
            raise SatError("Respuesta de verificación sin resultado.")
        estado = int(res.get("EstadoSolicitud", "0") or 0)
        paquetes = [n.text for n in res if n.tag.endswith("IdsPaquetes") and n.text]
        return VerificaResult(
            codigo=res.get("CodEstatus", ""),
            mensaje=res.get("Mensaje", ""),
            estado=estado,
            estado_nombre=ESTADO_NOMBRE.get(estado, str(estado)),
            numero_cfdis=int(res.get("NumeroCFDIs", "0") or 0),
            paquetes=paquetes,
        )

    def descargar_paquete(self, id_paquete: str) -> bytes:
        nsmap = {"soapenv": NS_S, "des": NS_DES}
        env = etree.Element(f"{{{NS_S}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{NS_S}}}Header")
        body = etree.SubElement(env, f"{{{NS_S}}}Body")
        op = etree.SubElement(body, f"{{{NS_DES}}}PeticionDescargaMasivaTercerosEntrada")
        pet = etree.SubElement(
            op,
            f"{{{NS_DES}}}peticionDescarga",
            IdPaquete=id_paquete,
            RfcSolicitante=self.fiel.rfc,
        )
        _xml_dsig_enveloped(self.fiel, pet)
        root = _post(DES_URL, DES_ACTION, etree.tostring(env, encoding="utf-8"), self.token())
        _fault(root)
        paquete = None
        for el in root.iter():
            if el.tag.endswith("Paquete") and el.text:
                paquete = el.text
                break
        if not paquete:
            raise SatError(f"El SAT no devolvió bytes del paquete {id_paquete}.")
        import base64

        return base64.b64decode(paquete)


def extraer_zip(data: bytes, destino: str) -> list[str]:
    import io
    import zipfile
    from pathlib import Path

    out: list[str] = []
    dest = Path(destino)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            target = dest / name
            target.write_bytes(zf.read(info))
            out.append(str(target))
            if name.lower().endswith(".zip"):
                out.extend(extraer_zip(target.read_bytes(), str(dest)))
    return out
