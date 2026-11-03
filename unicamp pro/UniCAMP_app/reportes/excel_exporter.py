"""Exportación corporativa de la oferta académica a Excel."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

HEADERS = (
    "Asignatura",
    "Código",
    "Período",
    "Grupo",
    "Día",
    "Hora inicio",
    "Hora fin",
    "Edificio",
    "Aula",
    "Cupo máximo",
    "Inscritos",
    "Cupo disponible",
)


def exportar_oferta_academica(
    rows: list[dict[str, Any]],
    output_path: str | Path,
) -> Path:
    """Escribe la oferta y ocupación de grupos con formato institucional."""
    destination = Path(output_path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Oferta académica"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:L{max(1, len(rows) + 1)}"

    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(name="Calibri", bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", color="233653")
    thin_gray = Side(style="thin", color="D9E2F3")
    cell_border = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)

    try:
        for column, header in enumerate(HEADERS, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = cell_border

        for row_number, row in enumerate(rows, start=2):
            capacity = int(row["cupo_maximo"])
            enrolled = int(row["inscritos"])
            values = (
                row["asignatura"],
                row["codigo"],
                row["periodo"],
                row["grupo"],
                row["dia"],
                row["hora_inicio"],
                row["hora_fin"],
                row.get("edificio", ""),
                row.get("aula", ""),
                capacity,
                enrolled,
                max(0, capacity - enrolled),
            )
            for column, value in enumerate(values, start=1):
                cell = sheet.cell(row=row_number, column=column, value=value)
                cell.font = body_font
                cell.border = cell_border
                cell.alignment = Alignment(
                    horizontal="center" if column >= 4 else "left",
                    vertical="center",
                )

        for column_cells in sheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(
                max(max_length + 2, 12),
                40,
            )
        sheet.row_dimensions[1].height = 32

        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(destination)
        return destination
    except Exception:
        logger.exception("No se pudo generar el archivo Excel de oferta académica.")
        raise
    finally:
        workbook.close()
