"""Send a synthetic message to the local Mailpit only. No external email is sent."""
import sys
from pathlib import Path
from urllib.request import urlopen

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / ".deps"))
sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.mail import SMTPMailer  # noqa: E402


def main():
    # Force loopback rather than reading an arbitrary configured SMTP destination.
    settings = Settings(
        _env_file=None, environment="test", database_url=None, secret_key=None,
        smtp_host="127.0.0.1", smtp_port=1025, smtp_username=None, smtp_password=None,
        smtp_starttls=False,
    )
    with urlopen("http://127.0.0.1:8025/", timeout=5) as response:
        if response.status != 200:
            raise SystemExit("Mailpit UI not ready")
    SMTPMailer(settings).send_code("backend-smoke@example.invalid", "register", "123456")
    print("Mailpit UI reachable; SMTP accepted the synthetic local-only verification message.")


if __name__ == "__main__":
    main()
