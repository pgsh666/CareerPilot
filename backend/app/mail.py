import smtplib
from email.message import EmailMessage

from app.config import Settings
from app.errors import ApiError


class SMTPMailer:
    """Only an SMTP accept counts as sent. Credentials and codes are never logged."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def send_code(self, email: str, purpose: str, code: str):
        labels = {"register": "注册", "password_reset": "重置密码", "email_change": "更换邮箱"}
        message = EmailMessage()
        message["From"] = self.settings.mail_from
        message["To"] = email
        message["Subject"] = f"CareerPilot {labels[purpose]}验证码"
        minutes = self.settings.code_ttl_seconds // 60
        message.set_content(f"你的{labels[purpose]}验证码：{code}\n有效期 {minutes} 分钟，仅限本次操作使用。")
        if self.settings.smtp_host not in {"127.0.0.1", "localhost", "::1"}:
            if not self.settings.smtp_starttls:
                raise ApiError(503, "MAIL_NOT_CONFIGURED", "正式邮件服务需要安全连接")
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
                if self.settings.smtp_starttls:
                    smtp.starttls()
                if self.settings.smtp_username:
                    secret = self.settings.smtp_password
                    smtp.login(self.settings.smtp_username, secret.get_secret_value() if secret else "")
                refused = smtp.send_message(message)
                if refused:
                    raise ApiError(503, "MAIL_UNAVAILABLE", "验证码发送失败，请稍后重试", retryable=True)
        except (OSError, smtplib.SMTPException) as exc:
            raise ApiError(503, "MAIL_UNAVAILABLE", "验证码发送失败，请稍后重试", retryable=True) from exc

