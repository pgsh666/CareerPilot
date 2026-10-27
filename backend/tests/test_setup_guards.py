import importlib.util
from pathlib import Path

import pytest


def load_setup(tmp_path):
    source = Path(__file__).resolve().parents[1] / "setup_mysql.py"
    spec = importlib.util.spec_from_file_location("mysql_setup_for_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BACKEND = tmp_path
    return module


def test_missing_env_prevents_database_changes(tmp_path, monkeypatch):
    import pymysql
    module = load_setup(tmp_path)
    monkeypatch.setattr(pymysql, "connect", lambda **_: pytest.fail("must not connect"))
    with pytest.raises(SystemExit, match="Nothing changed"):
        module.main()


def test_existing_config_never_overwritten(tmp_path, monkeypatch):
    import pymysql
    original = "CAREERPILOT_DATABASE_URL=mysql+pymysql://existing:unchanged@127.0.0.1/existing\n"
    (tmp_path / ".env").write_text(original, encoding="utf-8")
    module = load_setup(tmp_path)
    monkeypatch.setattr(pymysql, "connect", lambda **_: pytest.fail("must not connect"))
    with pytest.raises(SystemExit, match="Nothing changed"):
        module.main()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == original


def test_existing_database_prevents_any_ddl(tmp_path, monkeypatch):
    import pymysql
    (tmp_path / ".env").write_text("CAREERPILOT_SECRET_KEY=unchanged\n", encoding="utf-8")
    module = load_setup(tmp_path)
    queries = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def cursor(self):
            return self

        def execute(self, statement, *args):
            queries.append(statement)

        def fetchone(self):
            return {"Database": "careerpilot"}

    monkeypatch.setattr(pymysql, "connect", lambda **_: Connection())
    monkeypatch.setattr("builtins.input", lambda _: "root")
    monkeypatch.setattr("getpass.getpass", lambda _: "local-admin-secret")
    with pytest.raises(SystemExit, match="Nothing changed"):
        module.main()
    assert queries == ["SHOW DATABASES LIKE 'careerpilot'"]
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "CAREERPILOT_SECRET_KEY=unchanged\n"


def existing_connection(monkeypatch, *, tables=(), users=(), databases=("careerpilot",)):
    import pymysql
    queries = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def cursor(self):
            return self

        def execute(self, statement, params=()):
            self.statement, self.params = statement, params
            queries.append((statement, params))

        def fetchone(self):
            if self.statement.startswith("SHOW DATABASES"):
                return {"Database": "careerpilot"}
            if self.statement.startswith("SELECT SCHEMA_NAME") and self.params[0] in databases:
                return {"SCHEMA_NAME": self.params[0]}
            if self.statement.startswith("SELECT User") and self.params[0] in users:
                return {"User": self.params[0], "Host": "localhost"}
            return None

        def fetchall(self):
            return [{"TABLE_NAME": name} for name in tables]

    monkeypatch.setattr(pymysql, "connect", lambda **_: Connection())
    monkeypatch.setattr("builtins.input", lambda _: "root")
    monkeypatch.setattr("getpass.getpass", lambda _: "local-admin-secret")
    monkeypatch.setattr("secrets.token_urlsafe", lambda _: "project-only-test-password")
    return queries


@pytest.mark.parametrize("occupied", [False, True])
def test_explicit_empty_database_reuse_preserves_database_and_accounts(tmp_path, monkeypatch, capsys, occupied):
    env = tmp_path / ".env"
    env.write_text("CAREERPILOT_SECRET_KEY=unchanged\n", encoding="utf-8")
    module = load_setup(tmp_path)
    queries = existing_connection(monkeypatch, users=["careerpilot"] if occupied else [])
    module.main(use_existing=True)
    sql = "\n".join(statement for statement, _ in queries)
    assert "CREATE DATABASE" not in sql and "ALTER" not in sql.split("GRANT")[0]
    assert "DROP TABLE" not in sql and "ALTER USER" not in sql
    account = "careerpilot_backend" if occupied else "careerpilot"
    create = next(params for statement, params in queries if statement.startswith("CREATE USER"))
    assert create[0] == account
    content = env.read_text(encoding="utf-8")
    assert f"//{account}:project-only-test-password@" in content
    assert "local-admin-secret" not in content
    output = capsys.readouterr().out
    assert "SUCCESS" in output and "project-only-test-password" not in output


def test_nonempty_existing_database_only_reports_metadata(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    original = "CAREERPILOT_SECRET_KEY=unchanged\n"
    env.write_text(original, encoding="utf-8")
    module = load_setup(tmp_path)
    queries = existing_connection(monkeypatch, tables=["legacy_projects"])
    with pytest.raises(SystemExit, match="legacy_projects.*Nothing changed"):
        module.main(use_existing=True)
    assert all(statement.startswith(("SELECT", "SHOW")) for statement, _ in queries)
    assert env.read_text(encoding="utf-8") == original


def test_both_existing_accounts_not_reset(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    original = "CAREERPILOT_SECRET_KEY=unchanged\n"
    env.write_text(original, encoding="utf-8")
    module = load_setup(tmp_path)
    queries = existing_connection(monkeypatch, users=["careerpilot", "careerpilot_backend"])
    with pytest.raises(SystemExit, match="Both project account names already exist"):
        module.main(use_existing=True)
    assert all(statement.startswith(("SELECT", "SHOW")) for statement, _ in queries)
    assert env.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("occupied", [False, True])
def test_new_database_avoids_existing_tables_databases_and_accounts(tmp_path, monkeypatch, capsys, occupied):
    env = tmp_path / ".env"
    env.write_text("CAREERPILOT_SECRET_KEY=unchanged\n", encoding="utf-8")
    module = load_setup(tmp_path)
    databases = ["careerpilot", "careerpilot_app"] if occupied else ["careerpilot"]
    users = ["careerpilot_app_2"] if occupied else []
    queries = existing_connection(
        monkeypatch, tables=["users", "auth_sessions", "interviews", "drills", "projects"],
        databases=databases, users=users,
    )
    module.main(new_database=True)
    expected = "careerpilot_app_3" if occupied else "careerpilot_app"
    writes = [(statement, params) for statement, params in queries
              if not statement.startswith(("SHOW", "SELECT"))]
    assert len(writes) == 3
    assert writes[0][0].startswith(f"CREATE DATABASE `{expected}` ")
    assert writes[1][1][0] == expected
    assert f"ON `{expected}`.*" in writes[2][0]
    assert all("ON `careerpilot`." not in statement for statement, _ in writes)
    content = env.read_text(encoding="utf-8")
    assert f"/{expected}?charset=utf8mb4" in content
    assert "local-admin-secret" not in content
    output = capsys.readouterr().out
    assert expected in output and "SUCCESS" in output
    assert "project-only-test-password" not in output


def test_exhausted_names_and_conflicting_modes_do_not_change_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    original = "CAREERPILOT_SECRET_KEY=unchanged\n"
    env.write_text(original, encoding="utf-8")
    module = load_setup(tmp_path)
    databases = ["careerpilot_app"] + [f"careerpilot_app_{n}" for n in range(2, 101)]
    queries = existing_connection(monkeypatch, databases=databases)
    with pytest.raises(SystemExit, match="No unused project database"):
        module.main(new_database=True)
    assert all(statement.startswith(("SELECT", "SHOW")) for statement, _ in queries)
    assert env.read_text(encoding="utf-8") == original
    with pytest.raises(SystemExit, match="Choose only one"):
        module.main(use_existing=True, new_database=True)

