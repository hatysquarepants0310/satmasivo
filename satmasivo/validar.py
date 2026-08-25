"""Consulta de estatus ante el SAT (servicio público de QR)."""

from __future__ import annotations

from urllib.parse import quote

import requests

from satmasivo.cfdi import CfdiRow

CONSULTA = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc/json/Consulta"


def consultar_estatus(row: CfdiRow, timeout: float = 20.0) -> CfdiRow:
    if not row.uuid or not row.rfc_emisor or not row.rfc_receptor:
        row.estatus_sat = "Datos incompletos"
        return row
    total = f"{row.total:.6f}"
    params = {
        "re": row.rfc_emisor,
        "rr": row.rfc_receptor,
        "tt": total,
        "id": row.uuid,
    }
    try:
        r = requests.get(CONSULTA, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        row.estatus_sat = f"Error consulta: {exc}"
        return row
    # SAT JSON keys vary slightly between deployments
    row.estatus_sat = (
        data.get("CodigoEstatus")
        or data.get("EsCancelable")
        or data.get("Estado")
        or ""
    )
    estado = data.get("Estado") or data.get("Estatus") or ""
    if estado:
        row.estatus_sat = str(estado)
    row.cancelable = str(data.get("EsCancelable") or "")
    row.estatus_cancelacion = str(data.get("EstatusCancelacion") or "")
    return row


def validar_rows(rows: list[CfdiRow], progress=None) -> list[CfdiRow]:
    out: list[CfdiRow] = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        out.append(consultar_estatus(row))
        if progress:
            progress(i, total, row.uuid)
    return out
