"""Interactive local-only MySQL bootstrap; never resets existing credentials or data."""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND / ".deps"))


def choose_new_database(cursor):
    """Choose an unused fixed-prefix database/account pair without modifying existing objects."""
    for number in range(1, 101):
        candidate = "careerpilot_app" if number == 1 else f"careerpilot_app_{number}"
        cursor.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            (candidate,),
        )
        if cursor.fetchone():
            continue
        cursor.execute("SELECT User, Host FROM mysql.user WHERE User = %s", (candidate,))
        if cursor.fetchone():
            continue
        return candidate
    raise SystemExit("No unused project database/account name found. Nothing changed.")


def main(*, use_existing=False, new_database=False):
    import pymysql
    from pymysql.cursors import DictCursor

    if use_existing and new_database:
        raise SystemExit("Choose only one database setup mode. Nothing changed.")
    env_path = BACKEND / ".env"
    if not env_path.exists():
        raise SystemExit("Run manage.py init-env before this script. Nothing changed.")
    text = env_path.read_text(encoding="utf-8")
    if any(line.lstrip().startswith("CAREERPILOT_DATABASE_URL=") for line in text.splitlines()):
        raise SystemExit("backend/.env already has a database URL. Nothing changed.")
    administrator = input("Local MySQL administrator [root]: ").strip() or "root"
    admin_password = getpass.getpass("MySQL administrator password (not saved): ")
    connection = pymysql.connect(
        host="127.0.0.1", port=3306, user=administrator, password=admin_password,
        charset="utf8mb4", cursorclass=DictCursor, autocommit=True, connect_timeout=5,
    )
    with connection:
        with connection.cursor() as cursor:
            database = choose_new_database(cursor) if new_database else "careerpilot"
            if new_database:
                database_exists = False
            else:
                cursor.execute("SHOW DATABASES LIKE 'careerpilot'")
                database_exists = bool(cursor.fetchone())
            if database_exists and not use_existing:
                raise SystemExit("careerpilot database already exists. Nothing changed; configure its project account in backend/.env.")
            if database_exists:
                cursor.execute(
                    "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
                    ("careerpilot",),
                )
                tables = [row["TABLE_NAME"] for row in cursor.fetchall()]
                if tables:
                    raise SystemExit(
                        "Existing careerpilot database contains tables: " + ", ".join(tables)
                        + ". Nothing changed. Review the existing schema before configuring or migrating."
                    )
                print("Existing careerpilot database is empty; it will be reused without changing its settings.")
            account = database
            if not new_database:
                cursor.execute("SELECT User, Host FROM mysql.user WHERE User = %s", (account,))
            if not new_database and cursor.fetchone():
                # Preserve every existing user/password; create a separate project account instead.
                account = "careerpilot_backend"
                cursor.execute("SELECT User, Host FROM mysql.user WHERE User = %s", (account,))
                if cursor.fetchone():
                    raise SystemExit("Both project account names already exist. Nothing changed; configure an existing project's credentials locally.")
            password = secrets.token_urlsafe(32)
            # Save credentials before non-transactional MySQL DDL so partial failures remain recoverable.
            # token_urlsafe uses no URI-reserved characters. No password enters output or arguments.
            with env_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nCAREERPILOT_DATABASE_URL=mysql+pymysql://{account}:{password}@127.0.0.1:3306/{database}?charset=utf8mb4\n")
            # Identifiers are fixed or internally generated, never interpolated user input.
            if not database_exists:
                cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs")
            cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s", (account, password))
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP ON `{database}`.* TO %s@'127.0.0.1'", (account,))
    print(f"Project database: {database}")
    print("SUCCESS: Project database connection saved to backend/.env. A dedicated account was created; existing tables and user credentials were not changed.")


if __name__ == "__main__":
    import pymysql
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--use-existing", action="store_true",
                        help="Allow reuse of an existing empty careerpilot database; never change existing tables")
    mode.add_argument("--new-database", action="store_true",
                      help="Create an unused careerpilot_app database/account; preserve the existing careerpilot database")
    args = parser.parse_args()
    try:
        main(use_existing=args.use_existing, new_database=args.new_database)
    except pymysql.MySQLError as exc:
        # Server messages can contain SQL and credentials; report only the numeric error code.
        raise SystemExit(f"MySQL configuration failed (code {exc.args[0]}). Keep backend/.env for recovery; no existing database was deleted.") from None
