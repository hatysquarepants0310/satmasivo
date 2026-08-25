"""Representación impresa simple de un CFDI a PDF."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from satmasivo.cfdi import parse_cfdi


NAVY = colors.HexColor("#0B3D91")


def cfdi_to_pdf(xml_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    xml_path = Path(xml_path)
    row = parse_cfdi(xml_path)
    pdf_path = Path(pdf_path) if pdf_path else xml_path.with_suffix(".pdf")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], textColor=NAVY, fontSize=16, spaceAfter=8)
    label = ParagraphStyle("l", parent=styles["Normal"], fontSize=9, leading=12)
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
    )
    data = [
        ["UUID", row.uuid],
        ["Fecha", row.fecha],
        ["Tipo", row.tipo_documento],
        ["Emisor", f"{row.rfc_emisor}  {row.nombre_emisor}"],
        ["Receptor", f"{row.rfc_receptor}  {row.nombre_receptor}"],
        ["Serie / Folio", f"{row.serie} {row.folio}".strip()],
        ["Moneda / TC", f"{row.moneda}  {row.tipo_cambio}"],
        ["Subtotal", f"{row.subtotal:.2f}"],
        ["Descuento", f"{row.descuento:.2f}"],
        ["IVA trasladado", f"{row.iva_trasladado:.2f}"],
        ["IEPS trasladado", f"{row.ieps_trasladado:.2f}"],
        ["IVA retenido", f"{row.iva_retenido:.2f}"],
        ["ISR retenido", f"{row.isr_retenido:.2f}"],
        ["Total", f"{row.total:.2f}"],
        ["Forma / método", f"{row.forma_pago} / {row.metodo_pago}"],
        ["Uso CFDI", row.uso_cfdi],
        ["Complemento de pago", row.complemento_pago],
        ["Estatus SAT", row.estatus_sat or "—"],
    ]
    table = Table(data, colWidths=[4.4 * cm, 13.6 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#D0D5DD")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F4F7FB")),
            ]
        )
    )
    doc.build(
        [
            Paragraph("SAT Masivo — representación impresa", title),
            Paragraph(xml_path.name, label),
            Spacer(1, 10),
            table,
        ]
    )
    return pdf_path


def folder_to_pdf(folder: str | Path, dest: str | Path) -> list[Path]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for xml in sorted(Path(folder).rglob("*.xml")):
        try:
            written.append(cfdi_to_pdf(xml, dest / (xml.stem + ".pdf")))
        except Exception:
            continue
    return written
