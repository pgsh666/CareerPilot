"""Run with the established careerpilot Python. Dependencies are local to this project."""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND / ".deps"))
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-env")
    subparsers.add_parser("migrate")
    server = subparsers.add_parser("serve")
    server.add_argument("--port", type=int, default=8000)
    subparsers.add_parser("test")
    subparsers.add_parser("lint")
    subparsers.add_parser("create-admin")
    subparsers.add_parser("model-status")
    subparsers.add_parser("model-smoke")
    subparsers.add_parser("maintenance")
    subparsers.add_parser("backup")
    restore_cmd = subparsers.add_parser("restore")
    restore_cmd.add_argument("backup_file", type=Path)
    restore_cmd.add_argument("--confirm-database", required=True)
    reconcile = subparsers.add_parser("reconcile-fee")
    reconcile.add_argument("spend_id")
    reconcile.add_argument("--amount", required=True, help="Supplier-confirmed CNY, zero only with evidence")
    reconcile.add_argument("--evidence", required=True, help="Nonpersonal supplier reference or evidence file SHA256")
    pricing = subparsers.add_parser("verify-pricing")
    pricing.add_argument("--hit", required=True)
    pricing.add_argument("--miss", required=True)
    pricing.add_argument("--output", required=True)
    pricing.add_argument("--date", required=True)
    args = parser.parse_args()
    if args.command == "init-env":
        target = BACKEND / ".env"
        if target.exists():
            parser.error("backend/.env already exists; it was not overwritten")
        source = (BACKEND / ".env.example").read_text(encoding="utf-8")
        source = source.replace("REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS", secrets.token_urlsafe(48))
        # Keep MySQL unconfigured until the user supplies a dedicated project account.
        source = "\n".join("# " + line if line.startswith("CAREERPILOT_DATABASE_URL=") else line
                           for line in source.splitlines()) + "\n"
        with target.open("x", encoding="utf-8") as handle:
            handle.write(source)
        print("Created backend/.env with a random secret; configure the dedicated MySQL account locally.")
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, proxy_headers=False)
    elif args.command == "migrate":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    elif args.command == "test":
        import pytest
        raise SystemExit(pytest.main([str(BACKEND / "tests"), "-q"]))
    elif args.command == "lint":
        import subprocess
        executable = BACKEND / ".deps" / "bin" / "ruff.exe"
        if not executable.exists():
            executable = BACKEND / ".deps" / "Scripts" / "ruff.exe"
        raise SystemExit(subprocess.call([str(executable), "check", str(BACKEND)]))
    elif args.command in {"model-status", "model-smoke"}:
        from app.errors import ApiError
        from app.model_smoke import run
        try:
            run(status_only=args.command == "model-status")
        except ApiError as error:
            print(f"{error.code}: {error.message}")
            raise SystemExit(1) from None
        except Exception:
            print("MODEL_CHECK_FAILED: 检查未完成，未自动重试；可运行model-status查看额度状态。")
            raise SystemExit(1) from None
    elif args.command in {"maintenance", "backup", "restore", "reconcile-fee", "verify-pricing"}:
        import json
        from decimal import Decimal

        from app.config import Settings
        from app.db import make_engine
        from app.errors import ApiError
        from app.maintenance import backup, cleanup, restore
        settings = Settings()
        engine = make_engine(settings)
        if engine is None:
            parser.error("Configure the dedicated project database first")
        try:
            if args.command == "backup":
                result = backup(engine, settings)
            elif args.command == "maintenance":
                result = cleanup(engine, settings)
            elif args.command == "restore":
                import socket
                for port in (8000, 8001):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=1):
                            parser.error(f"Stop the local CareerPilot API/QA before restoring (port {port} is in use)")
                    except OSError:
                        pass
                print("Target database: " + str(engine.url.database))
                print("Backup: " + str(args.backup_file.resolve()))
                if input("This overwrites business data after backing it up. Type RESTORE to continue: ").strip() != "RESTORE":
                    parser.error("Restore cancelled; nothing overwritten")
                result = restore(engine, settings, args.backup_file, confirmed_database=args.confirm_database)
            elif args.command == "reconcile-fee":
                from app.model_budget import BudgetGuard
                amount = Decimal(args.amount)
                if not amount.is_finite() or amount < 0 or amount * 1_000_000 != (amount * 1_000_000).to_integral_value():
                    parser.error("Amount must be nonnegative CNY with at most 6 decimal places")
                print("Register supplier evidence only; zero must mean confirmed no charge.")
                result = BudgetGuard(engine, settings).reconcile(args.spend_id, amount_micro=int(amount * 1_000_000), evidence_ref=args.evidence)
            else:
                from app.model_pricing import confirm
                result = confirm(settings, hit=args.hit, miss=args.miss, output=args.output, verified_on=args.date)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except ApiError as error:
            print(error.code + ": " + error.message)
            raise SystemExit(1) from None
    elif args.command == "create-admin":
        from email_validator import validate_email
        from sqlalchemy import select

        from app.config import Settings
        from app.db import make_engine, session_factory
        from app.models import User
        from app.security import password_hasher
        settings = Settings()
        engine = make_engine(settings)
        if engine is None:
            parser.error("Configure the project database and migrate first")
        address = validate_email(input("Admin email: ").strip(), check_deliverability=False).normalized.lower()
        password = getpass.getpass("Admin password (at least 8 characters): ")
        if len(password) < 8 or len(password) > 128:
            parser.error("Admin password must be 8-128 characters")
        if password != getpass.getpass("Repeat password: "):
            parser.error("Passwords do not match")
        with session_factory(engine)() as db:
            if db.scalar(select(User).where(User.email == address)):
                parser.error("Email already exists; no account or role was changed")
            db.add(User(email=address, name="管理员", role="admin", email_verified=True,
                        password_hash=password_hasher.hash(password)))
            db.commit()
        print("Admin created locally. No default or public administrator registration exists.")


if __name__ == "__main__":
    main()
