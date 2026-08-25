"""Consulta de estatus ante el SAT (SOAP oficial, no el JSON que da 400)."""

from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

from satmasivo.cfdi import CfdiRow
from satmasivo.http import sat_session

SOAP_URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"
SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"
_HTTP = sat_session(insecure=True)

NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "a": "http://schemas.datacontract.org/2004/07/Sat.Cfdi.Negocio.ConsultaCfdi.Servicio",
}


def expresion_impresa(row: CfdiRow) -> str:
    total = row.total if isinstance(row.total, Decimal) else Decimal(str(row.total or 0))
    tt = format(total, "f")
    if "." in tt:
        tt = tt.rstrip("0").rstrip(".")
    if "." not in tt:
        tt = tt + ".0"
    parts = [
        f"re={row.rfc_emisor}",
        f"rr={row.rfc_receptor}",
        f"tt={tt}",
        f"id={row.uuid}",
    ]
    if row.sello_cfdi and len(row.sello_cfdi) >= 8:
        parts.append(f"fe={row.sello_cfdi[-8:]}")
    return "?" + "&".join(parts)


def _soap_body(expr: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:tem="http://tempuri.org/">'
        "<soapenv:Header/><soapenv:Body><tem:Consulta>"
        f"<tem:expresionImpresa><![CDATA[{expr}]]></tem:expresionImpresa>"
        "</tem:Consulta></soapenv:Body></soapenv:Envelope>"
    ).encode("utf-8")


def parse_consulta_xml(xml: str) -> dict[str, str]:
    root = ET.fromstring(xml)
    out = {"Estado": "", "EsCancelable": "", "EstatusCancelacion": "", "CodigoEstatus": ""}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in out:
            out[tag] = (el.text or "").strip()
    return out


def consultar_estatus(row: CfdiRow, timeout: float = 25.0) -> CfdiRow:
    if not row.uuid or not row.rfc_emisor or not row.rfc_receptor:
        row.estatus_sat = ""
        return row
    expr = expresion_impresa(row)
    try:
        r = _HTTP.post(
            SOAP_URL,
            data=_soap_body(expr),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": SOAP_ACTION,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = parse_consulta_xml(r.text)
    except Exception:
        row.estatus_sat = ""
        return row
    row.estatus_sat = data.get("Estado") or ""
    row.codigo_estatus = data.get("CodigoEstatus") or ""
    row.cancelable = data.get("EsCancelable") or ""
    row.estatus_cancelacion = data.get("EstatusCancelacion") or ""
    return row


def validar_rows(rows: list[CfdiRow], progress=None) -> list[CfdiRow]:
    out: list[CfdiRow] = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        out.append(consultar_estatus(row))
        if progress:
            progress(i, total, row.uuid)
    return out
