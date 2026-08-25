"""Excel al estilo Masiva erpDOZ + hojas de ingresos/egresos."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from satmasivo.cfdi import CfdiRow

# Orden y nombres documentados por erpDOZ (Softonic + erpdoz.com).
# Extra al final: lo que pidió la firma y no sale en ese listado.
COLUMNS = [
    ("fecha", "Fecha"),
    ("tipo_documento", "Tipo de Documento"),
    ("rfc_receptor", "RFC Receptor"),
    ("rfc_emisor", "RFC Emisor"),
    ("nombre_emisor", "Nombre del Emisor"),
    ("nombre_receptor", "Nombre del Receptor"),
    ("serie", "Serie"),
    ("folio", "Folio"),
    ("uuid", "UUID"),
    ("moneda", "Moneda"),
    ("tipo_cambio", "Tipo de cambio"),
    ("subtotal", "Sub Total"),
    ("impuestos_trasladados", "Impuestos trasladados"),
    ("iva_trasladado", "IVA"),
    ("ieps_trasladado", "IEPS"),
    ("iva_retenido", "Impuestos retenidos IVA"),
    ("isr_retenido", "ISR"),
    ("descuento", "Descuento"),
    ("total", "Total"),
    ("estatus_sat", "Vigente"),
    ("forma_pago", "Forma de pago"),
    ("metodo_pago", "Método de pago"),
    ("uso_cfdi", "Uso CFDI"),
    ("complemento_pago", "Complemento de pago"),
    ("ieps_retenido", "IEPS retenido"),
    ("impuestos_retenidos", "Impuestos retenidos"),
    ("cancelable", "Cancelable"),
    ("estatus_cancelacion", "Estatus cancelación"),
    ("archivo", "Archivo"),
]

MASIVA_TITLES = [
    "Fecha",
    "Tipo de Documento",
    "RFC Receptor",
    "RFC Emisor",
    "Nombre del Emisor",
    "Nombre del Receptor",
    "Serie",
    "Folio",
    "UUID",
    "Moneda",
    "Tipo de cambio",
    "Sub Total",
    "Impuestos trasladados",
    "IVA",
    "IEPS",
    "Impuestos retenidos IVA",
    "ISR",
    "Descuento",
    "Total",
    "Vigente",
]

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True, name="Calibri", size=10)
MONEY = "#,##0.00"
THIN = Border(
    left=Side(style="thin", color="BDD7EE"),
    right=Side(style="thin", color="BDD7EE"),
    top=Side(style="thin", color="BDD7EE"),
    bottom=Side(style="thin", color="BDD7EE"),
)
ZEBRA = PatternFill("solid", fgColor="D6EAF8")
MONEY_KEYS = {
    "subtotal",
    "descuento",
    "iva_trasladado",
    "ieps_trasladado",
    "impuestos_trasladados",
    "iva_retenido",
    "isr_retenido",
    "ieps_retenido",
    "impuestos_retenidos",
    "total",
    "tipo_cambio",
}


def _write_sheet(ws: Worksheet, rows: list[CfdiRow]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"
    for col, (_, title) in enumerate(COLUMNS, 1):
        cell = ws.cell(1, col, title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ordered = sorted(rows, key=lambda r: (r.fecha, r.uuid))
    for r_i, row in enumerate(ordered, 2):
        data = row.as_excel()
        for c_i, (key, _) in enumerate(COLUMNS, 1):
            cell = ws.cell(r_i, c_i, data.get(key, ""))
            cell.border = THIN
            cell.alignment = Alignment(vertical="center")
            if r_i % 2 == 0:
                cell.fill = ZEBRA
            if key in MONEY_KEYS and cell.value != "":
                cell.number_format = MONEY
    widths = {
        "A": 20,
        "B": 18,
        "C": 16,
        "D": 16,
        "E": 32,
        "F": 32,
        "I": 38,
        "S": 14,
        "T": 16,
        "AC": 40,
    }
    for col in range(1, len(COLUMNS) + 1):
        letter = get_column_letter(col)
        ws.column_dimensions[letter].width = widths.get(letter, 16)


def _split(rows: list[CfdiRow], rfc_firma: str | None) -> dict[str, list[CfdiRow]]:
    ingresos: list[CfdiRow] = []
    egresos: list[CfdiRow] = []
    pagos: list[CfdiRow] = []
    otros: list[CfdiRow] = []
    rfc = (rfc_firma or "").upper()
    for row in rows:
        if row.tipo_comprobante == "P":
            pagos.append(row)
        elif rfc and row.rfc_emisor.upper() == rfc:
            ingresos.append(row)
        elif rfc and row.rfc_receptor.upper() == rfc:
            egresos.append(row)
        elif row.tipo_comprobante == "I":
            ingresos.append(row)
        elif row.tipo_comprobante == "E":
            egresos.append(row)
        else:
            otros.append(row)
    return {
        "Reporte": rows,
        "Ingresos": ingresos,
        "Egresos": egresos,
        "Pagos": pagos,
        "Otros": otros,
    }


def export_excel(rows: list[CfdiRow], path: str | Path, rfc_firma: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    groups = _split(rows, rfc_firma)
    wb = Workbook()
    first = True
    for name, data in groups.items():
        if first:
            ws = wb.active
            if ws is None:
                ws = wb.create_sheet(name)
            else:
                ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        _write_sheet(ws, data)
    wb.save(path)
    return path
