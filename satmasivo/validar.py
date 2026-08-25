"""Consulta de estatus ante el SAT (SOAP oficial, no el JSON que da 400)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from xml.etree import ElementTree as ET

from satmasivo.cfdi import CfdiRow
from satmasivo.http import sat_session

SOAP_URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"
SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"
SOAP_WORKERS = 6

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


def consultar_estatus(row: CfdiRow, timeout: float = 8.0) -> CfdiRow:
    if not row.uuid or not row.rfc_emisor or not row.rfc_receptor:
        row.estatus_sat = ""
        return row
    expr = expresion_impresa(row)
    last_err = None
    for _ in range(2):
        try:
            http = sat_session(insecure=True)
            r = http.post(
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
            row.estatus_sat = data.get("Estado") or ""
            row.codigo_estatus = data.get("CodigoEstatus") or ""
            row.cancelable = data.get("EsCancelable") or ""
            row.estatus_cancelacion = data.get("EstatusCancelacion") or ""
            return row
        except Exception as exc:
            last_err = exc
            continue
    del last_err
    row.estatus_sat = ""
    return row


def validar_rows(rows: list[CfdiRow], progress=None) -> list[CfdiRow]:
    total = len(rows)
    if total == 0:
        return []
    out: list[CfdiRow | None] = [None] * total
    done = 0
    workers = min(SOAP_WORKERS, total)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(consultar_estatus, row): i for i, row in enumerate(rows)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                out[i] = fut.result()
            except Exception:
                out[i] = rows[i]
            done += 1
            if progress:
                got = out[i]
                uid = got.uuid if got is not None else rows[i].uuid
                progress(done, total, uid)
    return [r if r is not None else rows[i] for i, r in enumerate(out)]
