"""Parser de CFDI 3.3 / 4.0, conceptos, pagos 1.0/2.0 y retenciones."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    "implocal": "http://www.sat.gob.mx/implocal",
}

TIPO_DOC = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}

REGIMEN = {
    "601": "601 General de Ley Personas Morales",
    "603": "603 Personas Morales con Fines no Lucrativos",
    "605": "605 Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "606 Arrendamiento",
    "607": "607 Régimen de Enajenación o Adquisición de Bienes",
    "608": "608 Demás ingresos",
    "610": "610 Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "611 Ingresos por Dividendos (socios y accionistas)",
    "612": "612 Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "614 Ingresos por intereses",
    "615": "615 Régimen de los ingresos por obtención de premios",
    "616": "616 Sin obligaciones fiscales",
    "620": "620 Sociedades Cooperativas de Producción que optan por diferir sus ingresos",
    "621": "621 Incorporación Fiscal",
    "622": "622 Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "623 Opcional para Grupos de Sociedades",
    "624": "624 Coordinados",
    "625": "625 Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "626 Régimen Simplificado de Confianza",
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


def regimen_label(code: str) -> str:
    code = (code or "").strip()
    return REGIMEN.get(code, code)


def format_fecha_masiva(iso: str) -> str:
    raw = (iso or "").replace("T", " ").strip()
    if not raw:
        return ""
    date_part = raw[:10]
    time_part = raw[11:19] if len(raw) >= 19 else raw[11:]
    try:
        y, m, d = date_part.split("-")
        day = f"{d}/{m}/{y}"
    except ValueError:
        return raw
    if not time_part:
        return day
    try:
        hh, mm, ss = (time_part + ":00:00").split(":")[:3]
        h = int(hh)
        if h == 0 and mm == "00" and ss == "00":
            return day
        ampm = "a. m." if h < 12 else "p. m."
        h12 = h % 12 or 12
        return f"{day} {h12:02d}:{mm}:{ss} {ampm}"
    except ValueError:
        return day


@dataclass
class Concepto:
    clave_prod: str = ""
    no_id: str = ""
    cantidad: str = ""
    clave_unidad: str = ""
    unidad: str = ""
    descripcion: str = ""
    valor_unitario: Decimal = Decimal("0")
    importe: Decimal = Decimal("0")
    descuento: Decimal = Decimal("0")
    base_iva_exento: Decimal = Decimal("0")
    iva_exento: Decimal = Decimal("0")
    base_iva_0: Decimal = Decimal("0")
    iva_0: Decimal = Decimal("0")
    base_iva_8: Decimal = Decimal("0")
    iva_8: Decimal = Decimal("0")
    base_iva_16: Decimal = Decimal("0")
    iva_16: Decimal = Decimal("0")
    base_ieps: Decimal = Decimal("0")
    ieps: Decimal = Decimal("0")
    base_ret_iva: Decimal = Decimal("0")
    ret_iva: Decimal = Decimal("0")
    base_ret_isr: Decimal = Decimal("0")
    ret_isr: Decimal = Decimal("0")
    pedimento: str = ""
    predial: str = ""


@dataclass
class PagoDocto:
    forma_pago: str = ""
    fecha_pago: str = ""
    num_operacion: str = ""
    tipo_cambio: str = ""
    monto: Decimal = Decimal("0")
    moneda: str = ""
    num_parcialidad: str = ""
    uuid_dr: str = ""
    folio_dr: str = ""
    serie_dr: str = ""
    moneda_dr: str = ""
    tc_dr: str = ""
    saldo_ant: Decimal = Decimal("0")
    pago: Decimal = Decimal("0")
    saldo_insoluto: Decimal = Decimal("0")


@dataclass
class CfdiRow:
    archivo: str = ""
    uuid: str = ""
    sello_cfdi: str = ""
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
    codigo_estatus: str = ""
    cancelable: str = ""
    estatus_cancelacion: str = ""
    rec_dom_fiscal: str = ""
    rec_regimen: str = ""
    rec_residencia: str = ""
    rec_num_reg_trib: str = ""
    lugar_expedicion: str = ""
    regimen_fiscal: str = ""
    num_cta_pago: str = ""
    condiciones_pago: str = ""
    confirmacion: str = ""
    tipo_relacion: str = ""
    cfdi_relacionados: str = ""
    imp_local_ret: Decimal = Decimal("0")
    imp_local_tras: Decimal = Decimal("0")
    imp_local_det_ret: str = ""
    imp_local_det_tras: str = ""
    conceptos: list[Concepto] = field(default_factory=list)
    pagos: list[PagoDocto] = field(default_factory=list)

    def as_excel(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "fecha": self.fecha,
            "tipo_documento": self.tipo_documento,
            "tipo_comprobante": self.tipo_comprobante,
            "rfc_emisor": self.rfc_emisor,
            "nombre_emisor": self.nombre_emisor,
            "rfc_receptor": self.rfc_receptor,
            "nombre_receptor": self.nombre_receptor,
            "serie": self.serie,
            "folio": self.folio,
            "moneda": self.moneda,
            "tipo_cambio": self.tipo_cambio,
            "subtotal": float(self.subtotal),
            "descuento": float(self.descuento),
            "iva_trasladado": float(self.iva_trasladado),
            "ieps_trasladado": float(self.ieps_trasladado),
            "impuestos_trasladados": float(self.impuestos_trasladados),
            "iva_retenido": float(self.iva_retenido),
            "isr_retenido": float(self.isr_retenido),
            "ieps_retenido": float(self.ieps_retenido),
            "impuestos_retenidos": float(self.impuestos_retenidos),
            "total": float(self.total),
            "forma_pago": self.forma_pago,
            "metodo_pago": self.metodo_pago,
            "uso_cfdi": self.uso_cfdi,
            "complemento_pago": self.complemento_pago,
            "estatus_sat": self.estatus_sat,
            "cancelable": self.cancelable,
            "estatus_cancelacion": self.estatus_cancelacion,
            "archivo": self.archivo,
        }

    @property
    def primer_concepto(self) -> str:
        return self.texto_conceptos.split("\n", 1)[0] if self.texto_conceptos else ""

    @property
    def texto_conceptos(self) -> str:
        parts = [c.descripcion.strip() for c in self.conceptos if c.descripcion and str(c.descripcion).strip()]
        if parts:
            return "\n".join(parts)
        return "Pago" if self.tipo_comprobante == "P" else ""


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
        out["impuestos_trasladados"] = total or _d(node.get("TotalImpuestosTrasladados"))
    elif node.get("TotalImpuestosTrasladados"):
        out["impuestos_trasladados"] = _d(node.get("TotalImpuestosTrasladados"))
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
        out["impuestos_retenidos"] = total or _d(node.get("TotalImpuestosRetenidos"))
    return out


def _concepto_impuestos(concepto: Concepto, impuestos: etree._Element | None) -> None:
    if impuestos is None:
        return
    for child in impuestos:
        name = _local(child.tag)
        if name == "Traslados":
            for t in child:
                if _local(t.tag) != "Traslado":
                    continue
                imp = t.get("Impuesto", "")
                factor = (t.get("TipoFactor") or "").lower()
                tasa = t.get("TasaOCuota") or ""
                base = _d(t.get("Base"))
                importe = _d(t.get("Importe"))
                if imp == "002" and factor == "exento":
                    concepto.base_iva_exento += base
                elif imp == "002" and tasa.startswith("0.000"):
                    concepto.base_iva_0 += base
                    concepto.iva_0 += importe
                elif imp == "002" and tasa.startswith("0.080"):
                    concepto.base_iva_8 += base
                    concepto.iva_8 += importe
                elif imp == "002":
                    concepto.base_iva_16 += base
                    concepto.iva_16 += importe
                elif imp == "003":
                    concepto.base_ieps += base
                    concepto.ieps += importe
        elif name == "Retenciones":
            for t in child:
                if _local(t.tag) != "Retencion":
                    continue
                imp = t.get("Impuesto", "")
                base = _d(t.get("Base"))
                importe = _d(t.get("Importe"))
                if imp == "002":
                    concepto.base_ret_iva += base
                    concepto.ret_iva += importe
                elif imp == "001":
                    concepto.base_ret_isr += base
                    concepto.ret_isr += importe


def _parse_conceptos(root: etree._Element) -> list[Concepto]:
    out: list[Concepto] = []
    for child in root:
        if _local(child.tag) != "Conceptos":
            continue
        for node in child:
            if _local(node.tag) != "Concepto":
                continue
            c = Concepto(
                clave_prod=node.get("ClaveProdServ", ""),
                no_id=node.get("NoIdentificacion", ""),
                cantidad=node.get("Cantidad", ""),
                clave_unidad=node.get("ClaveUnidad", ""),
                unidad=node.get("Unidad", ""),
                descripcion=node.get("Descripcion", ""),
                valor_unitario=_d(node.get("ValorUnitario")),
                importe=_d(node.get("Importe")),
                descuento=_d(node.get("Descuento")),
            )
            impuestos = None
            for sub in node:
                n = _local(sub.tag)
                if n == "Impuestos":
                    impuestos = sub
                elif n == "InformacionAduanera":
                    ped = sub.get("NumeroPedimento", "")
                    if ped:
                        c.pedimento = ped if not c.pedimento else f"{c.pedimento}|{ped}"
                elif n == "CuentaPredial":
                    c.predial = sub.get("Numero", "")
            _concepto_impuestos(c, impuestos)
            out.append(c)
    return out


def _parse_pagos(complemento: etree._Element | None) -> list[PagoDocto]:
    if complemento is None:
        return []
    rows: list[PagoDocto] = []
    for child in complemento.iter():
        name = _local(child.tag)
        if name != "Pago":
            continue
        base = PagoDocto(
            forma_pago=child.get("FormaDePagoP", "") or child.get("FormaDePago", ""),
            fecha_pago=child.get("FechaPago", ""),
            num_operacion=child.get("NumOperacion", ""),
            tipo_cambio=child.get("TipoCambioP", "") or child.get("TipoCambio", ""),
            monto=_d(child.get("Monto")),
            moneda=child.get("MonedaP", "") or child.get("Moneda", ""),
        )
        doctos = [n for n in child if _local(n.tag) in {"DoctoRelacionado"}]
        if not doctos:
            rows.append(base)
            continue
        for d in doctos:
            row = PagoDocto(
                forma_pago=base.forma_pago,
                fecha_pago=base.fecha_pago,
                num_operacion=base.num_operacion,
                tipo_cambio=base.tipo_cambio,
                monto=base.monto,
                moneda=base.moneda,
                num_parcialidad=d.get("NumParcialidad", ""),
                uuid_dr=d.get("IdDocumento", ""),
                folio_dr=d.get("Folio", ""),
                serie_dr=d.get("Serie", ""),
                moneda_dr=d.get("MonedaDR", "") or d.get("Moneda", ""),
                tc_dr=d.get("EquivalenciaDR", "") or d.get("TipoCambioDR", ""),
                saldo_ant=_d(d.get("ImpSaldoAnt")),
                pago=_d(d.get("ImpPagado")),
                saldo_insoluto=_d(d.get("ImpSaldoInsoluto")),
            )
            rows.append(row)
    return rows


def _parse_implocal(complemento: etree._Element | None) -> tuple[Decimal, Decimal, str, str]:
    ret = Decimal("0")
    tras = Decimal("0")
    det_r: list[str] = []
    det_t: list[str] = []
    if complemento is None:
        return ret, tras, "", ""
    for child in complemento.iter():
        name = _local(child.tag)
        if name == "RetencionesLocales":
            imp = _d(child.get("Importe"))
            ret += imp
            det_r.append(f"{child.get('ImpLocRetenido', '')}:{imp}")
        elif name == "TrasladosLocales":
            imp = _d(child.get("Importe"))
            tras += imp
            det_t.append(f"{child.get('ImpLocTrasladado', '')}:{imp}")
    return ret, tras, "|".join(det_r), "|".join(det_t)


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
    row.lugar_expedicion = root.get("LugarExpedicion", "")
    row.num_cta_pago = root.get("NumCtaPago", "")
    row.condiciones_pago = root.get("CondicionesDePago", "")
    row.confirmacion = root.get("Confirmacion", "")

    emisor = receptor = impuestos = complemento = relacionados = None
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
        elif name == "CfdiRelacionados":
            relacionados = child
    if emisor is not None:
        row.rfc_emisor = emisor.get("Rfc", "")
        row.nombre_emisor = emisor.get("Nombre", "")
        row.regimen_fiscal = emisor.get("RegimenFiscal", "")
    if receptor is not None:
        row.rfc_receptor = receptor.get("Rfc", "")
        row.nombre_receptor = receptor.get("Nombre", "")
        row.uso_cfdi = receptor.get("UsoCFDI", "")
        row.rec_dom_fiscal = receptor.get("DomicilioFiscalReceptor", "")
        row.rec_regimen = receptor.get("RegimenFiscalReceptor", "")
        row.rec_residencia = receptor.get("ResidenciaFiscal", "")
        row.rec_num_reg_trib = receptor.get("NumRegIdTrib", "")
    row.__dict__.update(_impuestos(impuestos))
    row.conceptos = _parse_conceptos(root)
    if relacionados is not None:
        row.tipo_relacion = relacionados.get("TipoRelacion", "")
        uuids = [n.get("UUID", "") for n in relacionados if _local(n.tag) == "CfdiRelacionado"]
        row.cfdi_relacionados = ",".join(u for u in uuids if u)
    if complemento is not None:
        for child in complemento.iter():
            name = _local(child.tag)
            if name == "TimbreFiscalDigital":
                row.uuid = child.get("UUID", "")
                row.sello_cfdi = child.get("SelloCFD", "") or child.get("SelloCFDI", "")
            elif name in {"Pagos", "Pago"}:
                row.complemento_pago = "Sí"
        row.pagos = _parse_pagos(complemento)
        loc = _parse_implocal(complemento)
        row.imp_local_ret, row.imp_local_tras, row.imp_local_det_ret, row.imp_local_det_tras = loc
    if tipo == "P":
        row.complemento_pago = "Sí"
    return row


def scan_folder(folder: str | Path, fecha_ini: str = "", fecha_fin: str = "") -> list[CfdiRow]:
    root = Path(folder)
    ini = _parse_bound(fecha_ini)
    fin = _parse_bound(fecha_fin)
    rows: list[CfdiRow] = []
    for xml in sorted(root.rglob("*.xml")):
        try:
            row = parse_cfdi(xml)
        except Exception:
            continue
        lo, hi = _rango_cerca(xml, root)
        if ini:
            lo = ini
        if fin:
            hi = fin
        day = _row_day(row)
        if lo and day and day < lo:
            continue
        if hi and day and day > hi:
            continue
        rows.append(row)
    return rows


def _parse_bound(text: str):
    text = (text or "").strip()[:10]
    if not text:
        return None
    from datetime import datetime as _dt
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return _dt.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _row_day(row: CfdiRow):
    raw = (row.fecha or "")[:10]
    from datetime import datetime as _dt
    try:
        return _dt.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _rango_cerca(xml: Path, root: Path):
    import json
    cur = xml.parent
    root = root.resolve()
    for _ in range(4):
        f = cur / "rango.json"
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            return _parse_bound(str(data.get("ini") or "")), _parse_bound(str(data.get("fin") or ""))
        if cur.resolve() == root or cur.parent == cur:
            break
        cur = cur.parent
    return None, None
