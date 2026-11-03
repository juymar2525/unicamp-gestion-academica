"""Configuración SQLAlchemy y administración segura de sesiones MySQL."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def _database_url() -> URL:
    """Construye la URL sin exponer credenciales en logs o archivos."""
    return URL.create(
        drivername="mysql+mysqlconnector",
        username=os.getenv("UNICAMP_DB_USER", "root"),
        password=os.getenv("UNICAMP_DB_PASSWORD", ""),
        host=os.getenv("UNICAMP_DB_HOST", "localhost"),
        port=int(os.getenv("UNICAMP_DB_PORT", "3306")),
        database=os.getenv("UNICAMP_DB_NAME", "unicamp_horarios"),
        query={"charset": "utf8mb4"},
    )


engine: Engine = create_engine(
    _database_url(),
    isolation_level="READ COMMITTED",
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Entrega una sesión transaccional y garantiza rollback/cierre."""
    db = SessionLocal()
    try:
        with db.begin():
            yield db
    except Exception:
        db.rollback()
        logger.exception("Falló una transacción de base de datos.")
        raise
    finally:
        db.close()


def check_database_connection() -> None:
    """Comprueba la conexión y propaga errores de infraestructura."""
    connection = None
    try:
        connection = engine.connect()
        connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("No fue posible conectar con la base de datos.")
        raise
    finally:
        if connection is not None:
            connection.close()
