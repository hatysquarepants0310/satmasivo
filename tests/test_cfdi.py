from pathlib import Path

from satmasivo.cfdi import parse_cfdi, scan_folder
from satmasivo.excel import export_excel
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


def test_parse_pago():
    row = parse_cfdi(FIXTURES / "cfdi_pago.xml")
    assert row.tipo_documento == "Pago"
    assert row.complemento_pago == "Sí"


def test_scan_and_excel(tmp_path):
    rows = scan_folder(FIXTURES)
    assert len(rows) == 2
    dest = tmp_path / "out.xlsx"
    export_excel(rows, dest, rfc_firma="EKU9003173C9")
    assert dest.is_file()
    assert dest.stat().st_size > 2000


def test_pdf(tmp_path):
    dest = tmp_path / "f.pdf"
    cfdi_to_pdf(FIXTURES / "cfdi_ingreso.xml", dest)
    assert dest.is_file()
    assert dest.stat().st_size > 500
