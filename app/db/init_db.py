from sqlalchemy import inspect
from sqlmodel import SQLModel

from app.db import models  # noqa: F401
from app.db.session import engine, reset_sqlite_database, sqlite_database_path


def _sqlite_schema_mismatch() -> bool:
    if sqlite_database_path() is None:
        return False
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        expected_columns = set(table.columns.keys())
        if not expected_columns.issubset(existing_columns):
            return True
    return False


def create_db_and_tables() -> None:
    if _sqlite_schema_mismatch():
        reset_sqlite_database()
    SQLModel.metadata.create_all(engine)
