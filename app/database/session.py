from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.invoice_config import LOCAL_ROOT

# 保证 metadata 包含全部表
from app.database import models as _models  # noqa: F401


def default_sqlite_path() -> Path:

    return LOCAL_ROOT / "data" / "shipment_tracking.sqlite"


def default_database_url() -> str:

    path = default_sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(url: str | None = None) -> Engine:

    database_url = url or default_database_url()
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:

    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_schema(engine: Engine) -> None:

    Base.metadata.create_all(engine)
