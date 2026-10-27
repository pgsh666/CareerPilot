"""Start the configured Windows development stack without model calls or schema changes."""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SERVICES = ROOT / ".cache" / "services"
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]


class StartupError(Exception):
    pass


def say(message):
    print(message, flush=True)
    with (SERVICES / "startup.log").open("a", encoding="utf-8") as log:
        log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(path, port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status, response.read(100_000).decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read(100_000).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return 0, ""


def api_ready():
    try:
        status, body = http("/health/live", 8000)
        if status != 200 or json.loads(body).get("service") != "careerpilot-backend":
            return False
        status, body = http("/health/ready", 8000)
        return status == 200 and json.loads(body).get("status") == "ready"
    except ValueError:
        return False


def web_ready():
    status, body = http("/", 5173)
    if status != 200 or "CareerPilot" not in body or "/src/main.ts" not in body:
        return False
    status, runtime = http("/src/core/runtime.ts", 5173)
    if status != 200 or "isPreviewMode" not in runtime:
        return False
    if re.search(r'"VITE_PREVIEW_MODE"\s*:\s*"true"', runtime):
        return False
    try:
        status, body = http("/api/v1/auth/me", 5173)
        return status == 401 and json.loads(body).get("error", {}).get("code") == "AUTH_REQUIRED"
    except ValueError:
        return False


def mail_ready(smtp_port):
    try:
        status, body = http("/api/v1/info", 8025)
        info = json.loads(body)
        return status == 200 and "Version" in info and "Messages" in info and port_open(smtp_port)
    except ValueError:
        return False


def locate(preferred, command, description):
    if preferred.is_file():
        return preferred
    found = shutil.which(command)
    if found:
        return Path(found)
    raise StartupError(f"未找到{description}：{preferred}")


def load_settings():
    if not (BACKEND / ".env").is_file():
        raise StartupError("缺少 backend/.env，请按 backend/README.md 完成本机配置。")
    try:
        from sqlalchemy.engine import make_url

        from app.config import Settings
        settings = Settings()
        if not settings.database_url or not settings.secret_key:
            raise StartupError("请先在 backend/.env 配置项目数据库连接和认证密钥。")
        url = make_url(settings.database_url.get_secret_value())
        if settings.environment != "development" or url.host not in {"127.0.0.1", "localhost"}:
            raise StartupError("此启动脚本用于当前本机开发环境，请检查 backend/.env 的环境和数据库地址。")
        if settings.smtp_host not in {"127.0.0.1", "localhost"}:
            raise StartupError("当前邮件配置不是本机Mailpit，请按实际邮件服务方式启动。")
        return settings, url.port or 3306
    except StartupError:
        raise
    except Exception:
        raise StartupError("后端配置或依赖读取失败，请检查 backend/.env 和 backend/.deps。") from None


def database_ready(settings):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.db import make_engine
    engine = make_engine(settings)
    try:
        expected = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            connection.execute(text("SELECT 1 FROM users LIMIT 1"))
        if current != expected:
            raise StartupError("数据库迁移尚未完成，请先运行 backend/manage.py migrate。")
    except StartupError:
        raise
    except Exception:
        raise StartupError("数据库检查失败，请检查MySQL、专用账号配置及数据库迁移；连接密码不会打印。") from None
    finally:
        engine.dispose()


def start_mysql(port, check_only):
    if port_open(port):
        say(f"[就绪] MySQL端口 {port}")
        return
    if check_only:
        raise StartupError(f"MySQL端口 {port} 尚未就绪。")
    say("[启动] MySQL系统服务 MYSQL80…")
    result = subprocess.run(["sc.exe", "start", "MYSQL80"], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=False)
    if result.returncode == 5:
        say("启动MySQL需要管理员权限，请确认Windows授权窗口。")
        # Only service startup is elevated; application processes run as the current user.
        command = ("$mysqlStartProcess = Start-Process -FilePath 'sc.exe' "
                   "-ArgumentList @('start','MYSQL80') -Verb RunAs -WindowStyle Hidden "
                   "-Wait -PassThru -ErrorAction Stop; exit $mysqlStartProcess.ExitCode")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=60, check=False)
    if result.returncode not in {0, 1056}:
        raise StartupError("MySQL未能启动。请检查MYSQL80服务是否存在，或在管理员CMD执行：net start MYSQL80")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if port_open(port):
            say("[就绪] MySQL")
            return
        time.sleep(0.4)
    raise StartupError(f"MySQL服务已收到启动请求，但端口 {port} 尚未就绪。")


def ensure_service(label, title, ports, ready, command, cwd, *, check_only, env=None):
    if ready():
        say(f"[复用] {title}")
        return
    if any(port_open(port) for port in ports):
        raise StartupError(f"{title}的端口 {ports} 已占用，但服务检查未通过。请检查原启动窗口后重试。")
    if check_only:
        raise StartupError(f"{title}尚未启动。")
    if not Path(command[0]).is_file():
        raise StartupError(f"未找到{title}启动程序：{command[0]}")
    say(f"[启动] {title}…")
    with (SERVICES / f"{label}.stdout.log").open("ab") as output, (SERVICES / f"{label}.stderr.log").open("ab") as errors:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=errors, close_fds=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    (SERVICES / f"{label}.pid").write_text(str(process.pid), encoding="ascii")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError(f"{title}启动进程已退出，请查看 {SERVICES / (label + '.stderr.log')}")
        if ready():
            say(f"[就绪] {title}")
            return process
        time.sleep(0.4)
    raise StartupError(f"{title}启动超时，请查看 {SERVICES / (label + '.stderr.log')}")


@contextmanager
def startup_lock():
    import msvcrt
    with (SERVICES / "startup.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description="CareerPilot 本机一键启动")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    parser.add_argument("--check", action="store_true", help="仅检查配置、数据库和服务，不启动进程")
    args = parser.parse_args()
    if os.name != "nt":
        raise StartupError("请在Windows本机运行启动CareerPilot.cmd。")
    SERVICES.mkdir(parents=True, exist_ok=True)
    with startup_lock() as acquired:
        if not acquired:
            say("另一个窗口正在启动CareerPilot，请等待该窗口完成。")
            return
        say("CareerPilot 本机启动检查")
        settings, mysql_port = load_settings()
        vite = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
        if not vite.is_file():
            raise StartupError("前端依赖缺失，请先在frontend目录运行 npm.cmd ci。")
        node = locate(Path(os.environ.get("CAREERPILOT_NODE", "node.exe")), "node.exe", "Node.js")
        mailpit = locate(Path(os.environ.get("CAREERPILOT_MAILPIT", "mailpit.exe")), "mailpit.exe", "Mailpit")
        start_mysql(mysql_port, args.check)
        database_ready(settings)
        say("[就绪] 数据库配置及迁移")
        ensure_service("mailpit", "Mailpit验证码收件箱", [8025, settings.smtp_port], lambda: mail_ready(settings.smtp_port),
                       [str(mailpit), "--listen", "127.0.0.1:8025", "--smtp", f"127.0.0.1:{settings.smtp_port}", "--disable-version-check"],
                       ROOT, check_only=args.check)
        ensure_service("api", "CareerPilot后端", [8000], api_ready,
                       [sys.executable, str(BACKEND / "manage.py"), "serve"], ROOT, check_only=args.check)
        web_env = {**os.environ, "VITE_PREVIEW_MODE": "false", "CAREERPILOT_API_TARGET": "http://127.0.0.1:8000"}
        ensure_service("web", "CareerPilot前端", [5173], web_ready,
                       [str(node), str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
                       ROOT / "frontend", check_only=args.check, env=web_env)
        say("启动检查通过。页面：http://127.0.0.1:5173/  验证码：http://127.0.0.1:8025/")
        if not args.no_browser and not args.check:
            if not webbrowser.open("http://127.0.0.1:5173/"):
                say("请在浏览器打开上面的页面地址。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except (StartupError, ImportError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, StartupError):
            message = str(error)
        else:
            message = "启动未完成，请检查程序权限及服务日志。"
        print(f"[失败] {message}\n日志目录：{SERVICES}", flush=True)
        raise SystemExit(1) from None
