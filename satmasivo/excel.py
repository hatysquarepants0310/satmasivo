"""Excel ordenado: ingresos, egresos y todo."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from satmasivo.cfdi import CfdiRow

COLUMNS = [
    ("uuid", "UUID"),
    ("fecha", "Fecha"),
    ("tipo_documento", "Tipo de documento"),
    ("rfc_emisor", "RFC emisor"),
    ("nombre_emisor", "Nombre emisor"),
    ("rfc_receptor", "RFC receptor"),
    ("nombre_receptor", "Nombre receptor"),
    ("serie", "Serie"),
    ("folio", "Folio"),
    ("moneda", "Moneda"),
    ("tipo_cambio", "Tipo de cambio"),
    ("subtotal", "Subtotal"),
    ("descuento", "Descuento"),
    ("iva_trasladado", "IVA trasladado"),
    ("ieps_trasladado", "IEPS trasladado"),
    ("impuestos_trasladados", "Impuestos trasladados"),
    ("iva_retenido", "IVA retenido"),
    ("isr_retenido", "ISR retenido"),
    ("ieps_retenido", "IEPS retenido"),
    ("impuestos_retenidos", "Impuestos retenidos"),
    ("total", "Total"),
    ("forma_pago", "Forma de pago"),
    ("metodo_pago", "Método de pago"),
    ("uso_cfdi", "Uso CFDI"),
    ("complemento_pago", "Complemento de pago"),
    ("estatus_sat", "Estatus SAT"),
    ("cancelable", "Cancelable"),
    ("estatus_cancelacion", "Estatus cancelación"),
    ("archivo", "Archivo"),
]

HEADER_FILL = PatternFill("solid", fgColor="0B3D91")
HEADER_FONT = Font(color="FFFFFF", bold=True, name="Calibri", size=10)
MONEY = "#,##0.00"
THIN = Border(
    left=Side(style="thin", color="D0D5DD"),
    right=Side(style="thin", color="D0D5DD"),
    top=Side(style="thin", color="D0D5DD"),
    bottom=Side(style="thin", color="D0D5DD"),
)
ZEBRA = PatternFill("solid", fgColor="F4F7FB")


def _write_sheet(ws, rows: list[CfdiRow]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"
    for col, (_, title) in enumerate(COLUMNS, 1):
        cell = ws.cell(1, col, title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28
    money_keys = {
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
    for r_i, row in enumerate(rows, 2):
        data = row.as_excel()
        for c_i, (key, _) in enumerate(COLUMNS, 1):
            cell = ws.cell(r_i, c_i, data.get(key, ""))
            cell.border = THIN
            cell.alignment = Alignment(vertical="center")
            if r_i % 2 == 0:
                cell.fill = ZEBRA
            if key in money_keys and cell.value != "":
                cell.number_format = MONEY
    for col in range(1, len(COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["E"].width = 32
    ws.column_dimensions["G"].width = 32


def export_excel(rows: list[CfdiRow], path: str | Path, rfc_firma: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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

    wb = Workbook()
    sheets = [
        ("Todos", rows),
        ("Ingresos", ingresos),
        ("Egresos", egresos),
        ("Pagos", pagos),
        ("Otros", otros),
    ]
    first = True
    for name, data in sheets:
        ws = wb.active if first else wb.create_sheet(name)
        if first:
            ws.title = name
            first = False
        _write_sheet(ws, data)
    wb.save(path)
    return path
