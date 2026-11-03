"""Normalización de períodos académicos con o sin cero inicial."""

from __future__ import annotations

import re

PERIOD_PATTERN = re.compile(r"^(\d{4})-(\d{1,2})$")


def normalizar_periodo(periodo: str) -> str:
    """Normaliza, por ejemplo, 2026-01 y 2026-1 al mismo período."""
    value = periodo.strip()
    match = PERIOD_PATTERN.fullmatch(value)
    if match is None:
        return value
    year, term = match.groups()
    return f"{year}-{int(term)}"


def variantes_periodo(periodo: str) -> tuple[str, ...]:
    """Devuelve variantes compatibles con períodos ya guardados."""
    normalized = normalizar_periodo(periodo)
    match = PERIOD_PATTERN.fullmatch(normalized)
    if match is None:
        return (normalized,)
    year, term = match.groups()
    return normalized, f"{year}-{int(term):02d}"
