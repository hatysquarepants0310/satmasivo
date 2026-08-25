from pathlib import Path

from satmasivo.cfdi import format_fecha_masiva, parse_cfdi, scan_folder
from satmasivo.excel import RESUMEN_COLS, export_excel
from satmasivo.pdf import cfdi_to_pdf

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_ingreso():
    row = parse_cfdi(FIXTURES / "cfdi_ingreso.xml")
    assert row.uuid == "11111111-2222-3333-4444-555555555555"
    assert row.tipo_documento == "Ingreso"
    assert row.rfc_emisor == "EKU9003173C9"
    assert row.rfc_receptor == "XAXX010101000"
    assert row.iva_trasladado == 160
    assert row.total == 1160
    assert row.forma_pago == "03"
    assert row.complemento_pago == "No"
    assert row.lugar_expedicion == "55700"
    assert row.primer_concepto == "Servicio"
    assert len(row.conceptos) == 1


def test_parse_pago():
    row = parse_cfdi(FIXTURES / "cfdi_pago.xml")
    assert row.tipo_documento == "Pago"
    assert row.complemento_pago == "Sí"


def test_fecha_masiva():
    assert format_fecha_masiva("2026-03-20T14:01:40") == "20/03/2026 02:01:40 p. m."
    assert format_fecha_masiva("2026-03-20T09:06:47") == "20/03/2026 09:06:47 a. m."


def test_scan_and_excel(tmp_path):
    from openpyxl import load_workbook

    rows = scan_folder(FIXTURES)
    assert len(rows) == 2
    dest = tmp_path / "out.xlsx"
    export_excel(rows, dest, rfc_firma="EKU9003173C9")
    wb = load_workbook(dest)
    assert wb.sheetnames == ["Resumen", "Ingresos", "Pagos"]
    headers = [c.value for c in wb["Resumen"][1]]
    assert headers == RESUMEN_COLS
    assert wb["Resumen"]["C2"].value in {"I", "P"}


def test_pdf(tmp_path):
    dest = tmp_path / "f.pdf"
    cfdi_to_pdf(FIXTURES / "cfdi_ingreso.xml", dest)
    assert dest.is_file()
    assert dest.stat().st_size > 500
