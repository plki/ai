"""
公共工具模块 - 项目路径、格式化、JSON 安全读写、日志
"""
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config"
DATA_PATH = PROJECT_ROOT / "data"

MAX_TEXT_SIZE = 2 * 1024 * 1024  # 网页抓取上限 2MB


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的 logger"""
    logger = logging.getLogger(f"ai_desktop.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def load_json(path: Path, default=None):
    """安全读取 JSON，文件不存在或解析失败时返回 default"""
    if default is None:
        default = {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return default


def save_json(path: Path, data) -> bool:
    """安全写入 JSON"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def format_size(size: int) -> str:
    """格式化文件大小"""
    size = max(int(size), 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def dir_size(path: Path) -> int:
    """流式统计目录总大小（生成器遍历，避免全量载入内存）"""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except (PermissionError, OSError):
        return total
    return total
