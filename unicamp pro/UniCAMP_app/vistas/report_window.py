"""Ejemplo de vista con ciclo de vida seguro para un worker Qt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hilos.report_worker import ReportWorker
from reportes.excel_exporter import exportar_oferta_academica


class ReportWindow(QMainWindow):
    """Exporta ocupación; el proveedor debe abrir sus propios recursos fuera de la UI."""

    def __init__(
        self,
        offer_rows_provider: Callable[[], list[dict[str, Any]]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._offer_rows_provider = offer_rows_provider
        self._worker: ReportWorker | None = None
        self._last_result: Path | None = None
        self._last_error: str | None = None

        self.setWindowTitle("Reportes académicos")
        self.export_button = QPushButton("Exportar oferta académica a Excel")
        self.export_button.clicked.connect(self.export_offer)
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.addWidget(self.export_button)
        self.setCentralWidget(container)

    def export_offer(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar oferta académica",
            "oferta_academica.xlsx",
            "Libro de Excel (*.xlsx)",
        )
        if not filename:
            return

        destination = Path(filename)
        operation = lambda: exportar_oferta_academica(
            self._offer_rows_provider(),
            destination,
        )
        self._worker = ReportWorker(operation, self)
        self._worker.started.connect(self._on_task_started)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_task_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_task_started(self) -> None:
        self._last_result = None
        self._last_error = None
        self.export_button.setEnabled(False)
        self.export_button.setText("Generando reporte…")

    def _on_result_ready(self, result: object) -> None:
        if isinstance(result, Path):
            self._last_result = result

    def _on_error(self, message: str) -> None:
        self._last_error = message

    def _on_task_finished(self) -> None:
        self.export_button.setEnabled(True)
        self.export_button.setText("Exportar oferta académica a Excel")
        if self._last_error:
            QMessageBox.warning(self, "Error de exportación", self._last_error)
        elif self._last_result is not None:
            QMessageBox.information(
                self,
                "Reporte generado",
                f"El archivo se guardó correctamente en:\n{self._last_result}",
            )
        self._worker = None
