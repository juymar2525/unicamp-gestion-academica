"""Generación de comprobantes estáticos y expedientes PDF dinámicos."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)
INSTITUTIONAL_BLUE = colors.HexColor("#17365D")


def generar_comprobante_cita(
    datos: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Crea un comprobante de una página con lienzo de coordenadas fijas."""
    destination = Path(output_path)
    buffer = BytesIO()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        pdf.setStrokeColor(INSTITUTIONAL_BLUE)
        pdf.setLineWidth(1.5)
        pdf.rect(18 * mm, 18 * mm, width - 36 * mm, height - 36 * mm)

        pdf.setFillColor(INSTITUTIONAL_BLUE)
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawCentredString(width / 2, height - 38 * mm, "CITA DE RECEPCIÓN")
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(width / 2, height - 46 * mm, "Gestión Académica")

        y = height - 75 * mm
        fields = (
            ("Estudiante", datos["estudiante"]),
            ("Identificación", datos["identificacion"]),
            ("Fecha y hora", datos["fecha_hora"]),
            ("Ubicación", datos["ubicacion"]),
        )
        pdf.setFillColor(colors.black)
        for label, value in fields:
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(30 * mm, y, f"{label}:")
            pdf.setFont("Helvetica", 11)
            pdf.drawString(68 * mm, y, str(value))
            y -= 14 * mm

        reference = str(datos.get("codigo_validacion", "SIN-CODIGO"))
        pdf.setStrokeColor(colors.HexColor("#AAB7C4"))
        pdf.line(30 * mm, 38 * mm, width - 30 * mm, 38 * mm)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(width / 2, 29 * mm, f"Código de validación: {reference}")
        pdf.save()
        destination.write_bytes(buffer.getvalue())
        return destination
    except Exception:
        logger.exception("No se pudo generar el comprobante PDF.")
        raise
    finally:
        buffer.close()


def generar_hoja_expediente(
    datos: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Genera un expediente variable paginado con Flowables de ReportLab."""
    destination = Path(output_path)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InstitutionTitle",
        parent=styles["Title"],
        textColor=INSTITUTIONAL_BLUE,
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        textColor=INSTITUTIONAL_BLUE,
        alignment=TA_LEFT,
        spaceBefore=5 * mm,
    )
    body_style = styles["BodyText"]
    elements = [
        Paragraph("EXPEDIENTE ACADÉMICO", title_style),
        HRFlowable(width="100%", thickness=1, color=INSTITUTIONAL_BLUE),
        Spacer(1, 5 * mm),
        Paragraph(
            f"<b>Estudiante:</b> {escape(str(datos['estudiante']))}<br/>"
            f"<b>Identificación:</b> {escape(str(datos['identificacion']))}<br/>"
            f"<b>Tipo de ingreso:</b> {escape(str(datos['tipo_ingreso']))}<br/>"
            f"<b>Carrera:</b> {escape(str(datos['carrera']))}",
            body_style,
        ),
        Paragraph("Lista de cotejo documental", section_style),
    ]
    checklist = datos.get("documentos", [])
    checklist_rows = [["Documento", "Recibido", "Verificado"]]
    checklist_rows.extend(
        [
            str(item["nombre"]),
            "Sí" if item.get("recibido") else "No",
            "Sí" if item.get("verificado") else "No",
        ]
        for item in checklist
    )
    checklist_table = Table(checklist_rows, repeatRows=1, hAlign="LEFT")
    checklist_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INSTITUTIONAL_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EFF4FA")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.extend([checklist_table, Paragraph("Ubicación asignada", section_style)])
    location = datos.get("ubicacion", {})
    location_rows = [["Edificio", "Pabellón", "Aula", "Ventanilla"]]
    location_rows.append(
        [
            location.get("edificio", ""),
            location.get("pabellon", ""),
            location.get("aula", ""),
            location.get("ventanilla", ""),
        ]
    )
    location_table = Table(location_rows, repeatRows=1, hAlign="LEFT")
    location_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INSTITUTIONAL_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EFF4FA")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    elements.append(location_table)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = SimpleDocTemplate(
            str(destination),
            pagesize=letter,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
            title="Expediente académico",
        )
        document.build(elements)
        return destination
    except Exception:
        logger.exception("No se pudo generar la hoja dinámica de expediente PDF.")
        raise
