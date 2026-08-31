"""
API 中转站核心模块

统一主 API Key 作为上游，管理员创建子 API（子 Key），
外部调用方经由子 Key 透传请求到上游并返回响应。
"""
import datetime
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

from .utils import CONFIG_PATH, DATA_PATH, get_logger, load_json, save_json

logger = get_logger("relay")

RELAY_CONFIG_PATH = CONFIG_PATH / "relay.json"
RELAY_LOG_PATH = DATA_PATH / "relay_logs.jsonl"
MAX_LOG_LINES = 2000

_KEY_PREFIX = "sk-relay-"


class RelayError(Exception):
    """中转站错误，携带 HTTP 状态码与用户可读信息"""

    def __init__(self, message: str, status: int = 400, error_type: str = "relay_error"):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


class RelayManager:
    """管理上游配置、子 API CRUD、配额计数与调用日志"""

    def __init__(self, config_path: Path = None, log_path: Path = None):
        self.config_path = config_path or RELAY_CONFIG_PATH
        self.log_path = log_path or RELAY_LOG_PATH
        self._lock = threading.RLock()
        self._semaphores = {}
        self._data = load_json(self.config_path, {"upstream": {}, "keys": []})
        self._data.setdefault("upstream", {})
        self._data.setdefault("keys", [])

    # ---------- 持久化 ----------

    def _save(self) -> bool:
        return save_json(self.config_path, self._data)

    # ---------- 上游配置 ----------

    def get_upstream(self) -> dict:
        cfg = dict(self._data.get("upstream", {}) or {})
        if cfg.get("api_key"):
            cfg["api_key"] = self._mask(cfg["api_key"])
        return cfg

    def get_upstream_credentials(self) -> dict:
        """返回真实的 base_url / api_key / model / timeout，供转发使用"""
        cfg = dict(self._data.get("upstream", {}) or {})
        return {
            "base_url": (cfg.get("base_url") or "").rstrip("/"),
            "api_key": cfg.get("api_key") or "",
            "model": cfg.get("model") or "",
            "timeout": int(cfg.get("timeout") or 60),
        }

    def set_upstream(self, base_url: str, api_key: str, model: str = "", timeout: int = 60) -> dict:
        with self._lock:
            upstream = self._data.setdefault("upstream", {})
            upstream["base_url"] = (base_url or "").strip().rstrip("/")
            upstream["api_key"] = (api_key or "").strip()
            upstream["model"] = (model or "").strip()
            if timeout:
                upstream["timeout"] = max(1, int(timeout))
            self._save()
            return self.get_upstream()

    @property
    def upstream_ready(self) -> bool:
        up = self._data.get("upstream", {}) or {}
        return bool(up.get("base_url") and up.get("api_key"))

    @staticmethod
    def _mask(value: str) -> str:
        v = value or ""
        if len(v) <= 8:
            return "******" if v else ""
        return v[:4] + "****" + v[-4:]

    # ---------- 子 API CRUD ----------

    def list_keys(self) -> list:
        return [self._public(k) for k in self._data.get("keys", [])]

    def get_key_by_token(self, token: str):
        for k in self._data.get("keys", []):
            if k.get("key") == token:
                return k
        return None

    def create_key(self, name: str, models: list = None, quota: dict = None) -> dict:
        with self._lock:
            token = _KEY_PREFIX + secrets.token_urlsafe(32)
            now = time.time()
            quota = quota or {}
            key = {
                "id": uuid.uuid4().hex[:12],
                "name": (name or "").strip() or "未命名",
                "key": token,
                "key_prefix": token[:16],
                "models": [m for m in (models or []) if m],
                "status": "enabled",
                "quota": {
                    "max_calls": int(quota.get("max_calls") or 0),
                    "max_tokens": int(quota.get("max_tokens") or 0),
                    "max_concurrent": int(quota.get("max_concurrent") or 0),
                    "daily_limit": int(quota.get("daily_limit") or 0),
                },
                "usage": {
                    "calls": 0,
                    "tokens": 0,
                    "daily_date": datetime.date.today().isoformat(),
                    "daily_calls": 0,
                    "last_used_at": None,
                },
                "created_at": now,
            }
            self._data.setdefault("keys", []).append(key)
            self._save()
            return self._public(key)

    def update_key(self, key_id: str, name: str = None, models: list = None,
                   quota: dict = None, status: str = None) -> dict:
        with self._lock:
            for k in self._data.get("keys", []):
                if k.get("id") == key_id:
                    if name is not None:
                        k["name"] = (name or "").strip() or "未命名"
                    if models is not None:
                        k["models"] = [m for m in models if m]
                    if quota is not None:
                        for field in ("max_calls", "max_tokens", "max_concurrent", "daily_limit"):
                            if field in quota:
                                k["quota"][field] = max(0, int(quota.get(field) or 0))
                    if status in ("enabled", "disabled"):
                        k["status"] = status
                    self._save()
                    return self._public(k)
            raise RelayError("子 API 不存在", 404, "not_found")

    def delete_key(self, key_id: str) -> bool:
        with self._lock:
            keys = self._data.get("keys", [])
            new_keys = [k for k in keys if k.get("id") != key_id]
            if len(new_keys) == len(keys):
                return False
            self._data["keys"] = new_keys
            self._semaphores.pop(key_id, None)
            self._save()
            return True

    def reset_usage(self, key_id: str) -> dict:
        with self._lock:
            for k in self._data.get("keys", []):
                if k.get("id") == key_id:
                    k["usage"] = {
                        "calls": 0,
                        "tokens": 0,
                        "daily_date": datetime.date.today().isoformat(),
                        "daily_calls": 0,
                        "last_used_at": None,
                    }
                    self._save()
                    return self._public(k)
            raise RelayError("子 API 不存在", 404, "not_found")

    # ---------- 配额与并发 ----------

    def check_quota(self, key: dict) -> None:
        if key.get("status") != "enabled":
            raise RelayError("子 API 已停用", 403, "disabled")
        quota = key.get("quota", {}) or {}
        usage = key.get("usage", {}) or {}
        today = datetime.date.today().isoformat()
        if usage.get("daily_date") != today:
            usage["daily_date"] = today
            usage["daily_calls"] = 0

        calls = usage.get("calls", 0)
        tokens = usage.get("tokens", 0)
        daily = usage.get("daily_calls", 0)
        if quota.get("max_calls") and calls >= quota["max_calls"]:
            raise RelayError("调用次数已达上限", 429, "quota_exceeded")
        if quota.get("max_tokens") and tokens >= quota["max_tokens"]:
            raise RelayError("token 总量已达上限", 429, "quota_exceeded")
        if quota.get("daily_limit") and daily >= quota["daily_limit"]:
            raise RelayError("今日调用已达上限", 429, "quota_exceeded")
        self._check_concurrent(key)

    def _check_concurrent(self, key: dict) -> None:
        key_id = key.get("id")
        limit = key.get("quota", {}).get("max_concurrent", 0) or 0
        if not limit:
            return
        with self._lock:
            sem = self._semaphores.get(key_id)
            if sem is None:
                sem = threading.BoundedSemaphore(limit)
                self._semaphores[key_id] = sem
        if not sem.acquire(blocking=False):
            raise RelayError("并发请求数已达上限", 429, "concurrency_limited")

    def release(self, key: dict) -> None:
        key_id = key.get("id")
        with self._lock:
            sem = self._semaphores.get(key_id)
        if sem is not None:
            try:
                sem.release()
            except ValueError:
                pass

    def record_usage(self, key: dict, tokens: int = 0) -> None:
        with self._lock:
            usage = key.get("usage", {})
            usage["calls"] = usage.get("calls", 0) + 1
            usage["daily_calls"] = usage.get("daily_calls", 0) + 1
            usage["tokens"] = usage.get("tokens", 0) + max(0, int(tokens or 0))
            usage["last_used_at"] = time.time()
            self._save()

    # ---------- 日志 ----------

    def log(self, key_name: str, key_prefix: str, model: str, status_code: int,
            tokens: int = 0, duration_ms: int = 0) -> None:
        entry = {
            "ts": time.time(),
            "key_name": key_name,
            "key_prefix": key_prefix,
            "model": model,
            "status_code": status_code,
            "tokens": int(tokens or 0),
            "duration_ms": int(duration_ms or 0),
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._trim_log()
        except OSError as e:
            logger.warning("写入中转日志失败: %s", e)

    def get_logs(self, name: str = "", limit: int = 100) -> list:
        lines = []
        try:
            with open(self.log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if name and entry.get("key_name") != name:
                        continue
                    lines.append(entry)
        except OSError:
            return []
        lines.sort(key=lambda e: e.get("ts", 0), reverse=True)
        return lines[: max(1, min(int(limit or 100), 1000))]

    def _trim_log(self) -> None:
        try:
            with open(self.log_path, encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MAX_LOG_LINES:
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_LOG_LINES:])
        except OSError:
            pass

    # ---------- 展示 ----------

    @staticmethod
    def _public(key: dict) -> dict:
        k = dict(key)
        k.setdefault("usage", {})
        return k
