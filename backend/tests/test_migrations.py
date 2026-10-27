from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def migration_config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_initial_migration_and_orm_schema_agree(tmp_path, monkeypatch):
    from app.db import Base
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("CAREERPILOT_ENVIRONMENT", "test")
    monkeypatch.setenv("CAREERPILOT_DATABASE_URL", url)
    command.upgrade(migration_config(), "head")
    engine = create_engine(url)
    schema = inspect(engine)
    assert set(schema.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    for table_name, table in Base.metadata.tables.items():
        assert {column["name"] for column in schema.get_columns(table_name)} == set(table.columns.keys())
    assert schema.get_unique_constraints("users")[0]["column_names"] == ["email"]
    assert schema.get_foreign_keys("auth_sessions")[0]["referred_table"] == "users"
    engine.dispose()


def test_migration_generates_mysql_sql_without_connecting(monkeypatch):
    monkeypatch.setenv("CAREERPILOT_ENVIRONMENT", "test")
    monkeypatch.setenv("CAREERPILOT_DATABASE_URL", "mysql+pymysql://migration_check:unused@127.0.0.1/migration_check")
    output = StringIO()
    config = migration_config()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE users" in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id)" in sql
    assert "UNIQUE (token_hash)" in sql

