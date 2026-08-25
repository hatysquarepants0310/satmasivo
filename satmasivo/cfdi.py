"""Parser de CFDI 3.3 / 4.0 y retenciones. Sin red."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from lxml import etree

NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "cfdi3": "http://www.sat.gob.mx/cfd/3",
    "pago20": "http://www.sat.gob.mx/Pagos20",
    "pago10": "http://www.sat.gob.mx/Pagos",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}

TIPO_DOC = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}


def _d(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


@dataclass
class CfdiRow:
    archivo: str = ""
    uuid: str = ""
    fecha: str = ""
    tipo_documento: str = ""
    tipo_comprobante: str = ""
    rfc_emisor: str = ""
    nombre_emisor: str = ""
    rfc_receptor: str = ""
    nombre_receptor: str = ""
    serie: str = ""
    folio: str = ""
    moneda: str = ""
    tipo_cambio: str = ""
    subtotal: Decimal = Decimal("0")
    descuento: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    iva_trasladado: Decimal = Decimal("0")
    ieps_trasladado: Decimal = Decimal("0")
    otros_trasladados: Decimal = Decimal("0")
    impuestos_trasladados: Decimal = Decimal("0")
    iva_retenido: Decimal = Decimal("0")
    isr_retenido: Decimal = Decimal("0")
    ieps_retenido: Decimal = Decimal("0")
    impuestos_retenidos: Decimal = Decimal("0")
    forma_pago: str = ""
    metodo_pago: str = ""
    uso_cfdi: str = ""
    complemento_pago: str = "No"
    version: str = ""
    estatus_sat: str = ""
    cancelable: str = ""
    estatus_cancelacion: str = ""

    def as_excel(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d


def _impuestos(node: etree._Element | None) -> dict[str, Decimal]:
    out = {
        "iva_trasladado": Decimal("0"),
        "ieps_trasladado": Decimal("0"),
        "otros_trasladados": Decimal("0"),
        "impuestos_trasladados": Decimal("0"),
        "iva_retenido": Decimal("0"),
        "isr_retenido": Decimal("0"),
        "ieps_retenido": Decimal("0"),
        "impuestos_retenidos": Decimal("0"),
    }
    if node is None:
        return out
    traslados = None
    retenciones = None
    for child in node:
        name = _local(child.tag)
        if name == "Traslados":
            traslados = child
        elif name == "Retenciones":
            retenciones = child
    if traslados is not None:
        total = Decimal("0")
        for t in traslados:
            if _local(t.tag) != "Traslado":
                continue
            imp = t.get("Impuesto", "")
            importe = _d(t.get("Importe"))
            total += importe
            if imp == "002":
                out["iva_trasladado"] += importe
            elif imp == "003":
                out["ieps_trasladado"] += importe
            else:
                out["otros_trasladados"] += importe
        out["impuestos_trasladados"] = total
    if retenciones is not None:
        total = Decimal("0")
        for t in retenciones:
            if _local(t.tag) != "Retencion":
                continue
            imp = t.get("Impuesto", "")
            importe = _d(t.get("Importe"))
            total += importe
            if imp == "002":
                out["iva_retenido"] += importe
            elif imp == "001":
                out["isr_retenido"] += importe
            elif imp == "003":
                out["ieps_retenido"] += importe
        out["impuestos_retenidos"] = total
    return out


def parse_cfdi(path: str | Path) -> CfdiRow:
    p = Path(path)
    tree = etree.parse(str(p))
    root = tree.getroot()
    row = CfdiRow(archivo=str(p))
    if _local(root.tag) != "Comprobante":
        raise ValueError(f"No es un CFDI: {p.name}")
    row.version = root.get("Version", "")
    row.fecha = root.get("Fecha", "")
    tipo = root.get("TipoDeComprobante", "")
    row.tipo_comprobante = tipo
    row.tipo_documento = TIPO_DOC.get(tipo, tipo or "")
    row.serie = root.get("Serie", "")
    row.folio = root.get("Folio", "")
    row.moneda = root.get("Moneda", "")
    row.tipo_cambio = root.get("TipoCambio", "")
    row.subtotal = _d(root.get("SubTotal"))
    row.descuento = _d(root.get("Descuento"))
    row.total = _d(root.get("Total"))
    row.forma_pago = root.get("FormaPago", "")
    row.metodo_pago = root.get("MetodoPago", "")

    emisor = receptor = impuestos = complemento = None
    for child in root:
        name = _local(child.tag)
        if name == "Emisor":
            emisor = child
        elif name == "Receptor":
            receptor = child
        elif name == "Impuestos":
            impuestos = child
        elif name == "Complemento":
            complemento = child
    if emisor is not None:
        row.rfc_emisor = emisor.get("Rfc", "")
        row.nombre_emisor = emisor.get("Nombre", "")
    if receptor is not None:
        row.rfc_receptor = receptor.get("Rfc", "")
        row.nombre_receptor = receptor.get("Nombre", "")
        row.uso_cfdi = receptor.get("UsoCFDI", "")
    row.__dict__.update(_impuestos(impuestos))

    if complemento is not None:
        for child in complemento.iter():
            name = _local(child.tag)
            if name == "TimbreFiscalDigital":
                row.uuid = child.get("UUID", "")
            elif name in {"Pagos", "Pago"}:
                row.complemento_pago = "Sí"
    if tipo == "P":
        row.complemento_pago = "Sí"
    return row


def scan_folder(folder: str | Path) -> list[CfdiRow]:
    root = Path(folder)
    rows: list[CfdiRow] = []
    for xml in sorted(root.rglob("*.xml")):
        try:
            rows.append(parse_cfdi(xml))
        except Exception:
            continue
    return rows
