"""Registro y autenticación de cuentas de estudiantes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from config.database import session_scope
from modelos.entidades import (
    CuentaDocente,
    CuentaEstudiante,
    Estudiante,
    PerfilDocente,
)

logger = logging.getLogger(__name__)

CARNET_PATTERN = re.compile(r"^\d{2}-\d{5}-\d$")
PASSWORD_ITERATIONS = 310_000
PASSWORD_MIN_LENGTH = 6


class ErrorAutenticacion(ValueError):
    """Error funcional de ingreso o creación de cuenta."""


def _validate_carnet(carnet: str) -> str:
    normalized = carnet.strip()
    if not CARNET_PATTERN.fullmatch(normalized):
        raise ErrorAutenticacion("El carnet debe tener el formato 25-04497-0.")
    return normalized


def _validate_password(password: str) -> None:
    if (
        len(password) < PASSWORD_MIN_LENGTH
        or not any(character.isalpha() for character in password)
        or not any(character.isdigit() for character in password)
    ):
        raise ErrorAutenticacion(
            "La contraseña debe tener al menos 6 caracteres e incluir letras y números."
        )


def validar_correo(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+-]+@(gmail\.com|outlook\.com)", normalized):
        raise ErrorAutenticacion(
            "El correo debe estar en minúsculas y terminar en @gmail.com "
            "o @outlook.com."
        )
    return normalized


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt_text, expected_text = encoded_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            logger.error("Algoritmo de hash de contraseña desconocido.")
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        logger.exception("El hash almacenado para una cuenta no es válido.")
        return False


class AutenticacionService:
    """Gestiona credenciales sin guardar contraseñas en texto plano."""

    def registrar_estudiante(
        self,
        *,
        nombre: str,
        apellido: str,
        correo: str,
        carnet: str,
        password: str,
        tipo_ingreso: str,
        carrera_id: int,
    ) -> int:
        carnet = _validate_carnet(carnet)
        _validate_password(password)
        if not nombre.strip() or not apellido.strip() or not correo.strip():
            raise ErrorAutenticacion(
                "Completa nombre, apellido y correo electrónico."
            )
        if tipo_ingreso not in {"nuevo_ingreso", "reingreso"}:
            raise ErrorAutenticacion("Selecciona un tipo de ingreso válido.")

        try:
            with session_scope() as db:
                student = Estudiante(
                    nombre=nombre.strip(),
                    apellido=apellido.strip(),
                    correo=correo.strip(),
                    tipo_ingreso=tipo_ingreso,
                    carrera_id=carrera_id,
                )
                student.cuenta = CuentaEstudiante(
                    carnet=carnet,
                    password_hash=_hash_password(password),
                )
                db.add(student)
                db.flush()
                return student.id
        except IntegrityError as exc:
            logger.info("No se pudo registrar la cuenta por una clave duplicada.")
            raise ErrorAutenticacion(
                "Ese carnet o correo ya está registrado."
            ) from exc

    def registrar_docente(
        self,
        *,
        nombre: str,
        apellido: str,
        correo: str,
        password: str,
        carrera_id: int,
    ) -> int:
        correo = validar_correo(correo)
        _validate_password(password)
        if not nombre.strip() or not apellido.strip():
            raise ErrorAutenticacion("Completa nombre y apellido.")
        if carrera_id <= 0:
            raise ErrorAutenticacion("Selecciona una carrera válida.")

        try:
            with session_scope() as db:
                teacher = PerfilDocente(
                    nombre=nombre.strip(),
                    apellido=apellido.strip(),
                    correo=correo,
                    carrera_id=carrera_id,
                )
                teacher.cuenta = CuentaDocente(
                    password_hash=_hash_password(password),
                )
                db.add(teacher)
                db.flush()
                return teacher.id
        except IntegrityError as exc:
            logger.info("No se pudo registrar la cuenta por un correo duplicado.")
            raise ErrorAutenticacion(
                "Ese correo ya está registrado como docente."
            ) from exc

    def autenticar(self, carnet: str, password: str) -> int:
        carnet = _validate_carnet(carnet)
        if not password:
            raise ErrorAutenticacion("Escribe tu contraseña.")

        with session_scope() as db:
            statement = (
                select(CuentaEstudiante)
                .options(selectinload(CuentaEstudiante.estudiante))
                .where(CuentaEstudiante.carnet == carnet)
            )
            account = db.scalar(statement)
            if account is None:
                raise ErrorAutenticacion(
                    "No existe una cuenta vinculada a ese carnet. Si administración "
                    "ya registró tu perfil, debe habilitar tu acceso al portal."
                )
            if not account.estudiante.activo:
                raise ErrorAutenticacion(
                    "La cuenta está desactivada. Contacta a administración."
                )
            if not _verify_password(password, account.password_hash):
                raise ErrorAutenticacion("Carnet o contraseña incorrectos.")
            return account.estudiante_id

    def autenticar_docente(self, correo: str, password: str) -> int:
        correo = validar_correo(correo)
        if not password:
            raise ErrorAutenticacion("Escribe tu contraseña.")

        with session_scope() as db:
            statement = (
                select(CuentaDocente)
                .options(selectinload(CuentaDocente.docente))
                .join(CuentaDocente.docente)
                .where(PerfilDocente.correo == correo)
            )
            account = db.scalar(statement)
            if account is None:
                raise ErrorAutenticacion(
                    "No existe una cuenta docente vinculada a ese correo."
                )
            if not account.docente.activo:
                raise ErrorAutenticacion(
                    "La cuenta está desactivada. Contacta a administración."
                )
            if not _verify_password(password, account.password_hash):
                raise ErrorAutenticacion("Correo o contraseña incorrectos.")
            return account.docente_id

    def restablecer_contrasena_estudiante(
        self,
        estudiante_id: int,
        password: str,
    ) -> None:
        """Actualiza la contraseña de una cuenta existente de estudiante."""
        _validate_password(password)
        if estudiante_id <= 0:
            raise ErrorAutenticacion("Selecciona un estudiante válido.")

        with session_scope() as db:
            account = db.scalar(
                select(CuentaEstudiante).where(
                    CuentaEstudiante.estudiante_id == estudiante_id
                )
            )
            if account is None:
                raise ErrorAutenticacion(
                    "El estudiante no tiene una cuenta de acceso. "
                    "Habilita su acceso antes de cambiar la contraseña."
                )
            account.password_hash = _hash_password(password)

    def restablecer_contrasena_docente(
        self,
        docente_id: int,
        password: str,
    ) -> None:
        """Actualiza la contraseña de una cuenta existente de docente."""
        _validate_password(password)
        if docente_id <= 0:
            raise ErrorAutenticacion("Selecciona un docente válido.")

        with session_scope() as db:
            account = db.scalar(
                select(CuentaDocente).where(CuentaDocente.docente_id == docente_id)
            )
            if account is None:
                raise ErrorAutenticacion(
                    "El docente no tiene una cuenta de acceso."
                )
            account.password_hash = _hash_password(password)

    def habilitar_acceso(
        self,
        estudiante_id: int,
        carnet: str,
        password: str,
    ) -> None:
        """Crea credenciales para un perfil académico existente sin cuenta."""
        carnet = _validate_carnet(carnet)
        _validate_password(password)

        try:
            with session_scope() as db:
                student = db.scalar(
                    select(Estudiante)
                    .options(selectinload(Estudiante.cuenta))
                    .where(Estudiante.id == estudiante_id)
                )
                if student is None:
                    raise ErrorAutenticacion("El estudiante seleccionado ya no existe.")
                if not student.activo:
                    raise ErrorAutenticacion(
                        "No se puede habilitar el acceso de un estudiante desactivado."
                    )
                if student.cuenta is not None:
                    raise ErrorAutenticacion(
                        "El estudiante ya tiene una cuenta de acceso."
                    )
                student.cuenta = CuentaEstudiante(
                    carnet=carnet,
                    password_hash=_hash_password(password),
                )
                db.flush()
        except IntegrityError as exc:
            logger.info("No se pudo habilitar el acceso por un carnet duplicado.")
            raise ErrorAutenticacion(
                "Ese carnet ya está asociado a otra cuenta."
            ) from exc
