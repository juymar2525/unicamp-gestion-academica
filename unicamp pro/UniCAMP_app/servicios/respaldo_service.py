"""Creación y restauración de respaldos completos de la base académica."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, insert, select

from modelos.entidades import Base

BACKUP_FORMAT = "unicamp-database-backup"
BACKUP_VERSION = 1


class RespaldoError(ValueError):
    """El archivo de respaldo no corresponde al formato o esquema esperado."""


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return {
            "__unicamp_type__": type(value).__name__,
            "value": value.isoformat(),
        }
    if isinstance(value, bytes):
        return {
            "__unicamp_type__": "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    return value


def _deserialize_value(value: Any, column_type: Any) -> Any:
    if not isinstance(value, dict) or "__unicamp_type__" not in value:
        return value
    type_name = value["__unicamp_type__"]
    encoded = value.get("value")
    if not isinstance(encoded, str):
        raise RespaldoError("Un valor del respaldo tiene un formato inválido.")
    expected_type = {
        "datetime": datetime,
        "date": date,
        "time": time,
        "bytes": bytes,
    }.get(type_name)
    if expected_type is None or column_type.python_type is not expected_type:
        raise RespaldoError("Un valor del respaldo no coincide con su columna.")
    if type_name == "datetime":
        return datetime.fromisoformat(encoded)
    if type_name == "date":
        return date.fromisoformat(encoded)
    if type_name == "time":
        return time.fromisoformat(encoded)
    if type_name == "bytes":
        return base64.b64decode(encoded, validate=True)
    raise RespaldoError(f"El respaldo contiene un tipo no admitido: {type_name}.")


def crear_respaldo(destination: str | Path, engine: Engine) -> dict[str, int]:
    """Exporta cada tabla administrada por la aplicación a un archivo JSON."""
    tables = list(Base.metadata.sorted_tables)
    serialized_tables: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    with engine.connect() as connection, connection.begin():
        for table in tables:
            rows = connection.execute(select(table)).mappings().all()
            serialized_tables[table.name] = [
                {
                    column.name: _serialize_value(row[column.name])
                    for column in table.columns
                }
                for row in rows
            ]
            counts[table.name] = len(rows)

    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "tables": serialized_tables,
    }
    Path(destination).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return counts


def restaurar_respaldo(source: str | Path, engine: Engine) -> dict[str, int]:
    """Reemplaza transaccionalmente todos los registros con el archivo indicado."""
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("format") != BACKUP_FORMAT
        or payload.get("version") != BACKUP_VERSION
        or not isinstance(payload.get("tables"), dict)
    ):
        raise RespaldoError(
            "El archivo no es un respaldo UniCamp compatible o está dañado."
        )

    tables = list(Base.metadata.sorted_tables)
    saved_tables = payload["tables"]
    expected_names = {table.name for table in tables}
    if set(saved_tables) != expected_names:
        raise RespaldoError(
            "El respaldo no contiene exactamente las tablas de esta versión "
            "de UniCamp."
        )

    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for table in tables:
        rows = saved_tables[table.name]
        if not isinstance(rows, list):
            raise RespaldoError(
                f"Los registros de la tabla {table.name} no tienen un formato válido."
            )
        columns = {column.name: column for column in table.columns}
        decoded_rows = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise RespaldoError(
                    f"Un registro de la tabla {table.name} está incompleto o es inválido."
                )
            decoded_rows.append(
                {
                    name: _deserialize_value(value, columns[name].type)
                    for name, value in row.items()
                }
            )
        rows_by_table[table.name] = decoded_rows
        counts[table.name] = len(decoded_rows)

    with engine.begin() as connection:
        for table in reversed(tables):
            connection.execute(table.delete())
        for table in tables:
            rows = rows_by_table[table.name]
            if rows:
                connection.execute(insert(table), rows)

    return counts
