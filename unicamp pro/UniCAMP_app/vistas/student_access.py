"""Acceso de estudiantes y portal académico personal."""

from __future__ import annotations

import hmac
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from config.database import session_scope
from modelos.entidades import (
    Asignatura,
    Carrera,
    Estudiante,
    Grupo,
    Matricula,
    MatriculaDetail,
    PerfilDocente,
)
from servicios.autenticacion_service import (
    AutenticacionService,
    ErrorAutenticacion,
    _verify_password,
)
from servicios.matricula_service import MatriculaError, MatriculaService
from servicios.periodos import normalizar_periodo, variantes_periodo

logger = logging.getLogger(__name__)
ADMIN_EMAIL = "unicamp_admin26@gmail.com"
ADMIN_PASSWORD_HASH = (
    "pbkdf2_sha256$310000$ajeHio0tLXtxSdOXCBNoEQ=="
    "$12d_PcA61ifF3Vd1fIKHZN2TDdzkQfkZ-142hO48224="
)

ACCESS_STYLE = """
QMainWindow, QWidget {
    background: #f3f6fb; color: #172b4d;
    font-family: 'Segoe UI'; font-size: 13px;
}
QLabel#Welcome {
    color: #17365d; font-size: 25px; font-weight: 800;
}
QLabel#Subheading { color: #637590; font-size: 14px; }
QGroupBox {
    background: white; border: 1px solid #dce5f0; border-radius: 9px;
    margin-top: 12px; padding: 16px; font-weight: 700;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox {
    background: white; border: 1px solid #ccd8e7; border-radius: 5px;
    padding: 8px; min-height: 23px;
}
QPushButton {
    background: #347bd3; color: white; border: none; border-radius: 5px;
    padding: 10px 15px; font-weight: 700;
}
QPushButton:hover { background: #2466b6; }
QTableWidget {
    background: white; border: 1px solid #dce5f0;
    gridline-color: #e8edf5; alternate-background-color: #f7f9fc;
}
QHeaderView::section {
    background: #17365d; color: white; padding: 9px; border: none;
    font-weight: 700;
}
QTabBar::tab { background: #e6edf7; padding: 10px 16px; margin: 3px; }
QTabBar::tab:selected { background: #347bd3; color: white; }
"""


class StudentLoginWindow(QMainWindow):
    """Permite acceder a los portales de estudiantes y docentes."""

    def __init__(self) -> None:
        super().__init__()
        self._portal: StudentPortalWindow | None = None
        self.setWindowTitle("UniCamp | Acceso académico")
        self.setFixedSize(700, 760)
        self.setStyleSheet(ACCESS_STYLE)
        self.logo_path = Path(__file__).resolve().parents[1] / "imagenes" / "logo.jpeg"
        logo_pixmap = QPixmap(str(self.logo_path))
        if logo_pixmap.isNull():
            logger.warning("No se pudo cargar el logo desde %s.", self.logo_path)
        else:
            self.setWindowIcon(QIcon(logo_pixmap))
        self._build_ui()
        self._load_careers()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(32, 12, 32, 28)
        root.setSpacing(18)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedHeight(160)
        logo_pixmap = QPixmap(str(self.logo_path))
        if not logo_pixmap.isNull():
            logo.setPixmap(
                logo_pixmap.scaled(
                    300,
                    200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        root.addWidget(logo)

        welcome = QLabel("¡Bienvenido/a al portal académico!")
        welcome.setObjectName("Subheading")
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome.setWordWrap(True)
        root.addWidget(welcome)

        self.admin_button = QPushButton("Entrar como administrador")
        self.admin_button.setMinimumHeight(44)
        self.admin_button.clicked.connect(self._open_admin_panel)
        root.addWidget(self.admin_button)

        self.access_tabs = QTabWidget()
        self.access_tabs.addTab(self._login_page(), "Iniciar sesión")
        self.access_tabs.addTab(self._registration_page(), "Crear cuenta")
        self.access_tabs.currentChanged.connect(self._on_access_tab_changed)

        self.teacher_access_tabs = QTabWidget()
        self.teacher_access_tabs.addTab(self._teacher_login_page(), "Iniciar sesión")
        self.teacher_access_tabs.addTab(self._teacher_registration_page(), "Crear cuenta")
        self.teacher_access_tabs.currentChanged.connect(
            self._on_teacher_access_tab_changed
        )

        self.role_tabs = QTabWidget()
        self.role_tabs.addTab(self.access_tabs, "Estudiantes")
        self.role_tabs.addTab(self.teacher_access_tabs, "Docentes")
        root.addWidget(self.role_tabs)

        note = QLabel(
            "Estudiantes: ingresa con tu carnet. Docentes: ingresa con tu correo. "
            "Cada portal tiene su propio registro y acceso."
        )
        note.setObjectName("Subheading")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch()
        self.setCentralWidget(central)

    def _login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Acceso de estudiante")
        form = QFormLayout(box)
        self.login_carnet = QLineEdit()
        self.login_carnet.setPlaceholderText("25-04497-0")
        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Contraseña")
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Carnet", self.login_carnet)
        form.addRow("Contraseña", self.login_password)
        layout.addWidget(box)

        sign_in = QPushButton("Ingresar")
        sign_in.clicked.connect(self._sign_in)
        layout.addWidget(sign_in)
        layout.addStretch()
        self.login_password.returnPressed.connect(self._sign_in)
        return page

    def _registration_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)
        box = QGroupBox("Crear cuenta estudiantil")
        form = QFormLayout(box)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(12)
        self.register_name = QLineEdit()
        self.register_name.setPlaceholderText("Nombre")
        self.register_last_name = QLineEdit()
        self.register_last_name.setPlaceholderText("Apellido")
        self.register_email = QLineEdit()
        self.register_email.setPlaceholderText("correo@gmail.com o correo@outlook.com")
        self.register_email.textEdited.connect(
            lambda value: self._normalize_email_input(self.register_email, value)
        )
        self.register_carnet = QLineEdit()
        self.register_carnet.setPlaceholderText("25-04497-0")
        self.register_password = QLineEdit()
        self.register_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.register_password.setPlaceholderText("Por ejemplo: gwe344")
        self.register_confirm = QLineEdit()
        self.register_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.register_confirm.setPlaceholderText("Repite tu contraseña")
        self.register_type = QComboBox()
        self.register_type.addItem("Nuevo ingreso", "nuevo_ingreso")
        self.register_type.addItem("Reingreso", "reingreso")
        self.register_career = QComboBox()
        form.addRow("Nombre", self.register_name)
        form.addRow("Apellido", self.register_last_name)
        form.addRow("Correo", self.register_email)
        form.addRow("Carnet", self.register_carnet)
        form.addRow("Contraseña", self.register_password)
        form.addRow("Confirmar contraseña", self.register_confirm)
        form.addRow("Tipo de ingreso", self.register_type)
        form.addRow("Carrera", self.register_career)
        layout.addWidget(box)

        requirements = QLabel(
            "Formato de carnet: 25-04497-0. La contraseña debe tener al menos "
            "6 caracteres e incluir letras y números."
        )
        requirements.setObjectName("Subheading")
        requirements.setWordWrap(True)
        layout.addWidget(requirements)
        register = QPushButton("Crear cuenta e ingresar")
        register.clicked.connect(self._register)
        layout.addWidget(register)
        layout.addStretch()
        scroll_area.setWidget(content)
        page_layout.addWidget(scroll_area)
        return page

    @staticmethod
    def _normalize_email_input(field: QLineEdit, value: str) -> None:
        normalized = value.lower()
        if normalized != value:
            cursor_position = field.cursorPosition()
            field.setText(normalized)
            field.setCursorPosition(min(cursor_position, len(normalized)))

    def _teacher_login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Acceso de docente")
        form = QFormLayout(box)
        self.teacher_login_email = QLineEdit()
        self.teacher_login_email.setPlaceholderText(
            "correo@gmail.com o correo@outlook.com"
        )
        self.teacher_login_email.textEdited.connect(
            lambda value: self._normalize_email_input(
                self.teacher_login_email,
                value,
            )
        )
        self.teacher_login_password = QLineEdit()
        self.teacher_login_password.setPlaceholderText("Contraseña")
        self.teacher_login_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Correo", self.teacher_login_email)
        form.addRow("Contraseña", self.teacher_login_password)
        layout.addWidget(box)

        sign_in = QPushButton("Ingresar como docente")
        sign_in.clicked.connect(self._teacher_sign_in)
        layout.addWidget(sign_in)
        layout.addStretch()
        self.teacher_login_password.returnPressed.connect(self._teacher_sign_in)
        return page

    def _teacher_registration_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)
        box = QGroupBox("Crear cuenta docente")
        form = QFormLayout(box)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(12)
        self.teacher_register_name = QLineEdit()
        self.teacher_register_name.setPlaceholderText("Nombre")
        self.teacher_register_last_name = QLineEdit()
        self.teacher_register_last_name.setPlaceholderText("Apellido")
        self.teacher_register_email = QLineEdit()
        self.teacher_register_email.setPlaceholderText(
            "correo@gmail.com o correo@outlook.com"
        )
        self.teacher_register_email.textEdited.connect(
            lambda value: self._normalize_email_input(
                self.teacher_register_email,
                value,
            )
        )
        self.teacher_register_password = QLineEdit()
        self.teacher_register_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.teacher_register_password.setPlaceholderText("Crea una contraseña")
        self.teacher_register_confirm = QLineEdit()
        self.teacher_register_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.teacher_register_confirm.setPlaceholderText("Repite tu contraseña")
        self.teacher_register_career = QComboBox()
        form.addRow("Nombre", self.teacher_register_name)
        form.addRow("Apellido", self.teacher_register_last_name)
        form.addRow("Correo", self.teacher_register_email)
        form.addRow("Contraseña", self.teacher_register_password)
        form.addRow("Confirmar contraseña", self.teacher_register_confirm)
        form.addRow("Seleccione una carrera como docente", self.teacher_register_career)
        layout.addWidget(box)

        requirements = QLabel(
            "La contraseña debe tener al menos 6 caracteres e incluir letras y números."
        )
        requirements.setObjectName("Subheading")
        requirements.setWordWrap(True)
        layout.addWidget(requirements)
        register = QPushButton("Crear cuenta docente")
        register.clicked.connect(self._teacher_register)
        layout.addWidget(register)
        layout.addStretch()
        scroll_area.setWidget(content)
        page_layout.addWidget(scroll_area)
        return page

    def _load_careers(self) -> None:
        try:
            selected_career_id = self.register_career.currentData()
            selected_teacher_career_id = self.teacher_register_career.currentData()
            with session_scope() as db:
                careers = list(
                    db.scalars(select(Carrera).order_by(Carrera.nombre))
                )
            self.register_career.clear()
            self.teacher_register_career.clear()
            for career in careers:
                self.register_career.addItem(
                    f"{career.codigo} - {career.nombre}",
                    career.id,
                )
                self.teacher_register_career.addItem(
                    f"{career.codigo} - {career.nombre}",
                    career.id,
                )
            restored_index = self.register_career.findData(selected_career_id)
            if restored_index >= 0:
                self.register_career.setCurrentIndex(restored_index)
            teacher_restored_index = self.teacher_register_career.findData(
                selected_teacher_career_id
            )
            if teacher_restored_index >= 0:
                self.teacher_register_career.setCurrentIndex(teacher_restored_index)
        except SQLAlchemyError as exc:
            logger.exception("No se pudieron cargar las carreras para registro.")
            QMessageBox.critical(
                self,
                "Error de base de datos",
                f"No fue posible cargar las carreras.\n\n{exc}",
            )

    def _on_access_tab_changed(self, index: int) -> None:
        if index == 1:
            self._load_careers()

    def _on_teacher_access_tab_changed(self, index: int) -> None:
        if index == 1:
            self._load_careers()

    def _sign_in(self) -> None:
        try:
            student_id = AutenticacionService().autenticar(
                self.login_carnet.text(),
                self.login_password.text(),
            )
            self._open_portal(student_id)
        except ErrorAutenticacion as exc:
            QMessageBox.warning(self, "No se pudo iniciar sesión", str(exc))
        except SQLAlchemyError as exc:
            logger.exception("Falló la autenticación del estudiante.")
            QMessageBox.critical(
                self,
                "Error de conexión",
                f"No fue posible validar tus credenciales.\n\n{exc}",
            )

    def _register(self) -> None:
        if self.register_password.text() != self.register_confirm.text():
            QMessageBox.warning(
                self,
                "Validación",
                "Las contraseñas no coinciden.",
            )
            return
        career_id = self.register_career.currentData()
        if career_id is None:
            QMessageBox.warning(
                self,
                "Carrera no disponible",
                "No hay carreras registradas. Contacta a la administración.",
            )
            return
        try:
            student_id = AutenticacionService().registrar_estudiante(
                nombre=self.register_name.text(),
                apellido=self.register_last_name.text(),
                correo=self.register_email.text(),
                carnet=self.register_carnet.text(),
                password=self.register_password.text(),
                tipo_ingreso=str(self.register_type.currentData()),
                carrera_id=int(career_id),
            )
            QMessageBox.information(
                self,
                "Cuenta creada",
                "Tu cuenta fue creada correctamente. ¡Bienvenido/a a UniCamp!",
            )
            self._open_portal(student_id)
        except ErrorAutenticacion as exc:
            QMessageBox.warning(self, "No se pudo crear la cuenta", str(exc))
        except SQLAlchemyError as exc:
            logger.exception("Falló el registro de la cuenta estudiantil.")
            QMessageBox.critical(
                self,
                "Error de registro",
                f"No fue posible crear tu cuenta.\n\n{exc}",
            )

    def _teacher_sign_in(self) -> None:
        try:
            teacher_id = AutenticacionService().autenticar_docente(
                self.teacher_login_email.text(),
                self.teacher_login_password.text(),
            )
            self._open_teacher_portal(teacher_id)
        except ErrorAutenticacion as exc:
            QMessageBox.warning(self, "No se pudo iniciar sesión", str(exc))
        except SQLAlchemyError as exc:
            logger.exception("Falló la autenticación del docente.")
            QMessageBox.critical(
                self,
                "Error de conexión",
                f"No fue posible validar tus credenciales.\n\n{exc}",
            )

    def _teacher_register(self) -> None:
        if (
            self.teacher_register_password.text()
            != self.teacher_register_confirm.text()
        ):
            QMessageBox.warning(
                self,
                "Validación",
                "Las contraseñas no coinciden.",
            )
            return
        career_id = self.teacher_register_career.currentData()
        if career_id is None:
            QMessageBox.warning(
                self,
                "Carrera no disponible",
                "No hay carreras registradas. Contacta a la administración.",
            )
            return
        try:
            teacher_id = AutenticacionService().registrar_docente(
                nombre=self.teacher_register_name.text(),
                apellido=self.teacher_register_last_name.text(),
                correo=self.teacher_register_email.text(),
                password=self.teacher_register_password.text(),
                carrera_id=int(career_id),
            )
            QMessageBox.information(
                self,
                "Cuenta creada",
                "Tu cuenta docente fue creada correctamente.",
            )
            self._open_teacher_portal(teacher_id)
        except ErrorAutenticacion as exc:
            QMessageBox.warning(self, "No se pudo crear la cuenta", str(exc))
        except SQLAlchemyError as exc:
            logger.exception("Falló el registro de la cuenta docente.")
            QMessageBox.critical(
                self,
                "Error de registro",
                f"No fue posible crear tu cuenta.\n\n{exc}",
            )

    def _open_portal(self, student_id: int) -> None:
        self._portal = StudentPortalWindow(student_id, self)
        self._portal.show()
        self.hide()

    def _open_teacher_portal(self, teacher_id: int) -> None:
        self._teacher_portal = TeacherPortalWindow(teacher_id, self)
        self._teacher_portal.show()
        self.hide()

    def _open_admin_panel(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Acceso de administración")
        form = QFormLayout(dialog)
        email = QLineEdit()
        email.setPlaceholderText("Correo administrativo")
        email.textEdited.connect(
            lambda value: self._normalize_email_input(email, value)
        )
        form.addRow("Correo", email)
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("Contraseña administrativa")
        form.addRow("Contraseña", password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if (
            email.text().strip().casefold() != ADMIN_EMAIL
            or not _verify_password(password.text(), ADMIN_PASSWORD_HASH)
        ):
            QMessageBox.warning(
                self,
                "Acceso denegado",
                "El correo o la contraseña administrativa son incorrectos.",
            )
            return

        from vistas.main_window import MainWindow

        self._admin_window = MainWindow()
        self._admin_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._admin_window.destroyed.connect(self._show_login_after_admin)
        self._admin_window.show()
        self.hide()

    def _show_login_after_admin(self) -> None:
        self._load_careers()
        self.show()


class TeacherPortalWindow(QMainWindow):
    """Portal docente con la oferta académica de su carrera."""

    def __init__(self, teacher_id: int, login_window: StudentLoginWindow) -> None:
        super().__init__()
        self.teacher_id = teacher_id
        self.login_window = login_window
        self.setWindowTitle("UniCamp | Portal del docente")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(ACCESS_STYLE)

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 22)
        top = QHBoxLayout()
        self.welcome_label = QLabel("Portal docente")
        self.welcome_label.setObjectName("Welcome")
        top.addWidget(self.welcome_label)
        top.addStretch()
        logout = QPushButton("Cerrar sesión")
        logout.clicked.connect(self._logout)
        top.addWidget(logout)
        root.addLayout(top)
        self.teacher_summary = QLabel("")
        self.teacher_summary.setObjectName("Subheading")
        root.addWidget(self.teacher_summary)

        heading = QLabel("Clases asignadas a tu cuenta")
        heading.setObjectName("Subheading")
        root.addWidget(heading)
        self.offer_table = QTableWidget(0, 6)
        self.offer_table.setHorizontalHeaderLabels(
            ["Período", "Asignatura", "Grupo", "Día", "Horario", "Cupos"]
        )
        self.offer_table.setAlternatingRowColors(True)
        self.offer_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.offer_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.offer_table.verticalHeader().setVisible(False)
        self.offer_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.offer_table, 1)
        self.setCentralWidget(central)
        self._load_teacher()

    def _load_teacher(self) -> None:
        try:
            with session_scope() as db:
                teacher = db.scalar(
                    select(PerfilDocente)
                    .options(selectinload(PerfilDocente.carrera))
                    .where(PerfilDocente.id == self.teacher_id)
                )
                if teacher is None or not teacher.activo:
                    raise ValueError("La cuenta docente ya no está disponible.")
                full_name = f"{teacher.nombre} {teacher.apellido}"
                career = teacher.carrera.nombre
                groups = list(
                    db.scalars(
                        select(Grupo)
                        .join(Grupo.asignatura)
                        .options(selectinload(Grupo.asignatura))
                        .where(
                            Grupo.docente_id == teacher.id,
                            Asignatura.carreras.any(
                                Carrera.id == teacher.carrera_id
                            ),
                        )
                        .order_by(Grupo.periodo, Asignatura.nombre, Grupo.seccion)
                    )
                )

            self.welcome_label.setText(f"¡Bienvenido/a, {full_name}!")
            self.teacher_summary.setText(
                f"Correo: {teacher.correo}    |    Carrera: {career}"
            )
            self.offer_table.setRowCount(len(groups))
            for row, group in enumerate(groups):
                start = group.hora_inicio.strftime("%H:%M")
                end = group.hora_fin.strftime("%H:%M")
                values = (
                    group.periodo,
                    group.asignatura.nombre,
                    group.seccion,
                    group.dia,
                    f"{start} - {end}",
                    group.cupo_maximo,
                )
                for column, value in enumerate(values):
                    self.offer_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(str(value)),
                    )
        except (SQLAlchemyError, ValueError) as exc:
            logger.exception("No se pudo cargar el portal del docente.")
            QMessageBox.critical(
                self,
                "Error al cargar perfil",
                f"No fue posible abrir el portal docente.\n\n{exc}",
            )
            self.close()

    def _logout(self) -> None:
        self.login_window.teacher_login_password.clear()
        self.close()

    def closeEvent(self, event) -> None:
        if not self.login_window.isVisible():
            self.login_window.show()
        event.accept()


class StudentPortalWindow(QMainWindow):
    """Portal limitado al estudiante autenticado."""

    def __init__(self, student_id: int, login_window: StudentLoginWindow) -> None:
        super().__init__()
        self.student_id = student_id
        self.login_window = login_window
        self.setWindowTitle("UniCamp | Portal del estudiante")
        self.resize(1120, 760)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(ACCESS_STYLE)
        self._build_ui()
        self._load_student()
        self.refresh_data()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 22)
        root.setSpacing(12)
        top = QHBoxLayout()
        self.welcome_label = QLabel("¡Bienvenido/a!")
        self.welcome_label.setObjectName("Welcome")
        top.addWidget(self.welcome_label)
        top.addStretch()
        logout = QPushButton("Cerrar sesión")
        logout.clicked.connect(self._logout)
        top.addWidget(logout)
        root.addLayout(top)
        self.student_summary = QLabel("")
        self.student_summary.setObjectName("Subheading")
        root.addWidget(self.student_summary)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._offer_page(), "Oferta y matrícula")
        self.tabs.addTab(self._my_enrollments_page(), "Mis materias")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

    def _offer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Carrera"))
        self.career_filter = QComboBox()
        self.career_filter.addItem("Todas las carreras", None)
        self.career_filter.currentIndexChanged.connect(self.load_offer)
        filters.addWidget(self.career_filter, 1)
        filters.addWidget(QLabel("Período académico"))
        self.period_filter = QLineEdit()
        self.period_filter.setPlaceholderText("Ej. 2026-1")
        self.period_filter.textChanged.connect(self.load_offer)
        filters.addWidget(self.period_filter, 1)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh_data)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        hint = QLabel(
            "Selecciona grupos del mismo período y pulsa matricular. "
            "La inscripción valida cupos, créditos y choques de horario."
        )
        hint.setObjectName("Subheading")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.offer_hint = hint
        self.offer_table = self._table(
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
        self.offer_table.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        layout.addWidget(self.offer_table, 1)
        actions = QHBoxLayout()
        self.minimum_credits = QSpinBox()
        self.minimum_credits.setRange(0, 60)
        self.minimum_credits.setValue(0)
        self.minimum_credits.setMaximumWidth(70)
        self.maximum_credits = QSpinBox()
        self.maximum_credits.setRange(1, 60)
        self.maximum_credits.setValue(30)
        self.maximum_credits.setMaximumWidth(70)
        actions.addWidget(QLabel("Créditos mínimos"))
        actions.addWidget(self.minimum_credits)
        actions.addWidget(QLabel("Créditos máximos"))
        actions.addWidget(self.maximum_credits)
        actions.addStretch()
        enroll = QPushButton("Matricular grupos seleccionados")
        enroll.clicked.connect(self._enroll_selected)
        actions.addWidget(enroll)
        layout.addLayout(actions)
        return page

    def _my_enrollments_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        refresh = QPushButton("Actualizar mis materias")
        refresh.clicked.connect(self.load_my_enrollments)
        layout.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignRight)
        self.my_enrollments = self._table(
            [
                "Período",
                "Asignatura",
                "Docente",
                "Grupo",
                "Día",
                "Horario",
                "Ubicación",
                "Estado",
            ]
        )
        layout.addWidget(self.my_enrollments, 1)
        return page

    @staticmethod
    def _table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _load_student(self) -> None:
        try:
            with session_scope() as db:
                student = db.scalar(
                    select(Estudiante)
                    .options(
                        selectinload(Estudiante.carrera),
                        selectinload(Estudiante.cuenta),
                    )
                    .where(Estudiante.id == self.student_id)
                )
                if student is None or not student.activo:
                    raise ValueError("La cuenta de estudiante ya no está disponible.")
                full_name = f"{student.nombre} {student.apellido}"
                carnet = student.cuenta.carnet if student.cuenta else ""
                career = student.carrera.nombre
                self.student_career_id = student.carrera_id
                careers = list(
                    db.scalars(select(Carrera).order_by(Carrera.nombre))
                )
            self.welcome_label.setText(f"¡Bienvenido/a, {full_name}!")
            self.student_summary.setText(
                f"Carnet: {carnet}    |    Carrera: {career}"
            )
            self.career_filter.clear()
            self.career_filter.addItem("Todas las carreras", None)
            for available_career in careers:
                self.career_filter.addItem(
                    f"{available_career.codigo} - {available_career.nombre}",
                    available_career.id,
                )
            self.career_filter.setCurrentIndex(0)
        except (SQLAlchemyError, ValueError) as exc:
            logger.exception("No se pudo cargar el perfil del estudiante.")
            QMessageBox.critical(
                self,
                "Error al cargar perfil",
                f"No fue posible abrir el portal.\n\n{exc}",
            )
            self.close()

    def refresh_data(self) -> None:
        self.load_offer()
        self.load_my_enrollments()

    def load_offer(self, *_args: object) -> None:
        if not hasattr(self, "offer_table"):
            return
        period = self.period_filter.text().strip()
        if not period:
            self.offer_table.clearSelection()
            self.offer_table.setRowCount(0)
            self.offer_hint.setText(
                "Escribe un período académico para consultar los grupos disponibles."
            )
            return
        statement = (
            select(Grupo, Asignatura)
            .join(Grupo.asignatura)
            .options(selectinload(Grupo.docente))
            .where(Grupo.periodo.in_(variantes_periodo(period)))
            .order_by(Grupo.dia, Grupo.hora_inicio)
        )
        career_id = self.career_filter.currentData()
        if career_id is not None:
            statement = statement.where(
                Asignatura.carreras.any(Carrera.id == career_id)
            )
        try:
            self.offer_table.clearSelection()
            with session_scope() as db:
                records = db.execute(statement).all()
                counts = self._enrollment_counts(
                    db,
                    [group.id for group, _ in records],
                )
            self.offer_table.setRowCount(len(records))
            for row, (group, subject) in enumerate(records):
                enrolled = counts.get(group.id, 0)
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
                    f"{enrolled} / {group.cupo_maximo}",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, group.periodo)
                    self.offer_table.setItem(row, column, item)
            self.offer_hint.setText(
                f"{len(records)} grupo(s) disponible(s) para «{period}»."
                if records
                else f"No hay grupos creados para el período «{period}»."
            )
        except SQLAlchemyError as exc:
            self._show_database_error("No se pudo consultar la oferta.", exc)

    def load_my_enrollments(self) -> None:
        statement = (
            select(Matricula, MatriculaDetail, Grupo, Asignatura)
            .join(Matricula.detalles)
            .join(MatriculaDetail.grupo)
            .join(Grupo.asignatura)
            .options(selectinload(Grupo.docente))
            .where(
                Matricula.estudiante_id == self.student_id,
                Matricula.estado != "cancelada",
            )
            .order_by(Matricula.periodo, Grupo.dia, Grupo.hora_inicio)
        )
        try:
            with session_scope() as db:
                records = db.execute(statement).all()
            self.my_enrollments.setRowCount(len(records))
            for row, (matricula, detail, group, subject) in enumerate(records):
                values = (
                    matricula.periodo,
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
                    f"{matricula.estado.capitalize()} / {detail.estado.capitalize()}",
                )
                for column, value in enumerate(values):
                    self.my_enrollments.setItem(row, column, QTableWidgetItem(str(value)))
        except SQLAlchemyError as exc:
            self._show_database_error("No se pudieron cargar tus materias.", exc)

    def _enroll_selected(self) -> None:
        period = self.period_filter.text().strip()
        if not period:
            QMessageBox.information(
                self,
                "Indica el período",
                "Escribe el período académico antes de seleccionar grupos.",
            )
            return
        group_ids: list[int] = []
        for row in sorted(
            {index.row() for index in self.offer_table.selectedIndexes()}
        ):
            item = self.offer_table.item(row, 0)
            if (
                item is not None
                and normalizar_periodo(str(item.data(Qt.ItemDataRole.UserRole)))
                == normalizar_periodo(period)
            ):
                group_ids.append(int(item.text()))
        if not group_ids:
            QMessageBox.information(
                self,
                "Selección vacía",
                "Selecciona uno o más grupos disponibles.",
            )
            return
        selected_career_id = self.career_filter.currentData()
        if (
            selected_career_id is not None
            and selected_career_id != self.student_career_id
        ):
            QMessageBox.information(
                self,
                "Carrera del estudiante",
                "Puedes consultar la oferta de otras carreras, pero solo puedes "
                "matricular grupos de la carrera asociada a tu cuenta.",
            )
            return
        try:
            result = MatriculaService().inscribir(
                self.student_id,
                group_ids,
                period,
                creditos_minimos=self.minimum_credits.value(),
                creditos_maximos=self.maximum_credits.value(),
            )
            QMessageBox.information(
                self,
                "Matrícula guardada",
                f"¡Listo! Se agregaron {result.grupos_inscritos} grupo(s) "
                f"con {result.creditos_totales} crédito(s).",
            )
            self.refresh_data()
        except MatriculaError as exc:
            QMessageBox.warning(
                self,
                "No se pudo completar la matrícula",
                str(exc),
            )
        except SQLAlchemyError as exc:
            self._show_database_error("No se pudo guardar la matrícula.", exc)

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
        location = [
            item
            for item in (group.edificio, group.pabellon, group.aula, group.ventanilla)
            if item
        ]
        return ", ".join(location) or "Sin ubicación"

    def _show_database_error(self, message: str, exc: Exception) -> None:
        logger.exception("%s", message)
        QMessageBox.critical(self, "Error de base de datos", f"{message}\n\n{exc}")

    def _logout(self) -> None:
        self.close()
        self.login_window.login_password.clear()
        self.login_window.show()

    def closeEvent(self, event) -> None:
        if self.login_window.isVisible():
            event.accept()
            return
        if self.login_window._portal is self:
            self.login_window._portal = None
        event.accept()
