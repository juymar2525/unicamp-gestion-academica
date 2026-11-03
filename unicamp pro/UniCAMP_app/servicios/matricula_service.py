"""Reglas de matrícula, prerrequisitos, créditos, cupos y horarios."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config.database import session_scope
from modelos.entidades import (
    Asignatura,
    Estudiante,
    Grupo,
    Matricula,
    MatriculaDetail,
)
from repositorios.matricula_repository import MatriculaRepository
from servicios.periodos import normalizar_periodo

logger = logging.getLogger(__name__)


class MatriculaError(ValueError):
    """Error funcional seguro para presentar al usuario."""


class CupoAgotadoError(MatriculaError):
    """El grupo no tiene vacantes disponibles."""


class ChoqueHorarioError(MatriculaError):
    """La selección incluye dos grupos que se superponen."""


class PrerrequisitoPendienteError(MatriculaError):
    """El estudiante no ha aprobado todos los prerrequisitos."""


@dataclass(frozen=True)
class MatriculaResultado:
    matricula_id: int
    grupos_inscritos: int
    creditos_totales: int


class MatriculaService:
    """Coordina validaciones y escritura atómica de una matrícula."""

    def inscribir(
        self,
        estudiante_id: int,
        grupo_ids: list[int],
        periodo: str,
        *,
        creditos_minimos: int = 0,
        creditos_maximos: int = 30,
    ) -> MatriculaResultado:
        if not grupo_ids:
            raise MatriculaError("Selecciona al menos un grupo para continuar.")
        periodo = normalizar_periodo(periodo)
        if not periodo:
            raise MatriculaError("Indica el período académico.")
        if len(set(grupo_ids)) != len(grupo_ids):
            raise MatriculaError("La selección contiene grupos duplicados.")
        if creditos_minimos < 0 or creditos_maximos < creditos_minimos:
            raise MatriculaError("El rango de créditos configurado no es válido.")

        with session_scope() as db:
            repository = MatriculaRepository(db)
            estudiante = db.get(Estudiante, estudiante_id)
            if estudiante is None or not estudiante.activo:
                raise MatriculaError("El estudiante no existe o no está activo.")

            grupos = repository.lock_groups(sorted(grupo_ids))
            if len(grupos) != len(grupo_ids):
                raise MatriculaError("Uno o más grupos seleccionados ya no existen.")
            if any(
                normalizar_periodo(grupo.periodo) != periodo for grupo in grupos
            ):
                raise MatriculaError("Todos los grupos deben pertenecer al período solicitado.")

            matricula = repository.get_for_student_period(estudiante_id, periodo)
            if matricula is not None and matricula.estado != "pendiente":
                raise MatriculaError("Ya existe una matrícula confirmada para este período.")
            existing_details = (
                [
                    detail
                    for detail in matricula.detalles
                    if detail.estado == "inscrita"
                ]
                if matricula is not None
                else []
            )
            existing_groups = [detail.grupo for detail in existing_details]
            if {group.id for group in existing_groups}.intersection(grupo_ids):
                raise MatriculaError("Uno o más grupos ya forman parte de esta matrícula.")
            combined_groups = grupos + existing_groups
            assignment_ids = [group.asignatura_id for group in combined_groups]
            if len(set(assignment_ids)) != len(assignment_ids):
                raise MatriculaError(
                    "La matrícula no puede incluir dos grupos de la misma asignatura."
                )

            asignaturas = self._load_asignaturas(db, combined_groups)
            if any(
                estudiante.carrera_id not in {carrera.id for carrera in asignatura.carreras}
                for asignatura in asignaturas
            ):
                raise MatriculaError(
                    "La selección incluye asignaturas fuera de la malla de la carrera."
                )
            asignaturas_por_id = {asignatura.id: asignatura for asignatura in asignaturas}
            total_creditos = sum(
                asignaturas_por_id[grupo.asignatura_id].creditos
                for grupo in combined_groups
            )
            if not creditos_minimos <= total_creditos <= creditos_maximos:
                raise MatriculaError(
                    f"La carga debe estar entre {creditos_minimos} y "
                    f"{creditos_maximos} créditos; la selección suma {total_creditos}."
                )

            self._validate_prerequisites(db, estudiante_id, asignaturas)
            self._validate_schedule_conflicts(combined_groups)

            if matricula is None:
                matricula = Matricula(
                    estudiante_id=estudiante_id,
                    periodo=periodo,
                    estado="pendiente",
                )
                repository.create(matricula)

            counts = repository.enrollment_counts(grupo_ids)
            for grupo in grupos:
                if counts.get(grupo.id, 0) >= grupo.cupo_maximo:
                    raise CupoAgotadoError(
                        f"El grupo {grupo.seccion} de {grupo.asignatura.nombre} no tiene cupos."
                    )

            matricula.detalles.extend(
                MatriculaDetail(grupo=grupo, estado="inscrita") for grupo in grupos
            )
            db.flush()
            return MatriculaResultado(
                matricula_id=matricula.id,
                grupos_inscritos=len(grupo_ids),
                creditos_totales=total_creditos,
            )

    @staticmethod
    def _load_asignaturas(db, grupos: list[Grupo]) -> list[Asignatura]:
        asignatura_ids = {grupo.asignatura_id for grupo in grupos}
        statement = (
            select(Asignatura)
            .options(
                selectinload(Asignatura.prerrequisitos),
                selectinload(Asignatura.carreras),
            )
            .where(Asignatura.id.in_(asignatura_ids))
        )
        return list(db.scalars(statement))

    @staticmethod
    def _validate_prerequisites(
        db,
        estudiante_id: int,
        asignaturas: list[Asignatura],
    ) -> None:
        prerequisite_ids = {
            prerequisite.id
            for asignatura in asignaturas
            for prerequisite in asignatura.prerrequisitos
        }
        if not prerequisite_ids:
            return

        passed_ids = set(
            db.scalars(
                select(Grupo.asignatura_id)
                .join(MatriculaDetail.grupo)
                .join(MatriculaDetail.matricula)
                .where(
                    Matricula.estudiante_id == estudiante_id,
                    Matricula.estado == "confirmada",
                    MatriculaDetail.estado == "aprobada",
                    Grupo.asignatura_id.in_(prerequisite_ids),
                )
            )
        )
        missing = prerequisite_ids - passed_ids
        if missing:
            raise PrerrequisitoPendienteError(
                "No se puede inscribir: hay asignaturas prerrequisito pendientes."
            )

    @staticmethod
    def _validate_schedule_conflicts(grupos: list[Grupo]) -> None:
        for index, first in enumerate(grupos):
            for second in grupos[index + 1 :]:
                overlaps = (
                    first.dia == second.dia
                    and first.hora_inicio < second.hora_fin
                    and first.hora_fin > second.hora_inicio
                )
                if overlaps:
                    raise ChoqueHorarioError(
                        f"Los grupos {first.seccion} y {second.seccion} se "
                        f"superponen el {first.dia}."
                    )
