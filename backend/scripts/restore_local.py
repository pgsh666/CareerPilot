"""Interactive CMD entry; pass file paths as structured arguments, never shell text."""
import subprocess
import sys
from pathlib import Path

backend = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(backend), str(backend / ".deps")]

if __name__ == "__main__":
    from sqlalchemy.engine import make_url

    from app.config import Settings

    settings = Settings()
    if not settings.database_url:
        raise SystemExit("请先配置专用项目库。")
    target = str(make_url(settings.database_url.get_secret_value()).database)
    print("请先停止CareerPilot后端（8000端口）；恢复前会备份当前数据，最新费用和删除记录必须完整。")
    print("当前目标库：" + target)
    selected = Path(input("备份ZIP完整路径：").strip().strip('"')).resolve()
    if not selected.is_file():
        raise SystemExit("备份文件不存在，未恢复数据。")
    confirmation = input("重新输入上方目标库名：").strip()
    if confirmation != target:
        raise SystemExit("目标不一致，未恢复数据。")
    raise SystemExit(subprocess.call([sys.executable, str(backend / "manage.py"), "restore", str(selected),
                                     "--confirm-database", confirmation]))
