"""Worker QThread reutilizable sin acceso a widgets desde run()."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ReportWorker(QThread):
    """Ejecuta una operación larga y entrega su resultado mediante señales."""

    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, operation: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation()
        except Exception:
            logger.exception("Falló la tarea ejecutada por el worker.")
            self.error_occurred.emit(
                "No se pudo completar la operación. Revisa los datos e inténtalo de nuevo."
            )
        else:
            self.result_ready.emit(result)
