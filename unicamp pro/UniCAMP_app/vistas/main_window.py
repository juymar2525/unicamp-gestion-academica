"""Ventana principal de gestión académica integrada con las capas del proyecto."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QAbstractItemView,
    QInputDialog,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from config.database import engine, session_scope
from hilos.report_worker import ReportWorker
from modelos.entidades import (
    Asignatura,
    Carrera,
    DocumentoChecklist,
    Estudiante,
    Grupo,
    Matricula,
    MatriculaDetail,
    PerfilDocente,
)
from reportes.excel_exporter import exportar_oferta_academica
from reportes.pdf_generator import generar_comprobante_cita, generar_hoja_expediente
from servicios.autenticacion_service import (
    AutenticacionService,
    ErrorAutenticacion,
    validar_correo,
)
from servicios.matricula_service import MatriculaError, MatriculaService
from servicios.periodos import normalizar_periodo, variantes_periodo
from servicios.respaldo_service import crear_respaldo, restaurar_respaldo

logger = logging.getLogger(__name__)
DOCUMENT_TYPES = (
    "Título de Bachiller",
    "Certificado de Notas",
    "Cédula de Identidad",
    "Fotos Título",
)
PREDEFINED_CAREERS = (
    ("Ing. Sistemas", "ING-SIS"),
    ("Medicina", "MED"),
    ("Mecánica", "MEC"),
    ("Telemática", "TEL"),
    ("Psicología", "PSI"),
)

APP_STYLE = """
QMainWindow, QWidget {
    background: #f3f6fb; color: #172b4d;
    font-family: 'Segoe UI'; font-size: 18px;
}
QTabWidget::pane { border: 1px solid #dce5f0; background: #f3f6fb; }
QTabBar::tab {
    background: #e6edf7; color: #234365; padding: 11px 18px;
    margin: 3px; border-radius: 5px;
}
QTabBar::tab:selected { background: #347bd3; color: white; font-weight: 700; }
QGroupBox {
    background: white; border: 1px solid #dce5f0; border-radius: 9px;
    margin-top: 12px; padding: 16px; font-weight: 700;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QSpinBox, QTimeEdit {
    background: white; border: 1px solid #ccd8e7; border-radius: 5px;
    padding: 7px; min-height: 22px;
}
QPushButton {
    background: #347bd3; color: white; border: none; border-radius: 5px;
    padding: 9px 14px; font-weight: 600;
}
QPushButton:hover { background: #2466b6; }
QPushButton:disabled { background: #9aaabd; }
QTableWidget {
    background: white; border: 1px solid #dce5f0;
    gridline-color: #e8edf5; alternate-background-color: #f7f9fc;
}
QHeaderView::section {
    background: #17365d; color: white; padding: 9px; border: none;
    font-weight: 700;
}
QLabel#Title { color: #172e53; font-size: 25px; font-weight: 800; }
QLabel#Metric { color: #2468b5; font-size: 24px; font-weight: 800; }
QLabel#Hint { color: #637590; }
"""


class MainWindow(QMainWindow):
    """Interfaz principal para los flujos académicos del sistema."""

    def __init__(self) -> None:
        super().__init__()
        self._worker: ReportWorker | None = None
        self._worker_result: object | None = None
        self._worker_error: str | None = None
        self._editing_group_id: int | None = None
        self.setWindowTitle("UniCamp | Gestión Académica")
        self.resize(1360, 850)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        title = QLabel("Gestión Académica")
        title.setObjectName("Title")
        subtitle = QLabel(
            "Matrículas, oferta horaria, recepción documental y reportes institucionales"
        )
        subtitle.setObjectName("Hint")
        backup_actions = QHBoxLayout()
        backup_actions.addStretch()
        backup_button = QPushButton("Crear respaldo de datos")
        backup_button.clicked.connect(self._create_database_backup)
        backup_actions.addWidget(backup_button)
        restore_button = QPushButton("Restaurar respaldo")
        restore_button.clicked.connect(self._restore_database_backup)
        backup_actions.addWidget(restore_button)
        layout.addLayout(backup_actions)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._dashboard_page(), "Resumen")
        self.catalogs_page = self._catalogs_page()
        self.tabs.addTab(self.catalogs_page, "Catálogos")
        self.tabs.addTab(self._students_page(), "Estudiantes")
        self.tabs.addTab(self._access_accounts_page(), "Accesos")
        self.tabs.addTab(self._offer_page(), "Oferta académica")
        self.tabs.addTab(self._enrollment_page(), "Matrícula")
        self.tabs.addTab(self._documents_page(), "Documentos")
        self.tabs.addTab(self._reports_page(), "Reportes")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Listo")

    def _create_database_backup(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar respaldo de UniCamp",
            "UniCamp-Respaldo.json",
            "Respaldo UniCamp (*.json)",
        )
        if not filename:
            return
        try:
            counts = crear_respaldo(filename, engine)
        except (OSError, SQLAlchemyError, ValueError) as exc:
            logger.exception("No se pudo crear el respaldo de la base de datos.")
            QMessageBox.critical(
                self,
                "Error al crear el respaldo",
                f"No fue posible guardar todos los datos.\n\n{exc}",
            )
            return
        total = sum(counts.values())
        QMessageBox.information(
            self,
            "Respaldo creado",
            f"Se guardaron {total} registros de {len(counts)} tablas en:\n{filename}\n\n"
            "Copia este archivo al otro dispositivo y usa «Restaurar respaldo».",
        )

    def _restore_database_backup(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar respaldo de UniCamp",
            "",
            "Respaldo UniCamp (*.json)",
        )
        if not filename:
            return
        confirmation = QMessageBox.question(
            self,
            "Confirmar restauración",
            "Esta acción reemplazará todos los registros actuales con los del "
            "respaldo seleccionado. Se recomienda crear antes un respaldo de "
            "los datos actuales.\n\n¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            counts = restaurar_respaldo(filename, engine)
        except (OSError, SQLAlchemyError, ValueError) as exc:
            logger.exception("No se pudo restaurar el respaldo de la base de datos.")
            QMessageBox.critical(
                self,
                "Error al restaurar el respaldo",
                f"No se modificaron los datos porque la restauración no se completó.\n\n"
                f"{exc}",
            )
            return
        self.refresh_all()
        QMessageBox.information(
            self,
            "Respaldo restaurado",
            f"Se restauraron {sum(counts.values())} registros "
            f"de {len(counts)} tablas.",
        )

    @staticmethod
    def _table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    @staticmethod
    def _set_table_rows(
        table: QTableWidget,
        rows: list[tuple[Any, ...]],
    ) -> None:
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if column_index == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_index, column_index, item)

    def _dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        cards = QGridLayout()
        self.metric_labels: dict[str, QLabel] = {}
        for index, (key, label) in enumerate(
            (
                ("estudiantes", "Estudiantes"),
                ("carreras", "Carreras"),
                ("asignaturas", "Asignaturas"),
                ("grupos", "Grupos ofertados"),
                ("matriculas", "Matrículas"),
            )
        ):
            card = QGroupBox(label)
            card_layout = QVBoxLayout(card)
            value = QLabel("—")
            value.setObjectName("Metric")
            self.metric_labels[key] = value
            card_layout.addWidget(value)
            cards.addWidget(card, index // 3, index % 3)
        layout.addLayout(cards)

        information = QGroupBox("Flujo de trabajo")
        info_layout = QVBoxLayout(information)
        info = QLabel(
            "1. Registra carreras, asignaturas y sus grupos en Catálogos.\n"
            "2. Registra estudiantes y su tipo de ingreso.\n"
            "3. Selecciona grupos y procesa la matrícula; el sistema valida "
            "créditos, prerrequisitos, cupos y choques de horario.\n"
            "4. Controla documentos y genera comprobantes o reportes."
        )
        info.setWordWrap(True)
        info_layout.addWidget(info)
        layout.addWidget(information)
        layout.addStretch()
        return page

    def _catalogs_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self.catalog_tabs = QTabWidget()
        root.addWidget(self.catalog_tabs)

        careers_page = QWidget()
        careers_layout = QVBoxLayout(careers_page)
        career_box = QGroupBox("Registrar carrera")
        career_form = QHBoxLayout(career_box)
        self.career_choice = QComboBox()
        self.career_choice.addItem("Selecciona una carrera", None)
        for name, code in PREDEFINED_CAREERS:
            self.career_choice.addItem(f"{name} ({code})", (name, code))
        add_career = QPushButton("Registrar carrera")
        add_career.clicked.connect(self._add_career)
        career_form.addWidget(QLabel("Carrera"))
        career_form.addWidget(self.career_choice, 1)
        career_form.addWidget(add_career)
        careers_layout.addWidget(career_box)
        self.careers_table = self._table(["ID", "Código", "Carrera"])
        careers_layout.addWidget(self.careers_table, 1)
        delete_career = QPushButton("Eliminar carrera seleccionada")
        delete_career.clicked.connect(self._delete_selected_career)
        careers_layout.addWidget(delete_career, alignment=Qt.AlignmentFlag.AlignRight)
        self.catalog_tabs.addTab(careers_page, "Carreras")

        subjects_page = QWidget()
        subjects_layout = QVBoxLayout(subjects_page)
        subject_box = QGroupBox("Asignaturas y malla curricular")
        subject_form = QGridLayout(subject_box)
        self.subject_code = QLineEdit()
        self.subject_code.setPlaceholderText("Código")
        self.subject_name = QLineEdit()
        self.subject_name.setPlaceholderText("Nombre")
        self.subject_credits = QSpinBox()
        self.subject_credits.setRange(1, 60)
        self.subject_credits.setValue(3)
        self.subject_career = QComboBox()
        add_subject = QPushButton("Registrar asignatura")
        add_subject.clicked.connect(self._add_subject)
        subject_form.addWidget(QLabel("Código"), 0, 0)
        subject_form.addWidget(self.subject_code, 0, 1)
        subject_form.addWidget(QLabel("Nombre"), 0, 2)
        subject_form.addWidget(self.subject_name, 0, 3)
        subject_form.addWidget(QLabel("Créditos"), 1, 0)
        subject_form.addWidget(self.subject_credits, 1, 1)
        subject_form.addWidget(QLabel("Carrera"), 1, 2)
        subject_form.addWidget(self.subject_career, 1, 3)
        subject_form.addWidget(add_subject, 2, 3)
        subjects_layout.addWidget(subject_box)
        self.subjects_table = self._table(
            ["ID", "Código", "Asignatura", "Créditos", "Carreras"]
        )
        subjects_layout.addWidget(self.subjects_table, 1)
        delete_subject = QPushButton("Eliminar asignatura seleccionada")
        delete_subject.clicked.connect(self._delete_selected_subject)
        subjects_layout.addWidget(
            delete_subject,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.catalog_tabs.addTab(subjects_page, "Asignaturas")

        groups_page = QWidget()
        groups_layout = QVBoxLayout(groups_page)
        group_box = QGroupBox("Crear grupo de oferta")
        group_form = QGridLayout(group_box)
        self.group_subject = QComboBox()
        self.group_subject.currentIndexChanged.connect(
            self._load_eligible_group_teachers
        )
        self.group_teacher = QComboBox()
        self.group_period = QLineEdit()
        self.group_period.setPlaceholderText("Ej. 2026-1")
        self.group_section = QLineEdit()
        self.group_section.setPlaceholderText("Sección")
        self.group_day = QComboBox()
        self.group_day.addItems(
            ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        )
        self.group_start = QTimeEdit()
        self.group_start.setDisplayFormat("HH:mm")
        self.group_start.setTime(QTime(8, 0))
        self.group_end = QTimeEdit()
        self.group_end.setDisplayFormat("HH:mm")
        self.group_end.setTime(QTime(10, 0))
        self.group_capacity = QSpinBox()
        self.group_capacity.setRange(1, 500)
        self.group_capacity.setValue(30)
        self.group_building = QLineEdit()
        self.group_building.setPlaceholderText("Edificio")
        self.group_pavilion = QLineEdit()
        self.group_pavilion.setPlaceholderText("Pabellón")
        self.group_room = QLineEdit()
        self.group_room.setPlaceholderText("Aula")
        self.group_counter = QLineEdit()
        self.group_counter.setPlaceholderText("Ventanilla")
        add_group = QPushButton("Crear grupo")
        add_group.clicked.connect(self._add_group)
        update_group = QPushButton("Guardar cambios del grupo")
        update_group.clicked.connect(self._update_group)
        update_group.setEnabled(False)
        self.update_group_button = update_group
        fields = [
            ("Asignatura", self.group_subject),
            ("Docente", self.group_teacher),
            ("Período", self.group_period),
            ("Sección", self.group_section),
            ("Día", self.group_day),
            ("Inicio", self.group_start),
            ("Fin", self.group_end),
            ("Cupo", self.group_capacity),
            ("Edificio", self.group_building),
            ("Pabellón", self.group_pavilion),
            ("Aula", self.group_room),
            ("Ventanilla", self.group_counter),
        ]
        for index, (label, widget) in enumerate(fields):
            row, column = divmod(index, 3)
            group_form.addWidget(QLabel(label), row * 2, column)
            group_form.addWidget(widget, row * 2 + 1, column)
        last_row = ((len(fields) - 1) // 3) * 2 + 2
        group_form.addWidget(add_group, last_row, 2)
        group_form.addWidget(update_group, last_row, 1)
        groups_layout.addWidget(group_box)

        hint = QLabel(
            "Los grupos creados aparecerán en Oferta académica y estarán "
            "disponibles para matrícula según su período."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        groups_layout.addWidget(hint)
        groups_layout.addStretch()
        self.catalog_tabs.addTab(groups_page, "Grupos")
        return page

    def _students_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form_box = QGroupBox("Registrar estudiante")
        form = QHBoxLayout(form_box)
        self.student_first_name = QLineEdit()
        self.student_first_name.setPlaceholderText("Nombre")
        self.student_last_name = QLineEdit()
        self.student_last_name.setPlaceholderText("Apellido")
        self.student_email = QLineEdit()
        self.student_email.setPlaceholderText(
            "correo@gmail.com o correo@outlook.com"
        )
        self.student_email.textEdited.connect(
            lambda value: self._normalize_email_input(self.student_email, value)
        )
        self.student_type = QComboBox()
        self.student_type.addItem("Nuevo ingreso", "nuevo_ingreso")
        self.student_type.addItem("Reingreso", "reingreso")
        self.student_career = QComboBox()
        add_student = QPushButton("Registrar")
        add_student.clicked.connect(self._add_student)
        form.addWidget(self.student_first_name, 1)
        form.addWidget(self.student_last_name, 1)
        form.addWidget(self.student_email, 2)
        form.addWidget(self.student_type, 1)
        form.addWidget(self.student_career, 2)
        form.addWidget(add_student)
        layout.addWidget(form_box)

        self.students_table = self._table(
            ["ID", "Nombre", "Apellido", "Correo", "Ingreso", "Carrera", "Estado"]
        )
        layout.addWidget(self.students_table, 1)
        delete_student = QPushButton("Desactivar estudiante seleccionado")
        delete_student.clicked.connect(self._deactivate_selected_student)
        layout.addWidget(delete_student, alignment=Qt.AlignmentFlag.AlignRight)
        enable_student = QPushButton("Habilitar acceso al estudiante seleccionado")
        enable_student.clicked.connect(self._enable_student_access)
        layout.addWidget(enable_student, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _access_accounts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        student_box = QGroupBox("Cuentas de estudiantes")
        student_layout = QVBoxLayout(student_box)
        self.student_accounts_table = self._table(
            ["ID", "Estudiante", "Carnet", "Correo", "Estado"]
        )
        student_layout.addWidget(self.student_accounts_table, 1)
        reset_student = QPushButton("Cambiar contraseña del estudiante seleccionado")
        reset_student.clicked.connect(self._reset_student_password)
        student_layout.addWidget(
            reset_student,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(student_box, 1)

        teacher_box = QGroupBox("Cuentas de docentes")
        teacher_layout = QVBoxLayout(teacher_box)
        self.teacher_accounts_table = self._table(
            ["ID", "Docente", "Correo", "Carrera", "Estado"]
        )
        teacher_layout.addWidget(self.teacher_accounts_table, 1)
        reset_teacher = QPushButton("Cambiar contraseña del docente seleccionado")
        reset_teacher.clicked.connect(self._reset_teacher_password)
        teacher_layout.addWidget(
            reset_teacher,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(teacher_box, 1)
        return page

    def _offer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QHBoxLayout()
        refresh = QPushButton("Actualizar oferta")
        refresh.clicked.connect(self.load_offer)
        edit_group = QPushButton("Editar grupo seleccionado")
        edit_group.clicked.connect(self._load_selected_group_for_edit)
        delete_group = QPushButton("Eliminar grupo seleccionado")
        delete_group.clicked.connect(self._delete_selected_group)
        actions.addWidget(QLabel("Oferta y ocupación actual de grupos"))
        actions.addStretch()
        actions.addWidget(edit_group)
        actions.addWidget(delete_group)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self.offer_table = self._table(
            [
                "ID",
                "Asignatura",
                "Docente",
                "Código",
                "Período",
                "Grupo",
                "Día",
                "Horario",
                "Ubicación",
                "Inscritos / cupo",
                "Disponibles",
            ]
        )
        layout.addWidget(self.offer_table, 1)
        return page

    def _enrollment_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QGroupBox("Solicitud de matrícula")
        form = QFormLayout(controls)
        self.enrollment_student = QComboBox()
        self.enrollment_period = QLineEdit()
        self.enrollment_period.setPlaceholderText("Ej. 2026-1")
        self.enrollment_period.textChanged.connect(self.load_enrollment_groups)
        self.enrollment_min_credits = QSpinBox()
        self.enrollment_min_credits.setRange(0, 60)
        self.enrollment_max_credits = QSpinBox()
        self.enrollment_max_credits.setRange(1, 60)
        self.enrollment_max_credits.setValue(30)
        form.addRow("Estudiante", self.enrollment_student)
        form.addRow("Período", self.enrollment_period)
        form.addRow("Créditos mínimos", self.enrollment_min_credits)
        form.addRow("Créditos máximos", self.enrollment_max_credits)
        layout.addWidget(controls)

        self.enrollment_groups = self._table(
            [
                "ID",
                "Asignatura",
                "Docente",
                "Grupo",
                "Día",
                "Horario",
                "Ubicación",
                "Cupos",
            ]
        )
        self.enrollment_groups.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self.enrollment_groups.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.enrollment_groups, 1)
        self.enrollment_groups_hint = QLabel(
            "Escribe un período para filtrar los grupos y seleccionar materias."
        )
        self.enrollment_groups_hint.setObjectName("Hint")
        group_list_actions = QHBoxLayout()
        group_list_actions.addWidget(self.enrollment_groups_hint, 1)
        refresh_groups = QPushButton("Actualizar grupos")
        refresh_groups.clicked.connect(self.load_enrollment_groups)
        group_list_actions.addWidget(refresh_groups)
        layout.addLayout(group_list_actions)
        submit = QPushButton("Validar y guardar matrícula")
        submit.clicked.connect(self._submit_enrollment)
        layout.addWidget(submit, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _documents_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.document_student = QComboBox()
        self.document_student.currentIndexChanged.connect(self.load_checklist)
        row.addWidget(QLabel("Estudiante"))
        row.addWidget(self.document_student, 1)
        layout.addLayout(row)
        hint = QLabel("Marca los documentos recibidos y verificados.")
        hint.setObjectName("Hint")
        layout.addWidget(hint)
        self.documents_table = QTableWidget(0, 3)
        self.documents_table.setHorizontalHeaderLabels(
            ["Documento", "Recibido", "Verificado"]
        )
        self.documents_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.documents_table, 1)
        save = QPushButton("Guardar checklist")
        save.clicked.connect(self.save_checklist)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _reports_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Los archivos se generan en un hilo de trabajo. Las consultas y "
            "la exportación no bloquean la interfaz."
        )
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        export_excel = QPushButton("Exportar oferta académica a Excel")
        export_excel.clicked.connect(self.export_excel)
        layout.addWidget(export_excel)
        self.report_buttons = [export_excel]

        self.report_student = QComboBox()
        layout.addWidget(self.report_student)
        pdf_actions = QHBoxLayout()
        appointment = QPushButton("Generar comprobante de cita PDF")
        appointment.clicked.connect(self.export_appointment_pdf)
        dossier = QPushButton("Generar expediente PDF")
        dossier.clicked.connect(self.export_dossier_pdf)
        self.report_buttons.extend([appointment, dossier])
        pdf_actions.addWidget(appointment)
        pdf_actions.addWidget(dossier)
        layout.addLayout(pdf_actions)

        self.report_status = QLabel("Sin tareas en curso")
        self.report_status.setObjectName("Hint")
        layout.addWidget(self.report_status)
        layout.addStretch()
        return page

    def refresh_all(self) -> None:
        try:
            with session_scope() as db:
                self.metric_labels["estudiantes"].setText(
                    str(db.scalar(select(func.count(Estudiante.id))) or 0)
                )
                self.metric_labels["carreras"].setText(
                    str(db.scalar(select(func.count(Carrera.id))) or 0)
                )
                self.metric_labels["asignaturas"].setText(
                    str(db.scalar(select(func.count(Asignatura.id))) or 0)
                )
                self.metric_labels["grupos"].setText(
                    str(db.scalar(select(func.count(Grupo.id))) or 0)
                )
                self.metric_labels["matriculas"].setText(
                    str(db.scalar(select(func.count(Matricula.id))) or 0)
                )
            self.load_catalog_combos()
            self.load_catalog_tables()
            self.load_students()
            self.load_offer()
            self.load_enrollment_groups()
            self.load_checklist()
        except SQLAlchemyError as exc:
            logger.exception("No se pudieron cargar los datos de la aplicación.")
            QMessageBox.critical(
                self,
                "Error al cargar",
                f"No fue posible cargar los datos académicos.\n\n{exc}",
            )

    def load_catalog_combos(self) -> None:
        with session_scope() as db:
            careers = list(db.scalars(select(Carrera).order_by(Carrera.nombre)))
            subjects = list(
                db.scalars(
                    select(Asignatura)
                    .options(selectinload(Asignatura.carreras))
                    .order_by(Asignatura.nombre)
                )
            )
        self._replace_combo(
            self.subject_career,
            [(career.id, f"{career.codigo} - {career.nombre}") for career in careers],
        )
        self._replace_combo(
            self.student_career,
            [(career.id, f"{career.codigo} - {career.nombre}") for career in careers],
        )
        self._replace_combo(
            self.group_subject,
            [
                (
                    subject.id,
                    f"{subject.codigo} - {subject.nombre} ({subject.creditos} cr.)",
                )
                for subject in subjects
            ],
        )
        self._load_eligible_group_teachers()

    def _load_eligible_group_teachers(self, *_args: object) -> None:
        selected_teacher_id = self.group_teacher.currentData()
        subject_id = self.group_subject.currentData()
        try:
            with session_scope() as db:
                career_ids = (
                    list(
                        db.scalars(
                            select(Carrera.id)
                            .join(Carrera.asignaturas)
                            .where(Asignatura.id == subject_id)
                        )
                    )
                    if subject_id is not None
                    else []
                )
                teachers = (
                    list(
                        db.scalars(
                            select(PerfilDocente)
                            .options(selectinload(PerfilDocente.carrera))
                            .where(
                                PerfilDocente.activo.is_(True),
                                PerfilDocente.carrera_id.in_(career_ids),
                            )
                            .order_by(PerfilDocente.apellido, PerfilDocente.nombre)
                        )
                    )
                    if career_ids
                    else []
                )
            self.group_teacher.clear()
            self.group_teacher.addItem("Sin docente asignado", None)
            for teacher in teachers:
                self.group_teacher.addItem(
                    f"{teacher.apellido}, {teacher.nombre} — {teacher.carrera.nombre}",
                    teacher.id,
                )
            restored_index = self.group_teacher.findData(selected_teacher_id)
            if restored_index >= 0:
                self.group_teacher.setCurrentIndex(restored_index)
        except SQLAlchemyError as exc:
            self._show_error("No se pudieron cargar los docentes de la asignatura.", exc)

    def load_catalog_tables(self) -> None:
        with session_scope() as db:
            careers = list(db.scalars(select(Carrera).order_by(Carrera.nombre)))
            subjects = list(
                db.scalars(
                    select(Asignatura)
                    .options(
                        selectinload(Asignatura.carreras),
                        selectinload(Asignatura.grupos),
                    )
                    .order_by(Asignatura.nombre)
                )
            )

        self.careers_table.setRowCount(len(careers))
        for row, career in enumerate(careers):
            values = (career.id, career.codigo, career.nombre)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, career.id)
                self.careers_table.setItem(row, column, item)

        self.subjects_table.setRowCount(len(subjects))
        for row, subject in enumerate(subjects):
            career_names = ", ".join(career.nombre for career in subject.carreras)
            values = (
                subject.id,
                subject.codigo,
                subject.nombre,
                subject.creditos,
                career_names,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, subject.id)
                self.subjects_table.setItem(row, column, item)

    @staticmethod
    def _replace_combo(combo: QComboBox, items: list[tuple[int, str]]) -> None:
        current = combo.currentData()
        combo.clear()
        for item_id, label in items:
            combo.addItem(label, item_id)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)

    def load_students(self) -> None:
        with session_scope() as db:
            records = db.execute(
                select(Estudiante, Carrera.nombre)
                .join(Estudiante.carrera)
                .order_by(Estudiante.apellido, Estudiante.nombre)
            ).all()
        self._set_table_rows(
            self.students_table,
            [
                (
                    student.id,
                    student.nombre,
                    student.apellido,
                    student.correo,
                    "Nuevo ingreso"
                    if student.tipo_ingreso == "nuevo_ingreso"
                    else "Reingreso",
                    career_name,
                    "Activo" if student.activo else "Inactivo",
                )
                for student, career_name in records
            ],
        )
        student_items = [
            (
                student.id,
                f"{student.apellido}, {student.nombre} — {career_name}",
            )
            for student, career_name in records
            if student.activo
        ]
        self._replace_combo(self.enrollment_student, student_items)
        self._replace_combo(self.document_student, student_items)
        self._replace_combo(self.report_student, student_items)

    def load_access_accounts(self) -> None:
        with session_scope() as db:
            students = list(
                db.scalars(
                    select(Estudiante)
                    .options(selectinload(Estudiante.cuenta))
                    .where(Estudiante.cuenta.has())
                    .order_by(Estudiante.apellido, Estudiante.nombre)
                )
            )
            teachers = list(
                db.scalars(
                    select(PerfilDocente)
                    .options(
                        selectinload(PerfilDocente.cuenta),
                        selectinload(PerfilDocente.carrera),
                    )
                    .where(PerfilDocente.cuenta.has())
                    .order_by(PerfilDocente.apellido, PerfilDocente.nombre)
                )
            )

        self._set_table_rows(
            self.student_accounts_table,
            [
                (
                    student.id,
                    f"{student.apellido}, {student.nombre}",
                    student.cuenta.carnet,
                    student.correo,
                    "Activo" if student.activo else "Inactivo",
                )
                for student in students
                if student.cuenta is not None
            ],
        )
        self._set_table_rows(
            self.teacher_accounts_table,
            [
                (
                    teacher.id,
                    f"{teacher.apellido}, {teacher.nombre}",
                    teacher.correo,
                    teacher.carrera.nombre,
                    "Activo" if teacher.activo else "Inactivo",
                )
                for teacher in teachers
                if teacher.cuenta is not None
            ],
        )

    def load_offer(self) -> None:
        try:
            with session_scope() as db:
                records = db.execute(
                    select(Grupo, Asignatura)
                    .join(Grupo.asignatura)
                    .options(selectinload(Grupo.docente))
                    .order_by(Grupo.periodo, Grupo.dia, Grupo.hora_inicio)
                ).all()
                counts = self._enrollment_counts(
                    db,
                    [group.id for group, _ in records],
                )
            rows = []
            for group, subject in records:
                enrolled = counts.get(group.id, 0)
                rows.append(
                    (
                        group.id,
                        subject.nombre,
                        (
                            f"{group.docente.nombre} {group.docente.apellido}"
                            if group.docente
                            else "Sin asignar"
                        ),
                        subject.codigo,
                        group.periodo,
                        group.seccion,
                        group.dia,
                        f"{group.hora_inicio:%H:%M} - {group.hora_fin:%H:%M}",
                        self._location(group),
                        f"{enrolled} / {group.cupo_maximo}",
                        max(0, group.cupo_maximo - enrolled),
                    )
                )
            self._set_table_rows(self.offer_table, rows)
        except SQLAlchemyError as exc:
            self._show_error("No se pudo actualizar la oferta académica.", exc)

    def load_enrollment_groups(self) -> None:
        period = self.enrollment_period.text().strip()
        statement = (
            select(Grupo, Asignatura)
            .join(Grupo.asignatura)
            .options(selectinload(Grupo.docente))
            .order_by(Grupo.periodo, Grupo.dia, Grupo.hora_inicio)
        )
        if period:
            statement = statement.where(
                Grupo.periodo.in_(variantes_periodo(period))
            )
        try:
            with session_scope() as db:
                records = db.execute(statement).all()
                counts = self._enrollment_counts(
                    db,
                    [group.id for group, _ in records],
                )
            self.enrollment_groups.clearSelection()
            self.enrollment_groups.setRowCount(0)
            for row_number, (group, subject) in enumerate(records):
                self.enrollment_groups.insertRow(row_number)
                values = (
                    group.id,
                    subject.nombre,
                    (
                        f"{group.docente.nombre} {group.docente.apellido}"
                        if group.docente
                        else "Sin asignar"
                    ),
                    group.seccion,
                    group.dia,
                    f"{group.hora_inicio:%H:%M} - {group.hora_fin:%H:%M}",
                    self._location(group),
                    f"{counts.get(group.id, 0)} / {group.cupo_maximo}",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, group.periodo)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.enrollment_groups.setItem(row_number, column, item)
            self.enrollment_groups_hint.setText(
                f"{len(records)} grupo(s) disponible(s) para el período «{period}»."
                if period and records
                else (
                    f"No hay grupos para el período «{period}»."
                    if period
                    else "Escribe un período para filtrar los grupos y seleccionar materias."
                )
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudieron actualizar los grupos de matrícula.", exc)

    @staticmethod
    def _enrollment_counts(db, group_ids: list[int]) -> dict[int, int]:
        if not group_ids:
            return {}
        statement = (
            select(MatriculaDetail.grupo_id, func.count(MatriculaDetail.id))
            .join(MatriculaDetail.matricula)
            .where(
                MatriculaDetail.grupo_id.in_(group_ids),
                Matricula.estado != "cancelada",
                MatriculaDetail.estado == "inscrita",
            )
            .group_by(MatriculaDetail.grupo_id)
        )
        return {group_id: count for group_id, count in db.execute(statement)}

    @staticmethod
    def _location(group: Grupo) -> str:
        parts = [
            part
            for part in (group.edificio, group.pabellon, group.aula, group.ventanilla)
            if part
        ]
        return ", ".join(parts) or "Sin ubicación"

    def _add_career(self) -> None:
        selection = self.career_choice.currentData()
        if not selection:
            self._notify("Validación", "Selecciona una carrera de la lista.")
            return
        name, code = selection
        try:
            with session_scope() as db:
                db.add(Carrera(nombre=name, codigo=code))
            self.career_choice.setCurrentIndex(0)
            self.refresh_all()
            self._notify("Carrera registrada", f"{name} ({code}) se agregó al catálogo.")
        except IntegrityError:
            self._notify("Dato duplicado", "Ese código o nombre de carrera ya existe.")
        except SQLAlchemyError as exc:
            self._show_error("No se pudo registrar la carrera.", exc)

    def _add_subject(self) -> None:
        code = self.subject_code.text().strip()
        name = self.subject_name.text().strip()
        career_id = self.subject_career.currentData()
        if not code or not name or career_id is None:
            self._notify(
                "Validación",
                "Completa código, nombre y selecciona una carrera.",
            )
            return
        try:
            with session_scope() as db:
                career = db.get(Carrera, career_id)
                if career is None:
                    raise ValueError("La carrera seleccionada ya no existe.")
                subject = Asignatura(
                    codigo=code,
                    nombre=name,
                    creditos=self.subject_credits.value(),
                )
                subject.carreras.append(career)
                db.add(subject)
            self.subject_code.clear()
            self.subject_name.clear()
            self.refresh_all()
        except IntegrityError:
            self._notify("Dato duplicado", "Ese código de asignatura ya existe.")
        except (SQLAlchemyError, ValueError) as exc:
            self._show_error("No se pudo registrar la asignatura.", exc)

    def _add_group(self) -> None:
        subject_id = self.group_subject.currentData()
        period = self.group_period.text().strip()
        section = self.group_section.text().strip()
        start, end = self.group_start.time(), self.group_end.time()
        if subject_id is None or not period or not section:
            self._notify(
                "Validación",
                "Selecciona asignatura e indica período y sección.",
            )
            return
        if end <= start:
            self._notify("Horario inválido", "La hora final debe ser posterior a la inicial.")
            return
        try:
            with session_scope() as db:
                db.add(
                    Grupo(
                        asignatura_id=subject_id,
                        docente_id=self.group_teacher.currentData(),
                        periodo=period,
                        seccion=section,
                        dia=self.group_day.currentText(),
                        hora_inicio=start.toPython(),
                        hora_fin=end.toPython(),
                        cupo_maximo=self.group_capacity.value(),
                        edificio=self.group_building.text().strip(),
                        pabellon=self.group_pavilion.text().strip(),
                        aula=self.group_room.text().strip(),
                        ventanilla=self.group_counter.text().strip(),
                    )
                )
            self.refresh_all()
            self._notify("Grupo creado", "El grupo quedó disponible en la oferta.")
        except IntegrityError:
            self._notify(
                "Grupo duplicado",
                "Ya existe esa sección para la asignatura y período indicados.",
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudo crear el grupo.", exc)

    def _load_selected_group_for_edit(self) -> None:
        group_id = self._selected_record_id(self.offer_table)
        if group_id is None:
            self._notify(
                "Selecciona un grupo",
                "Selecciona el grupo que deseas editar en la oferta.",
            )
            return
        try:
            with session_scope() as db:
                group = db.get(Grupo, group_id)
                if group is None:
                    self._notify(
                        "Grupo no encontrado",
                        "Actualiza la oferta y selecciona el grupo nuevamente.",
                    )
                    return
                values = {
                    "asignatura_id": group.asignatura_id,
                    "docente_id": group.docente_id,
                    "periodo": group.periodo,
                    "seccion": group.seccion,
                    "dia": group.dia,
                    "hora_inicio": group.hora_inicio,
                    "hora_fin": group.hora_fin,
                    "cupo_maximo": group.cupo_maximo,
                    "edificio": group.edificio,
                    "pabellon": group.pabellon,
                    "aula": group.aula,
                    "ventanilla": group.ventanilla,
                }
            subject_index = self.group_subject.findData(values["asignatura_id"])
            if subject_index < 0:
                self._notify(
                    "Asignatura no disponible",
                    "La asignatura de este grupo no aparece en el catálogo.",
                )
                return

            self.group_subject.setCurrentIndex(subject_index)
            teacher_index = self.group_teacher.findData(values["docente_id"])
            self.group_teacher.setCurrentIndex(max(0, teacher_index))
            self.group_period.setText(values["periodo"])
            self.group_section.setText(values["seccion"])
            self.group_day.setCurrentText(values["dia"])
            self.group_start.setTime(QTime.fromString(
                values["hora_inicio"].strftime("%H:%M:%S"),
                "HH:mm:ss",
            ))
            self.group_end.setTime(QTime.fromString(
                values["hora_fin"].strftime("%H:%M:%S"),
                "HH:mm:ss",
            ))
            self.group_capacity.setValue(values["cupo_maximo"])
            self.group_building.setText(values["edificio"])
            self.group_pavilion.setText(values["pabellon"])
            self.group_room.setText(values["aula"])
            self.group_counter.setText(values["ventanilla"])

            self._editing_group_id = group_id
            self.update_group_button.setEnabled(True)
            self.catalog_tabs.setCurrentIndex(2)
            self.tabs.setCurrentWidget(self.catalogs_page)
            self._notify(
                "Editando grupo",
                f"Se cargaron los datos del grupo #{group_id}. "
                "Modifícalos y pulsa «Guardar cambios del grupo».",
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudo cargar el grupo para editarlo.", exc)

    def _update_group(self) -> None:
        if self._editing_group_id is None:
            self._notify(
                "Selecciona un grupo",
                "Primero carga un grupo desde «Editar grupo seleccionado».",
            )
            return
        subject_id = self.group_subject.currentData()
        period = self.group_period.text().strip()
        section = self.group_section.text().strip()
        start, end = self.group_start.time(), self.group_end.time()
        if subject_id is None or not period or not section:
            self._notify(
                "Validación",
                "Selecciona asignatura e indica período y sección.",
            )
            return
        if end <= start:
            self._notify(
                "Horario inválido",
                "La hora final debe ser posterior a la hora inicial.",
            )
            return
        if not self._confirm_delete(
            "Guardar cambios del grupo",
            "¿Aplicar los cambios al grupo seleccionado?",
        ):
            return
        try:
            with session_scope() as db:
                group = db.scalar(
                    select(Grupo)
                    .options(selectinload(Grupo.detalles_matricula))
                    .where(Grupo.id == self._editing_group_id)
                )
                if group is None:
                    self._notify(
                        "Grupo no encontrado",
                        "El grupo ya no existe. Actualiza la oferta.",
                    )
                    self._cancel_group_edit()
                    return
                if group.detalles_matricula:
                    self._notify(
                        "No se puede actualizar",
                        "Este grupo ya tiene estudiantes matriculados. "
                        "No se permiten cambios que alteren sus horarios académicos.",
                    )
                    return

                group.asignatura_id = subject_id
                group.docente_id = self.group_teacher.currentData()
                group.periodo = period
                group.seccion = section
                group.dia = self.group_day.currentText()
                group.hora_inicio = start.toPython()
                group.hora_fin = end.toPython()
                group.cupo_maximo = self.group_capacity.value()
                group.edificio = self.group_building.text().strip()
                group.pabellon = self.group_pavilion.text().strip()
                group.aula = self.group_room.text().strip()
                group.ventanilla = self.group_counter.text().strip()
            self._cancel_group_edit()
            self.refresh_all()
            self._notify("Grupo actualizado", "Los cambios se guardaron correctamente.")
        except IntegrityError:
            self._notify(
                "Grupo duplicado",
                "Ya existe esa sección para la asignatura y período indicados.",
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudo actualizar el grupo.", exc)

    def _cancel_group_edit(self) -> None:
        self._editing_group_id = None
        self.update_group_button.setEnabled(False)

    @staticmethod
    def _selected_record_id(table: QTableWidget) -> int | None:
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        try:
            return int(value if value is not None else item.text())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_email_input(field: QLineEdit, value: str) -> None:
        normalized = value.lower()
        if normalized != value:
            cursor_position = field.cursorPosition()
            field.setText(normalized)
            field.setCursorPosition(min(cursor_position, len(normalized)))

    def _confirm_delete(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _delete_selected_career(self) -> None:
        career_id = self._selected_record_id(self.careers_table)
        if career_id is None:
            self._notify("Selecciona una carrera", "Selecciona la carrera que deseas eliminar.")
            return
        if not self._confirm_delete(
            "Eliminar carrera",
            "¿Eliminar la carrera y TODOS sus datos asociados? Se borrarán sus "
            "estudiantes, cuentas de acceso, documentos, matrículas, asignaturas "
            "exclusivas, grupos e inscripciones. Esta acción es irreversible.",
        ):
            return
        try:
            with session_scope() as db:
                career = db.scalar(
                    select(Carrera)
                    .options(
                        selectinload(Carrera.estudiantes)
                        .selectinload(Estudiante.matriculas)
                        .selectinload(Matricula.detalles),
                        selectinload(Carrera.estudiantes).selectinload(
                            Estudiante.documentos
                        ),
                        selectinload(Carrera.estudiantes).selectinload(
                            Estudiante.cuenta
                        ),
                        selectinload(Carrera.asignaturas)
                        .selectinload(Asignatura.carreras),
                        selectinload(Carrera.asignaturas)
                        .selectinload(Asignatura.grupos)
                        .selectinload(Grupo.detalles_matricula),
                        selectinload(Carrera.asignaturas)
                        .selectinload(Asignatura.prerrequisitos),
                        selectinload(Carrera.asignaturas)
                        .selectinload(Asignatura.requerida_por),
                    )
                    .where(Carrera.id == career_id)
                )
                if career is None:
                    self._notify("Carrera no encontrada", "Actualiza la lista e inténtalo de nuevo.")
                    return

                for student in list(career.estudiantes):
                    db.delete(student)

                for subject in list(career.asignaturas):
                    other_careers = [
                        associated
                        for associated in subject.carreras
                        if associated.id != career.id
                    ]
                    subject.carreras.remove(career)
                    if other_careers:
                        continue

                    for prerequisite in list(subject.prerrequisitos):
                        prerequisite.requerida_por.remove(subject)
                    for dependent in list(subject.requerida_por):
                        dependent.prerrequisitos.remove(subject)
                    for group in list(subject.grupos):
                        db.delete(group)
                    db.delete(subject)

                db.delete(career)
            self.refresh_all()
            self._notify(
                "Carrera eliminada",
                "La carrera y sus datos exclusivos se eliminaron correctamente. "
                "Las asignaturas compartidas con otras carreras se conservaron.",
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudo eliminar la carrera.", exc)

    def _delete_selected_subject(self) -> None:
        subject_id = self._selected_record_id(self.subjects_table)
        if subject_id is None:
            self._notify(
                "Selecciona una asignatura",
                "Selecciona la asignatura que deseas eliminar.",
            )
            return
        if not self._confirm_delete(
            "Eliminar asignatura",
            "¿Eliminar la asignatura seleccionada? Esta acción no se puede deshacer.",
        ):
            return
        try:
            with session_scope() as db:
                subject = db.scalar(
                    select(Asignatura)
                    .options(
                        selectinload(Asignatura.grupos),
                        selectinload(Asignatura.prerrequisitos),
                        selectinload(Asignatura.requerida_por),
                    )
                    .where(Asignatura.id == subject_id)
                )
                if subject is None:
                    self._notify(
                        "Asignatura no encontrada",
                        "Actualiza la lista e inténtalo de nuevo.",
                    )
                    return
                if subject.grupos or subject.prerrequisitos or subject.requerida_por:
                    self._notify(
                        "No se puede eliminar",
                        "La asignatura tiene grupos ofertados o relaciones de "
                        "prerrequisito. Elimina esos vínculos primero.",
                    )
                    return
                db.delete(subject)
            self.refresh_all()
            self._notify("Asignatura eliminada", "La asignatura se eliminó correctamente.")
        except SQLAlchemyError as exc:
            self._show_error("No se pudo eliminar la asignatura.", exc)

    def _delete_selected_group(self) -> None:
        group_id = self._selected_record_id(self.offer_table)
        if group_id is None:
            self._notify("Selecciona un grupo", "Selecciona el grupo que deseas eliminar.")
            return
        if not self._confirm_delete(
            "Eliminar grupo",
            "¿Eliminar el grupo seleccionado? Esta acción no se puede deshacer.",
        ):
            return
        try:
            with session_scope() as db:
                group = db.scalar(
                    select(Grupo)
                    .options(selectinload(Grupo.detalles_matricula))
                    .where(Grupo.id == group_id)
                )
                if group is None:
                    self._notify("Grupo no encontrado", "Actualiza la oferta e inténtalo de nuevo.")
                    return
                if group.detalles_matricula:
                    self._notify(
                        "No se puede eliminar",
                        "El grupo tiene estudiantes matriculados. Conserva el "
                        "historial académico y no elimines este grupo.",
                    )
                    return
                db.delete(group)
            self.refresh_all()
            self._notify("Grupo eliminado", "El grupo se eliminó correctamente.")
        except SQLAlchemyError as exc:
            self._show_error("No se pudo eliminar el grupo.", exc)

    def _deactivate_selected_student(self) -> None:
        student_id = self._selected_record_id(self.students_table)
        if student_id is None:
            self._notify(
                "Selecciona un estudiante",
                "Selecciona el estudiante al que deseas quitar acceso.",
            )
            return
        if not self._confirm_delete(
            "Desactivar estudiante",
            "Se desactivará su acceso al portal, pero se conservará su historial "
            "académico. ¿Deseas continuar?",
        ):
            return
        try:
            with session_scope() as db:
                student = db.get(Estudiante, student_id)
                if student is None:
                    self._notify(
                        "Estudiante no encontrado",
                        "Actualiza la lista e inténtalo de nuevo.",
                    )
                    return
                student.activo = False
            self.refresh_all()
            self._notify(
                "Estudiante desactivado",
                "Se quitó el acceso al portal y se conservó el historial académico.",
            )
        except SQLAlchemyError as exc:
            self._show_error("No se pudo desactivar el estudiante.", exc)

    def _enable_student_access(self) -> None:
        student_id = self._selected_record_id(self.students_table)
        if student_id is None:
            self._notify(
                "Selecciona un estudiante",
                "Selecciona el estudiante al que deseas habilitar el acceso.",
            )
            return

        carnet, accepted = QInputDialog.getText(
            self,
            "Habilitar acceso",
            "Carnet institucional (formato 25-04497-0):",
            QLineEdit.EchoMode.Normal,
        )
        if not accepted:
            return
        password, accepted = QInputDialog.getText(
            self,
            "Habilitar acceso",
            "Contraseña inicial (mínimo 6 caracteres, letras y números):",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        try:
            AutenticacionService().habilitar_acceso(
                student_id,
                carnet,
                password,
            )
            self._notify(
                "Acceso habilitado",
                "El estudiante ya puede entrar con el carnet y la contraseña inicial. "
                "Comunícale esas credenciales de forma privada.",
            )
        except ErrorAutenticacion as exc:
            self._notify("No se pudo habilitar el acceso", str(exc))
        except SQLAlchemyError as exc:
            self._show_error("No se pudo habilitar el acceso.", exc)

    def _request_new_password(self, role: str) -> str | None:
        password, accepted = QInputDialog.getText(
            self,
            f"Cambiar contraseña de {role}",
            "Nueva contraseña (mínimo 6 caracteres, letras y números):",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return None
        confirmation, accepted = QInputDialog.getText(
            self,
            f"Cambiar contraseña de {role}",
            "Confirma la nueva contraseña:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return None
        if password != confirmation:
            self._notify("Validación", "Las contraseñas no coinciden.")
            return None
        return password

    def _reset_student_password(self) -> None:
        student_id = self._selected_record_id(self.student_accounts_table)
        if student_id is None:
            self._notify(
                "Selecciona un estudiante",
                "Selecciona la cuenta del estudiante que deseas actualizar.",
            )
            return
        password = self._request_new_password("estudiante")
        if password is None:
            return
        try:
            AutenticacionService().restablecer_contrasena_estudiante(
                student_id,
                password,
            )
            self._notify(
                "Contraseña actualizada",
                "La nueva contraseña del estudiante se guardó correctamente. "
                "Comunícasela de forma privada.",
            )
        except ErrorAutenticacion as exc:
            self._notify("No se pudo cambiar la contraseña", str(exc))
        except SQLAlchemyError as exc:
            self._show_error("No se pudo cambiar la contraseña del estudiante.", exc)

    def _reset_teacher_password(self) -> None:
        teacher_id = self._selected_record_id(self.teacher_accounts_table)
        if teacher_id is None:
            self._notify(
                "Selecciona un docente",
                "Selecciona la cuenta del docente que deseas actualizar.",
            )
            return
        password = self._request_new_password("docente")
        if password is None:
            return
        try:
            AutenticacionService().restablecer_contrasena_docente(
                teacher_id,
                password,
            )
            self._notify(
                "Contraseña actualizada",
                "La nueva contraseña del docente se guardó correctamente. "
                "Comunícasela de forma privada.",
            )
        except ErrorAutenticacion as exc:
            self._notify("No se pudo cambiar la contraseña", str(exc))
        except SQLAlchemyError as exc:
            self._show_error("No se pudo cambiar la contraseña del docente.", exc)

    def _add_student(self) -> None:
        first = self.student_first_name.text().strip()
        last = self.student_last_name.text().strip()
        email = self.student_email.text().strip()
        career_id = self.student_career.currentData()
        if not first or not last or not email or career_id is None:
            self._notify(
                "Validación",
                "Completa nombre, apellido, correo y selecciona una carrera.",
            )
            return
        try:
            email = validar_correo(email)
        except ErrorAutenticacion as exc:
            self._notify("Correo no válido", str(exc))
            return
        try:
            with session_scope() as db:
                db.add(
                    Estudiante(
                        nombre=first,
                        apellido=last,
                        correo=email,
                        tipo_ingreso=str(self.student_type.currentData()),
                        carrera_id=career_id,
                    )
                )
            self.student_first_name.clear()
            self.student_last_name.clear()
            self.student_email.clear()
            self.refresh_all()
        except IntegrityError:
            self._notify("Correo duplicado", "Ya existe un estudiante con ese correo.")
        except SQLAlchemyError as exc:
            self._show_error("No se pudo registrar el estudiante.", exc)

    def _submit_enrollment(self) -> None:
        student_id = self.enrollment_student.currentData()
        period = self.enrollment_period.text().strip()
        if student_id is None or not period:
            self._notify("Validación", "Selecciona al estudiante e indica el período.")
            return
        selected_rows = sorted(
            {index.row() for index in self.enrollment_groups.selectedIndexes()}
        )
        group_ids: list[int] = []
        for row in selected_rows:
            item = self.enrollment_groups.item(row, 0)
            if (
                item is not None
                and normalizar_periodo(str(item.data(Qt.ItemDataRole.UserRole)))
                == normalizar_periodo(period)
            ):
                group_ids.append(int(item.text()))
        if not group_ids:
            self._notify(
                "Selección vacía",
                "Selecciona uno o más grupos del período indicado.",
            )
            return
        try:
            result = MatriculaService().inscribir(
                int(student_id),
                group_ids,
                period,
                creditos_minimos=self.enrollment_min_credits.value(),
                creditos_maximos=self.enrollment_max_credits.value(),
            )
            self._notify(
                "Matrícula guardada",
                f"Solicitud #{result.matricula_id}: "
                f"{result.grupos_inscritos} grupo(s), "
                f"{result.creditos_totales} crédito(s).",
            )
            self.refresh_all()
        except MatriculaError as exc:
            self._notify("No se pudo completar la matrícula", str(exc))
        except SQLAlchemyError as exc:
            self._show_error("Falló la transacción de matrícula.", exc)

    def load_checklist(self, *_args: object) -> None:
        if not hasattr(self, "documents_table"):
            return
        student_id = self.document_student.currentData()
        if student_id is None:
            self.documents_table.setRowCount(0)
            return
        try:
            with session_scope() as db:
                records = list(
                    db.scalars(
                        select(DocumentoChecklist).where(
                            DocumentoChecklist.estudiante_id == student_id
                        )
                    )
                )
            by_type = {record.tipo_documento: record for record in records}
            self.documents_table.setRowCount(len(DOCUMENT_TYPES))
            for row, name in enumerate(DOCUMENT_TYPES):
                record = by_type.get(name)
                name_item = QTableWidgetItem(name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                received = QTableWidgetItem()
                verified = QTableWidgetItem()
                for item, checked in (
                    (received, bool(record and record.recibido)),
                    (verified, bool(record and record.verificado)),
                ):
                    item.setFlags(
                        (item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled
                    )
                    item.setCheckState(
                        Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                    )
                self.documents_table.setItem(row, 0, name_item)
                self.documents_table.setItem(row, 1, received)
                self.documents_table.setItem(row, 2, verified)
        except SQLAlchemyError as exc:
            self._show_error("No se pudo cargar el checklist.", exc)

    def save_checklist(self) -> None:
        student_id = self.document_student.currentData()
        if student_id is None:
            self._notify("Validación", "Selecciona un estudiante.")
            return
        try:
            with session_scope() as db:
                records = {
                    record.tipo_documento: record
                    for record in db.scalars(
                        select(DocumentoChecklist).where(
                            DocumentoChecklist.estudiante_id == student_id
                        )
                    )
                }
                for row, document_type in enumerate(DOCUMENT_TYPES):
                    received = (
                        self.documents_table.item(row, 1).checkState()
                        == Qt.CheckState.Checked
                    )
                    verified = (
                        self.documents_table.item(row, 2).checkState()
                        == Qt.CheckState.Checked
                    )
                    if verified and not received:
                        raise ValueError(
                            f"Marca como recibido «{document_type}» antes de verificarlo."
                        )
                    record = records.get(document_type)
                    if record is None:
                        record = DocumentoChecklist(
                            estudiante_id=int(student_id),
                            tipo_documento=document_type,
                        )
                        db.add(record)
                    record.recibido = received
                    record.verificado = verified
                    record.recibido_en = datetime.now() if received else None
            self._notify("Checklist guardado", "Los documentos fueron actualizados.")
        except ValueError as exc:
            self._notify("Validación", str(exc))
        except SQLAlchemyError as exc:
            self._show_error("No se pudo guardar el checklist.", exc)

    def export_excel(self) -> None:
        destination = self._choose_path(
            "Guardar oferta académica",
            "oferta_academica.xlsx",
            "Libro de Excel (*.xlsx)",
        )
        if destination is None:
            return

        def operation() -> Path:
            with session_scope() as db:
                records = db.execute(
                    select(Grupo, Asignatura)
                    .join(Grupo.asignatura)
                    .order_by(Grupo.periodo, Grupo.dia, Grupo.hora_inicio)
                ).all()
                counts = self._enrollment_counts(
                    db,
                    [group.id for group, _ in records],
                )
                rows = [
                    {
                        "asignatura": subject.nombre,
                        "codigo": subject.codigo,
                        "periodo": group.periodo,
                        "grupo": group.seccion,
                        "dia": group.dia,
                        "hora_inicio": group.hora_inicio.strftime("%H:%M"),
                        "hora_fin": group.hora_fin.strftime("%H:%M"),
                        "edificio": group.edificio,
                        "aula": group.aula,
                        "cupo_maximo": group.cupo_maximo,
                        "inscritos": counts.get(group.id, 0),
                    }
                    for group, subject in records
                ]
            return exportar_oferta_academica(rows, destination)

        self._run_worker(operation, "Generando archivo Excel…")

    def export_appointment_pdf(self) -> None:
        student_id = self.report_student.currentData()
        if student_id is None:
            self._notify("Validación", "Selecciona un estudiante para el comprobante.")
            return
        destination = self._choose_path(
            "Guardar comprobante de cita",
            "comprobante_cita.pdf",
            "Documento PDF (*.pdf)",
        )
        if destination is None:
            return

        def operation() -> Path:
            with session_scope() as db:
                student = db.scalar(
                    select(Estudiante)
                    .options(selectinload(Estudiante.carrera))
                    .where(Estudiante.id == student_id)
                )
                if student is None:
                    raise ValueError("El estudiante seleccionado ya no existe.")
                data = {
                    "estudiante": f"{student.nombre} {student.apellido}",
                    "identificacion": student.correo,
                    "fecha_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "ubicacion": student.carrera.nombre,
                    "codigo_validacion": f"UNI-{student.id:06d}",
                }
            return generar_comprobante_cita(data, destination)

        self._run_worker(operation, "Generando comprobante PDF…")

    def export_dossier_pdf(self) -> None:
        student_id = self.report_student.currentData()
        if student_id is None:
            self._notify("Validación", "Selecciona un estudiante para el expediente.")
            return
        destination = self._choose_path(
            "Guardar expediente académico",
            "expediente_academico.pdf",
            "Documento PDF (*.pdf)",
        )
        if destination is None:
            return

        def operation() -> Path:
            with session_scope() as db:
                student = db.scalar(
                    select(Estudiante)
                    .options(
                        selectinload(Estudiante.carrera),
                        selectinload(Estudiante.documentos),
                    )
                    .where(Estudiante.id == student_id)
                )
                if student is None:
                    raise ValueError("El estudiante seleccionado ya no existe.")
                data = {
                    "estudiante": f"{student.nombre} {student.apellido}",
                    "identificacion": student.correo,
                    "tipo_ingreso": (
                        "Nuevo ingreso"
                        if student.tipo_ingreso == "nuevo_ingreso"
                        else "Reingreso"
                    ),
                    "carrera": student.carrera.nombre,
                    "documentos": [
                        {
                            "nombre": document_type,
                            "recibido": next(
                                (
                                    document.recibido
                                    for document in student.documentos
                                    if document.tipo_documento == document_type
                                ),
                                False,
                            ),
                            "verificado": next(
                                (
                                    document.verificado
                                    for document in student.documentos
                                    if document.tipo_documento == document_type
                                ),
                                False,
                            ),
                        }
                        for document_type in DOCUMENT_TYPES
                    ],
                    "ubicacion": {},
                }
            return generar_hoja_expediente(data, destination)

        self._run_worker(operation, "Generando expediente PDF…")

    @staticmethod
    def _choose_path(
        title: str,
        default_name: str,
        file_filter: str,
    ) -> Path | None:
        filename, _ = QFileDialog.getSaveFileName(
            None,
            title,
            default_name,
            file_filter,
        )
        return Path(filename) if filename else None

    def _run_worker(self, operation: Callable[[], object], status: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker_result = None
        self._worker_error = None
        self.report_status.setText(status)
        self._worker = ReportWorker(operation, self)
        self._worker.started.connect(self._on_worker_started)
        self._worker.result_ready.connect(self._on_worker_result)
        self._worker.error_occurred.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_worker_started(self) -> None:
        for button in self.report_buttons:
            button.setEnabled(False)
        self.report_status.setText("Procesando reporte en segundo plano…")

    def _on_worker_result(self, result: object) -> None:
        self._worker_result = result

    def _on_worker_error(self, message: str) -> None:
        self._worker_error = message

    def _on_worker_finished(self) -> None:
        for button in self.report_buttons:
            button.setEnabled(True)
        self.report_status.setText("Sin tareas en curso")
        if self._worker_error:
            QMessageBox.warning(self, "Error de reporte", self._worker_error)
        elif isinstance(self._worker_result, Path):
            QMessageBox.information(
                self,
                "Reporte generado",
                f"Archivo guardado en:\n{self._worker_result}",
            )
        self._worker = None

    def _on_tab_changed(self, index: int) -> None:
        try:
            if self.tabs.tabText(index) == "Oferta académica":
                self.load_offer()
            elif self.tabs.tabText(index) == "Accesos":
                self.load_access_accounts()
            elif self.tabs.tabText(index) == "Matrícula":
                self.load_enrollment_groups()
            elif self.tabs.tabText(index) == "Documentos":
                self.load_checklist()
        except SQLAlchemyError as exc:
            self._show_error("No se pudieron actualizar los datos.", exc)

    @staticmethod
    def _notify(title: str, message: str) -> None:
        QMessageBox.information(None, title, message)

    def _show_error(self, message: str, exc: Exception) -> None:
        logger.exception("%s", message, exc_info=exc)
        QMessageBox.critical(self, "Error", f"{message}\n\n{exc}")

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Proceso en curso",
                "Espera a que termine la generación del reporte antes de cerrar.",
            )
            event.ignore()
            return
        event.accept()
