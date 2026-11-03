"""Punto de entrada de UniCamp Gestión Académica."""

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from config.database import check_database_connection, engine
from modelos.entidades import Base
from vistas.student_access import StudentLoginWindow

logger = logging.getLogger(__name__)


def ensure_group_teacher_schema() -> None:
    """Agrega el vínculo opcional con docentes a bases de datos anteriores."""
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("grupos")}
    if "docente_id" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE grupos ADD COLUMN docente_id INTEGER NULL")
            )

    indexes = inspect(engine).get_indexes("grupos")
    if not any(
        "docente_id" in (index.get("column_names") or [])
        for index in indexes
    ):
        with engine.begin() as connection:
            connection.execute(
                text("CREATE INDEX ix_grupos_docente_id ON grupos (docente_id)")
            )

    foreign_keys = inspect(engine).get_foreign_keys("grupos")
    if not any(
        "docente_id" in (key.get("constrained_columns") or [])
        for key in foreign_keys
    ):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE grupos "
                    "ADD CONSTRAINT fk_grupo_perfil_docente "
                    "FOREIGN KEY (docente_id) REFERENCES perfiles_docente (id) "
                    "ON DELETE SET NULL"
                )
            )


def main() -> int:
    """Inicializa Qt, comprueba MySQL y abre la ventana académica."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("UniCamp Gestión Académica")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))

    try:
        check_database_connection()
        Base.metadata.create_all(bind=engine)
        ensure_group_teacher_schema()
    except SQLAlchemyError:
        logger.exception("No se pudo preparar la base de datos.")
        QMessageBox.critical(
            None,
            "No se pudo conectar a MySQL",
            "Verifica que MySQL esté iniciado, que la base de datos exista y que "
            "las variables UNICAMP_DB_HOST, UNICAMP_DB_PORT, UNICAMP_DB_USER, "
            "UNICAMP_DB_PASSWORD y UNICAMP_DB_NAME sean correctas.\n\n"
            "La base de datos debe crearse antes de iniciar la aplicación.",
        )
        return 1

    window = StudentLoginWindow()
    window.show()
    exit_code = app.exec()
    engine.dispose()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
