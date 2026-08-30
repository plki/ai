"""
AI 引擎 - 本地 Ollama 与 OpenAI 兼容云端 API 双 provider

特性：
- 支持 provider 抽象：local（Ollama）/ cloud（任意 OpenAI 兼容 API，可配 Base URL + Key + 模型名）
- 原生 function calling（/api/chat + tools 或 /v1/chat/completions + tools）
- 思考 → 确认 → 执行：AI 提出工具调用计划后先由用户确认，再执行
- 关键词快路径，降低模型幻觉与延迟
- 对话历史按 max_history 裁剪，防止内存无限增长
"""
import json
import os
import re
import subprocess
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from colorama import Fore, Style

from .utils import CONFIG_PATH, get_logger, load_json

logger = get_logger("ai")

OLLAMA_HOST = "http://127.0.0.1:11434"
MAX_TOOL_TURNS = 5  # 单轮对话最多执行的工具调用次数，防止死循环


@dataclass
class ConfirmRequest:
    """AI 提出的工具调用计划，等待用户确认"""
    plan: str = "执行以下操作"
    tool_calls: list = field(default_factory=list)

    @property
    def tool_names(self) -> list:
        return [tc["name"] for tc in self.tool_calls]


# 全局 session 清理注册表
_ai_instances = []

# 模型列表缓存（避免每次创建 AIEngine 都查 Ollama API）
_model_cache = None


def _register_session(instance):
    _ai_instances.append(instance)


def cleanup_all_sessions():
    """清理所有资源：HTTP 连接 + 通知 Ollama 卸载模型"""
    # 1. 通知 Ollama 卸载模型
    try:
        session = requests.Session()
        for inst in _ai_instances:
            if inst.provider and inst.provider.name == "ollama" and inst.model:
                session.post(
                    f"{inst.provider.host}/api/generate",
                    json={"model": inst.model, "keep_alive": 0},
                    timeout=2,
                )
        session.close()
    except Exception:
        pass

    # 2. 关闭所有 provider 的 HTTP 会话
    for inst in _ai_instances:
        try:
            inst.provider.close()
        except Exception:
            pass
    _ai_instances.clear()


def _clear_model_cache():
    """清除模型缓存（模型拉取后调用）"""
    global _model_cache
    _model_cache = None


SYSTEM_PROMPT = """你是智能桌面助手。规则：
1. 不知道真实信息必须用工具获取，不许编造
2. 用中文简短回复
3. 需要工具时调用提供的 function 工具，不要自己编造结果
可用工具：file_list, file_find, file_sort, web_fetch, web_search, web_download, task_run, system_info, model_search, model_download, backup"""

# 关键词 → 工具映射（在发送给 AI 前先匹配，避免模型瞎编）
KEYWORD_TOOLS = {
    "系统信息": ("task_run", {"name": "系统信息"}),
    "系统配置": ("task_run", {"name": "系统信息"}),
    "电脑配置": ("task_run", {"name": "系统信息"}),
    "本机信息": ("task_run", {"name": "系统信息"}),
    "磁盘": ("task_run", {"name": "磁盘分析"}),
    "硬盘": ("task_run", {"name": "磁盘分析"}),
    "空间": ("task_run", {"name": "磁盘分析"}),
    "进程": ("task_run", {"name": "进程列表"}),
    "任务管理器": ("task_run", {"name": "进程列表"}),
    "网络诊断": ("task_run", {"name": "网络诊断"}),
    "网络检查": ("task_run", {"name": "网络诊断"}),
    "清理垃圾": ("task_run", {"name": "清理临时文件"}),
    "清理临时文件": ("task_run", {"name": "清理临时文件"}),
    "列出文件": ("file_list", {}),
    "目录": ("file_list", {}),
}

TOOL_UI_NAMES = {
    "file_list": "列出文件",
    "file_find": "搜索文件",
    "file_sort": "整理目录",
    "web_fetch": "抓取网页",
    "web_search": "搜索网络",
    "web_download": "下载文件",
    "task_run": "运行任务",
    "system_info": "查看系统信息",
    "model_search": "查找模型",
    "model_download": "下载模型",
    "backup": "备份目录",
}

# function calling 工具定义（同时兼容 Ollama 与 OpenAI 格式）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "列出指定目录的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认当前目录"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_find",
            "description": "在指定目录中搜索文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "path": {"type": "string", "description": "搜索路径，默认当前目录"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_sort",
            "description": "按文件类型自动整理目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要整理的目录路径"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "获取网页内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索网络信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_download",
            "description": "下载网络文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "文件 URL"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_run",
            "description": "运行预设任务（如系统信息、磁盘分析、清理临时文件等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "查看系统信息（操作系统、CPU、内存）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "model_search",
            "description": "查看推荐可下载的 AI 模型",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，可选"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "model_download",
            "description": "下载 AI 模型",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "模型名称或编号"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backup",
            "description": "备份指定目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要备份的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
]

# 工具参数默认值映射（缺省参数时的兜底值）
TOOL_DEFAULTS = {
    "file_list": {"path": "."},
    "file_find": {"path": "."},
    "file_sort": {"path": "."},
    "model_search": {"keyword": ""},
}


def _load_ai_config() -> dict:
    """读取 ai 段配置"""
    return load_json(CONFIG_PATH / "config.json", {}).get("ai", {})


# ============ Provider 抽象 ============

class BaseProvider:
    name = "base"

    def __init__(self):
        self.session = requests.Session()

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


class OllamaProvider(BaseProvider):
    """本地 Ollama provider"""

    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST):
        super().__init__()
        self.host = host

    def list_models(self) -> list:
        try:
            with self.session.get(f"{self.host}/api/tags", timeout=5) as resp:
                return resp.json().get("models", [])
        except Exception:
            return []

    def chat(self, model: str, messages: list, tools: list) -> dict:
        """调用 /api/chat，返回 {content, tool_calls}，tool_calls 为规范化的列表"""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "tools": tools,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        try:
            resp = self.session.post(f"{self.host}/api/chat", json=payload, timeout=120)
            if resp.status_code == 404:
                raise ProviderCompatibilityError("Ollama 版本过低，不支持 function calling")
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {}) or {}
            tool_calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {}) or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                tool_calls.append({"id": fn.get("id", ""), "name": fn.get("name", ""), "args": args})
            return {"content": msg.get("content", ""), "tool_calls": tool_calls}
        except ProviderCompatibilityError:
            raise
        except requests.exceptions.ConnectionError:
            raise ProviderError("Ollama 未运行")
        except requests.exceptions.Timeout:
            raise ProviderError("AI 响应超时（模型较慢）")
        except Exception as e:
            logger.exception("Ollama 对话失败")
            raise ProviderError(f"Ollama 对话失败: {e}")

    def chat_fallback(self, model: str, messages: list) -> dict:
        """不带 tools 的简单对话（兼容旧版 Ollama）"""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        try:
            resp = self.session.post(f"{self.host}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return {"content": (data.get("message", {}) or {}).get("content", ""), "tool_calls": []}
        except Exception:
            raise ProviderError("AI 对话失败")

    def pull(self, model: str, progress_cb=None):
        """拉取模型，progress_cb(status: str, pct: float)"""
        try:
            with self.session.post(
                f"{self.host}/api/pull", json={"name": model, "stream": True},
                stream=True, timeout=300,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        total = data.get("total", 0)
                        completed = data.get("completed", 0)
                        pct = (completed / total * 100) if total else 0.0
                        if progress_cb:
                            progress_cb(status, pct)
                        elif status == "success":
                            break
                    except json.JSONDecodeError:
                        pass
            return True
        except Exception as e:
            logger.exception("模型拉取失败")
            raise ProviderError(f"拉取失败: {e}")

    def unload(self, model: str):
        try:
            self.session.post(
                f"{self.host}/api/generate", json={"model": model, "keep_alive": 0}, timeout=2,
            )
        except Exception:
            pass


class CloudProvider(BaseProvider):
    """OpenAI 兼容云端 API provider（DeepSeek / 通义 / Moonshot / OpenAI ...）"""

    name = "cloud"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        super().__init__()
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = int(timeout or 60)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check(self) -> tuple:
        """轻量校验配置，返回 (ok, message)"""
        if not self.base_url:
            return False, "未配置云端 API base_url"
        if not self.api_key:
            return False, "未配置云端 API Key"
        if not self.model:
            return False, "未配置云端模型名"
        return True, "ok"

    def list_models(self) -> list:
        return [{"name": self.model}] if self.model else []

    def chat(self, model: str, messages: list, tools: list) -> dict:
        """调用 /v1/chat/completions，返回 {content, tool_calls}"""
        url = self._url()
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        try:
            resp = self.session.post(url, headers=self._headers(), json=body, timeout=self.timeout)
            if resp.status_code in (401, 403):
                raise ProviderError("云端 API 认证失败，请检查 Key")
            if resp.status_code == 404:
                raise ProviderError(f"模型不存在或接口地址有误: {model}")
            resp.raise_for_status()
            data = resp.json()
            msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
            content = msg.get("content") or ""
            tool_calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {}) or {}
                args = fn.get("arguments") or "{}"
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                tool_calls.append({"id": fn.get("id", tc.get("id", "")), "name": fn.get("name", ""), "args": args})
            if tool_calls and len(content) < 3:
                content = f"[计划调 {len(tool_calls)} 个工具]"
            return {"content": content, "tool_calls": tool_calls}
        except ProviderError:
            raise
        except requests.exceptions.ConnectionError:
            raise ProviderError("无法连接云端 API（检查 base_url 与网络）")
        except requests.exceptions.Timeout:
            raise ProviderError(f"云端 API 响应超时（{self.timeout}s）")
        except Exception as e:
            logger.exception("云端 API 对话失败")
            raise ProviderError(f"云端 API 对话失败: {e}")

    def close(self):
        super().close()


class ProviderError(Exception):
    """AI provider 错误，携带用户可读信息"""


class ProviderCompatibilityError(ProviderError):
    """provider 不支持某些特性（如旧版 Ollama 不支持 function calling）"""


# ============ AI 引擎 ============

class AIEngine:
    def __init__(self, model: str = ""):
        cfg = _load_ai_config()
        self.confirm_tools = bool(cfg.get("confirm_tools", True))
        self.max_history = self._load_max_history()
        self.conversation_history = []
        self.system_prompt = SYSTEM_PROMPT
        self.provider = self._create_provider(cfg)
        self.model = model or self._pick_default_model(cfg)
        self._session = self.provider.session  # 兼容旧代码引用
        _register_session(self)

    # ---------- 初始化 ----------

    @staticmethod
    def _load_max_history() -> int:
        try:
            return int(_load_ai_config().get("max_history", 20))
        except (TypeError, ValueError):
            return 20

    def _create_provider(self, cfg: dict) -> BaseProvider:
        provider_name = cfg.get("provider", "auto")
        cloud = cfg.get("cloud", {}) or {}
        use_cloud = provider_name == "cloud"
        if provider_name == "auto":
            # 云端配置了就优先云端，否则本地 Ollama
            use_cloud = bool(cloud.get("base_url") and cloud.get("api_key"))
        if use_cloud:
            return CloudProvider(
                base_url=cloud.get("base_url", ""),
                api_key=cloud.get("api_key", ""),
                model=cloud.get("model", ""),
                timeout=cloud.get("timeout", 60),
            )
        return OllamaProvider(host=cfg.get("ollama_host", OLLAMA_HOST))

    def _pick_default_model(self, cfg: dict) -> str:
        if self.provider.name == "cloud":
            cloud = cfg.get("cloud", {}) or {}
            return cloud.get("model", "")
        return self._pick_best_model()

    def _pick_best_model(self) -> str:
        """直接选最好的中文模型（带缓存，不重复查 Ollama API）"""
        global _model_cache
        if _model_cache is not None:
            return _model_cache
        try:
            models = self.provider.list_models()
            names = [m.get("name", "") for m in models if m.get("name")]
            if not names:
                return ""
            priority = ["qwen2.5", "qwen2", "tinyllama", "granite4", "llama"]
            for p in priority:
                for name in names:
                    if p in name.lower():
                        _model_cache = name
                        return name
            _model_cache = names[0]
            return names[0]
        except Exception:
            return ""

    # ---------- 历史与上下文 ----------

    def _append_history(self, role: str, content: str):
        """追加对话历史并裁剪，防止内存无限增长"""
        self.conversation_history.append({"role": role, "content": content})
        limit = max(self.max_history * 2, 4)
        if len(self.conversation_history) > limit:
            self.conversation_history = self.conversation_history[-limit:]

    def _build_messages(self) -> list:
        """构建 provider 所需 messages（system + 历史）"""
        return [{"role": "system", "content": self.system_prompt}] + list(self.conversation_history)

    def clear_history(self):
        self.conversation_history = []

    def cleanup(self):
        """退出时清理 HTTP 连接"""
        try:
            self.provider.close()
        except Exception:
            pass

    # ---------- 关键词快路径 ----------

    def _try_keyword_tool(self, message: str) -> Optional[dict]:
        """在发送给 AI 前，先匹配关键词直接执行工具（避免模型瞎编）"""
        home = Path.home()
        project_dir = Path(__file__).parent.parent

        def _extract_path(msg: str) -> str:
            quick_map = {
                "桌面": str(home / "Desktop"),
                "下载": str(home / "Downloads"),
                "文档": str(home / "Documents"),
            }
            for name, folder in quick_map.items():
                if name in msg:
                    return folder
            m = re.search(r'([A-Za-z]:\\[^\s]*)', msg)
            if not m:
                return "."
            path = m.group(1)
            for suffix in ["帮我整理", "帮我排序", "帮我归类", "整理一下", "整理", "排序", "归类",
                           "帮我列出", "列出", "帮我查找", "查找", "搜索", "帮我搜索"]:
                if path.endswith(suffix):
                    path = path[:-len(suffix)]
                    break
            return path if path.strip(":\\/") else "."

        if "整理" in message or "排序" in message or "归类" in message:
            path = _extract_path(message)
            if path != "." and os.path.abspath(path) == str(project_dir):
                print("  [!] 不能整理项目自身目录，已跳过")
                return {"name": "noop", "args": {}}
            return {"name": "file_sort", "args": {"path": path}}

        if "列出" in message or "有什么文件" in message or "目录" in message:
            path = _extract_path(message)
            return {"name": "file_list", "args": {"path": path}}

        if any(kw in message for kw in ["删除空文本", "删除空文件", "清理空文本", "清理空文件",
                                        "删除没有的空文本", "删除没有的空文件"]):
            desktop = home / "Desktop"
            if desktop.exists():
                empty_files = [f for f in desktop.iterdir()
                               if f.is_file() and f.suffix.lower() == ".txt" and f.stat().st_size == 0]
                if empty_files:
                    print(f"\n  [找到 {len(empty_files)} 个空文本文件]")
                    for f in empty_files:
                        try:
                            f.unlink()
                            print(f"  已删除: {f.name}")
                        except OSError as e:
                            print(f"  删除失败: {f.name} ({e})")
                else:
                    print("\n  [桌面没有空文本文件]")
            else:
                print("\n  [桌面目录不存在]")
            return {"name": "noop", "args": {}}

        if any(kw in message for kw in ["打开", "启动", "运行"]):
            msg_lower = message.lower()
            app_map = {
                "edge": "start msedge",
                "浏览器": "start msedge",
                "chrome": "start chrome",
                "记事本": "notepad",
                "计算器": "calc",
                "画图": "mspaint",
                "cmd": "start cmd",
                "命令提示符": "start cmd",
                "任务管理器": "taskmgr",
            }
            for name, cmd in app_map.items():
                if name in msg_lower:
                    if os.name == "nt":
                        subprocess.Popen(cmd, shell=True)
                    print(f"\n  [已打开: {name}]")
                    return {"name": "noop", "args": {}}

        for kw, (tool, args) in KEYWORD_TOOLS.items():
            if kw in message:
                return {"name": tool, "args": args}
        return None

    # ---------- 主对话流程 ----------

    def chat(self, message: str) -> Generator:
        """与 AI 对话（思考→确认→执行）。

        生成器 yield 两类值：
        - str：正常输出文本，可流式打印
        - ConfirmRequest：AI 请求执行工具，调用方需用 `gen.send(True/False)` 回复
        """
        if not self.model:
            yield f"\n{Fore.RED}  AI 模型不可用，请先配置模型{Style.RESET_ALL}"
            return

        self._append_history("user", message)

        # 先尝试关键词匹配（避免模型瞎编）
        tool_call = self._try_keyword_tool(message)
        if tool_call:
            yield from self._execute_tool_and_continue(tool_call)
            return

        # 原生 function calling
        yield from self._chat_with_tools()

    def _chat_with_tools(self) -> Generator:
        """AI 提出计划 → 用户确认 → 执行 → 汇总（原生 function calling）"""
        working = list(self._build_messages())

        for _ in range(MAX_TOOL_TURNS):
            try:
                data = self.provider.chat(self.model, working, TOOLS)
            except ProviderCompatibilityError:
                yield from self._chat_fallback()
                return
            except ProviderError as e:
                yield f"\n  [x] {e}"
                return

            content = data.get("content", "")
            tool_calls = data.get("tool_calls", []) or []

            if content:
                yield content

            if not tool_calls:
                if content.strip():
                    self._append_history("assistant", content.strip())
                return

            # 组装 assistant 消息（含工具调用）
            assistant_msg = {"role": "assistant", "content": content or ""}
            if self.provider.name == "cloud":
                assistant_msg["tool_calls"] = [
                    {"id": tc.get("id", f"call_{i}"), "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False)}}
                    for i, tc in enumerate(tool_calls)
                ]
            else:
                assistant_msg["tool_calls"] = [
                    {"function": {"name": tc["name"], "arguments": tc.get("args", {})}}
                    for tc in tool_calls
                ]
            working.append(assistant_msg)

            # 思考 → 确认 环节
            should_run = True
            if self.confirm_tools:
                plan = self._describe_plan(tool_calls)
                req = ConfirmRequest(plan=plan, tool_calls=tool_calls)
                decision = yield req  # 调用方 send(True/False)
                should_run = bool(decision)

            if not should_run:
                yield "\n  [已取消] 好的，本次操作未执行。\n"
                # 把拒绝结果回填给模型
                for tc in tool_calls:
                    tool_msg = {"role": "tool", "content": "用户拒绝执行此工具调用，未执行。"}
                    if self.provider.name == "cloud":
                        tool_msg["tool_call_id"] = tc.get("id", "call_0")
                    working.append(tool_msg)
                continue

            # 执行工具并回填结果
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args", {}) or {}
                yield f"\n  [执行: {name}] "
                result = self._run_tool(name, args)
                tool_msg = {"role": "tool", "content": result}
                if self.provider.name == "cloud":
                    tool_msg["tool_call_id"] = tc.get("id", "call_0")
                working.append(tool_msg)

    def _describe_plan(self, tool_calls: list) -> str:
        lines = []
        for tc in tool_calls:
            name = tc.get("name", "")
            label = TOOL_UI_NAMES.get(name, name)
            args = tc.get("args", {}) or {}
            detail = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
            lines.append(f"{label}({detail})" if detail else label)
        return " → ".join(lines)

    def _chat_fallback(self) -> Generator:
        """备用方案：不带 tools 的简单对话（兼容旧版 Ollama）"""
        try:
            resp = self.provider.chat_fallback(self.model, self._build_messages())
            content = resp.get("content", "")
            self._append_history("assistant", content.strip())
            yield content or "\n  [无响应]"
        except ProviderError as e:
            yield f"\n  [x] {e}"

    def ask(self, message: str) -> str:
        """一次性问答（自动确认执行工具）"""
        result = ""
        gen = self.chat(message)
        for chunk in gen:
            if isinstance(chunk, ConfirmRequest):
                gen.send(True)
            else:
                result += chunk
        return result

    # ---------- 工具执行 ----------

    def _run_tool(self, name: str, args: dict) -> str:
        """执行工具并返回文本结果"""
        from .backup_manager import BackupManager
        from .file_manager import FileManager
        from .model_manager import ModelManager
        from .task_automation import TaskAutomation
        from .web_automation import WebAutomation

        if name == "noop":
            return ""

        try:
            if name == "file_list":
                FileManager().list_files(args.get("path", "."))
                return "文件列表已显示"
            if name == "file_find":
                FileManager().find_files(args.get("keyword", ""), args.get("path", "."))
                return "搜索结果已显示"
            if name == "file_sort":
                FileManager().sort_files_by_type(args.get("path", "."))
                return "文件整理完成"
            if name == "web_fetch":
                WebAutomation().fetch_page(args.get("url", ""))
                return "网页内容已获取"
            if name == "web_search":
                WebAutomation().search(args.get("keyword", ""))
                return "搜索结果已显示"
            if name == "web_download":
                WebAutomation().download_file(args.get("url", ""))
                return "下载完成"
            if name == "task_run":
                TaskAutomation().run_task(args.get("name", ""))
                return "任务执行完成"
            if name == "model_search":
                ModelManager().search_models(args.get("keyword", ""))
                return "模型列表已显示"
            if name == "model_download":
                ModelManager().download_model(args.get("name", ""))
                return "模型下载中"
            if name == "backup":
                BackupManager().backup_directory(args.get("path", ""))
                return "备份完成"
            if name == "system_info":
                TaskAutomation().run_task("系统信息")
                return "系统信息已显示"
            return f"未知工具: {name}"
        except Exception as e:
            logger.exception("工具执行失败")
            return f"执行失败: {e}"

    def _execute_tool_and_continue(self, tool_call: dict) -> Generator:
        """执行关键词匹配出的工具调用（带确认）"""
        if tool_call.get("name") == "noop":
            return

        name = tool_call["name"]
        args = dict(tool_call.get("args", {}))
        defaults = TOOL_DEFAULTS.get(name, {})
        for key, val in defaults.items():
            args.setdefault(key, val)

        if not self.confirm_tools:
            yield f"\n  [执行: {name}] "
            yield f"OK. {self._run_tool(name, args)}"
            return

        label = TOOL_UI_NAMES.get(name, name)
        detail = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
        req = ConfirmRequest(plan=f"{label}({detail})" if detail else label,
                             tool_calls=[{"name": name, "args": args}])
        decision = yield req
        if not decision:
            yield f"\n  [已取消] 未执行 {label}。\n"
            return
        yield f"\n  [执行: {name}] "
        yield f"OK. {self._run_tool(name, args)}"

    # ---------- 模型管理 ----------

    def list_available_models(self) -> list:
        if self.provider.name == "cloud":
            if self.model:
                return [{"name": self.model, "size": "云端", "params": "?",
                         "quant": "?", "provider": "cloud"}]
            return []
        try:
            models = self.provider.list_models()
            return [{
                "name": m.get("name", ""),
                "size": self._format_size(m.get("size", 0)),
                "params": (m.get("details", {}) or {}).get("parameter_size", "?"),
                "quant": (m.get("details", {}) or {}).get("quantization_level", "?"),
                "provider": "ollama",
            } for m in models if m.get("name")]
        except Exception:
            return []

    def pull_model(self, name: str):
        """从 Ollama 拉取模型"""
        if self.provider.name != "ollama":
            print("  云端模式无需拉取模型，直接使用云端 API 即可")
            return
        print(f"  正在拉取模型: {name}")
        print(f"  {'=' * 50}")
        try:
            self.provider.pull(
                name,
                progress_cb=lambda status, pct: self._show_pull_progress(name, status, pct),
            )
            _clear_model_cache()
        except ProviderError as e:
            print(f"  拉取失败: {e}")
        else:
            print("\n  完成！")

    def _show_pull_progress(self, name: str, status: str, pct: float):
        if "downloading" in status and pct > 0:
            bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
            print(f"\r  [{bar}] {pct:.0f}%", end="", flush=True)
        else:
            print(f"\r  {status}", end="", flush=True)

    def _format_size(self, size: int) -> str:
        from .utils import format_size
        return format_size(size)
