import os
import subprocess

from sqlalchemy import create_engine, inspect


def test_migration_roundtrip(tmp_path):
    url = f"sqlite:///{tmp_path}/migrated.db"
    env = {**os.environ, "DATABASE_URL": url}

    def run(*args):
        subprocess.run([".venv/bin/alembic", *args], env=env, check=True, capture_output=True)

    run("upgrade", "head")
    engine = create_engine(url)
    assert "creation_operations" in inspect(engine).get_table_names()
    constraints = inspect(engine).get_unique_constraints("creation_operations")
    assert {tuple(c["column_names"]) for c in constraints} == {("request_key",), ("alias",)}
    run("check")
    run("downgrade", "base")
    assert "creation_operations" not in inspect(engine).get_table_names()
    run("upgrade", "head")
    engine.dispose()
