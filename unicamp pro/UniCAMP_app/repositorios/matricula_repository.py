"""Consultas y escrituras de matrículas dentro de una sesión externa."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from modelos.entidades import Grupo, Matricula, MatriculaDetail
from servicios.periodos import variantes_periodo


class MatriculaRepository:
    """Repositorio que no confirma transacciones por cuenta propia."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_for_student_period(self, estudiante_id: int, periodo: str) -> Matricula | None:
        statement = (
            select(Matricula)
            .options(selectinload(Matricula.detalles).selectinload(MatriculaDetail.grupo))
            .where(
                Matricula.estudiante_id == estudiante_id,
                Matricula.periodo.in_(variantes_periodo(periodo)),
            )
        )
        return self.db.scalar(statement)

    def lock_groups(self, grupo_ids: list[int]) -> list[Grupo]:
        statement = (
            select(Grupo)
            .where(Grupo.id.in_(grupo_ids))
            .order_by(Grupo.id)
            .with_for_update()
        )
        return list(self.db.scalars(statement))

    def enrollment_counts(self, grupo_ids: list[int]) -> dict[int, int]:
        statement = (
            select(MatriculaDetail.grupo_id, func.count(MatriculaDetail.id))
            .join(MatriculaDetail.matricula)
            .where(
                MatriculaDetail.grupo_id.in_(grupo_ids),
                Matricula.estado != "cancelada",
                MatriculaDetail.estado == "inscrita",
            )
            .group_by(MatriculaDetail.grupo_id)
        )
        return {grupo_id: count for grupo_id, count in self.db.execute(statement)}

    def create(self, matricula: Matricula) -> Matricula:
        self.db.add(matricula)
        self.db.flush()
        return matricula
