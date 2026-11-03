"""Entidades SQLAlchemy para gestión académica y atención de estudiantes."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Time,
    UniqueConstraint,
    Column,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarativa para todas las entidades persistentes."""


carrera_asignaturas = Table(
    "carrera_asignaturas",
    Base.metadata,
    Column("carrera_id", ForeignKey("carreras.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "asignatura_id",
        ForeignKey("asignaturas.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

asignatura_prerrequisitos = Table(
    "asignatura_prerrequisitos",
    Base.metadata,
    Column(
        "asignatura_id",
        ForeignKey("asignaturas.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "prerrequisito_id",
        ForeignKey("asignaturas.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Carrera(Base):
    """Programa académico con su malla curricular."""

    __tablename__ = "carreras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    estudiantes: Mapped[list[Estudiante]] = relationship(back_populates="carrera")
    docentes: Mapped[list[PerfilDocente]] = relationship(back_populates="carrera")
    asignaturas: Mapped[list[Asignatura]] = relationship(
        secondary=carrera_asignaturas,
        back_populates="carreras",
    )


class Estudiante(Base):
    """Persona inscrita como estudiante de nuevo ingreso o reingreso."""

    __tablename__ = "estudiantes"
    __table_args__ = (
        CheckConstraint(
            "tipo_ingreso IN ('nuevo_ingreso', 'reingreso')",
            name="ck_estudiante_tipo_ingreso",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False)
    correo: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tipo_ingreso: Mapped[str] = mapped_column(String(20), nullable=False)
    carrera_id: Mapped[int] = mapped_column(ForeignKey("carreras.id"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_registro: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)

    carrera: Mapped[Carrera] = relationship(back_populates="estudiantes")
    matriculas: Mapped[list[Matricula]] = relationship(
        back_populates="estudiante",
        cascade="all, delete-orphan",
    )
    documentos: Mapped[list[DocumentoChecklist]] = relationship(
        back_populates="estudiante",
        cascade="all, delete-orphan",
    )
    cuenta: Mapped[CuentaEstudiante | None] = relationship(
        back_populates="estudiante",
        cascade="all, delete-orphan",
        uselist=False,
    )


class CuentaEstudiante(Base):
    """Credenciales de acceso separadas del perfil académico."""

    __tablename__ = "cuentas_estudiante"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estudiante_id: Mapped[int] = mapped_column(
        ForeignKey("estudiantes.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    carnet: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    estudiante: Mapped[Estudiante] = relationship(back_populates="cuenta")


class PerfilDocente(Base):
    """Persona docente asociada a una carrera académica."""

    __tablename__ = "perfiles_docente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False)
    correo: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    carrera_id: Mapped[int] = mapped_column(ForeignKey("carreras.id"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    carrera: Mapped[Carrera] = relationship(back_populates="docentes")
    cuenta: Mapped[CuentaDocente | None] = relationship(
        back_populates="docente",
        cascade="all, delete-orphan",
        uselist=False,
    )
    grupos: Mapped[list[Grupo]] = relationship(back_populates="docente")


class CuentaDocente(Base):
    """Credenciales de acceso del docente, separadas de su perfil."""

    __tablename__ = "cuentas_docente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    docente_id: Mapped[int] = mapped_column(
        ForeignKey("perfiles_docente.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    docente: Mapped[PerfilDocente] = relationship(back_populates="cuenta")


class Asignatura(Base):
    """Asignatura con créditos y relaciones de prerrequisitos."""

    __tablename__ = "asignaturas"
    __table_args__ = (
        CheckConstraint("creditos > 0", name="ck_asignatura_creditos_positivos"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    creditos: Mapped[int] = mapped_column(Integer, nullable=False)

    carreras: Mapped[list[Carrera]] = relationship(
        secondary=carrera_asignaturas,
        back_populates="asignaturas",
    )
    prerrequisitos: Mapped[list[Asignatura]] = relationship(
        "Asignatura",
        secondary=asignatura_prerrequisitos,
        primaryjoin=id == asignatura_prerrequisitos.c.asignatura_id,
        secondaryjoin=id == asignatura_prerrequisitos.c.prerrequisito_id,
        back_populates="requerida_por",
    )
    requerida_por: Mapped[list[Asignatura]] = relationship(
        "Asignatura",
        secondary=asignatura_prerrequisitos,
        primaryjoin=id == asignatura_prerrequisitos.c.prerrequisito_id,
        secondaryjoin=id == asignatura_prerrequisitos.c.asignatura_id,
        back_populates="prerrequisitos",
    )
    grupos: Mapped[list[Grupo]] = relationship(back_populates="asignatura")


class Grupo(Base):
    """Oferta de una asignatura con horario, aula y capacidad."""

    __tablename__ = "grupos"
    __table_args__ = (
        CheckConstraint("cupo_maximo > 0", name="ck_grupo_cupo_positivo"),
        CheckConstraint("hora_fin > hora_inicio", name="ck_grupo_horas_validas"),
        UniqueConstraint(
            "asignatura_id",
            "periodo",
            "seccion",
            name="uq_grupo_asignatura_periodo_seccion",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asignatura_id: Mapped[int] = mapped_column(
        ForeignKey("asignaturas.id"),
        nullable=False,
        index=True,
    )
    docente_id: Mapped[int | None] = mapped_column(
        ForeignKey("perfiles_docente.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    periodo: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    seccion: Mapped[str] = mapped_column(String(12), nullable=False)
    dia: Mapped[str] = mapped_column(String(12), nullable=False)
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time] = mapped_column(Time, nullable=False)
    cupo_maximo: Mapped[int] = mapped_column(Integer, nullable=False)
    edificio: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    aula: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    pabellon: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    ventanilla: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    asignatura: Mapped[Asignatura] = relationship(back_populates="grupos")
    docente: Mapped[PerfilDocente | None] = relationship(back_populates="grupos")
    detalles_matricula: Mapped[list[MatriculaDetail]] = relationship(
        back_populates="grupo",
        cascade="all, delete-orphan",
    )


class Matricula(Base):
    """Solicitud transaccional de matrícula de un estudiante en un período."""

    __tablename__ = "matriculas"
    __table_args__ = (
        UniqueConstraint("estudiante_id", "periodo", name="uq_matricula_estudiante_periodo"),
        CheckConstraint(
            "estado IN ('pendiente', 'confirmada', 'cancelada')",
            name="ck_matricula_estado",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estudiante_id: Mapped[int] = mapped_column(
        ForeignKey("estudiantes.id"),
        nullable=False,
        index=True,
    )
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False)
    creada_en: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    estudiante: Mapped[Estudiante] = relationship(back_populates="matriculas")
    detalles: Mapped[list[MatriculaDetail]] = relationship(
        back_populates="matricula",
        cascade="all, delete-orphan",
    )


class MatriculaDetail(Base):
    """Asignatura/grupo seleccionado dentro de una matrícula."""

    __tablename__ = "matricula_details"
    __table_args__ = (
        UniqueConstraint("matricula_id", "grupo_id", name="uq_matricula_grupo"),
        CheckConstraint(
            "estado IN ('inscrita', 'aprobada', 'reprobada', 'retirada')",
            name="ck_detalle_matricula_estado",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    matricula_id: Mapped[int] = mapped_column(
        ForeignKey("matriculas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grupo_id: Mapped[int] = mapped_column(ForeignKey("grupos.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="inscrita", nullable=False)
    calificacion: Mapped[int | None] = mapped_column(Integer)

    matricula: Mapped[Matricula] = relationship(back_populates="detalles")
    grupo: Mapped[Grupo] = relationship(back_populates="detalles_matricula")


class DocumentoChecklist(Base):
    """Documento solicitado y su estado de recepción/verificación."""

    __tablename__ = "documentos_checklist"
    __table_args__ = (
        UniqueConstraint("estudiante_id", "tipo_documento", name="uq_documento_estudiante_tipo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estudiante_id: Mapped[int] = mapped_column(
        ForeignKey("estudiantes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo_documento: Mapped[str] = mapped_column(String(80), nullable=False)
    recibido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recibido_en: Mapped[datetime | None] = mapped_column(DateTime)

    estudiante: Mapped[Estudiante] = relationship(back_populates="documentos")
