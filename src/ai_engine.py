"""
AI 引擎 - 集成本地 Ollama 模型

现代化版本：
- 使用 Ollama 原生 function calling（/api/chat + tools），替代脆弱的文本标签解析
- 保留关键词快路径，降低模型幻觉与延迟
- 对话历史按 max_history 裁剪，防止内存无限增长
"""
import json
import os
import re
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Optional

import requests
from colorama import Fore, Style

from .utils import CONFIG_PATH, get_logger, load_json

logger = get_logger("ai")

OLLAMA_HOST = "http://127.0.0.1:11434"
MAX_TOOL_TURNS = 5  # 单轮对话最多执行的工具调用次数，防止死循环

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
            if inst.model:
                session.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": inst.model, "keep_alive": 0},
                    timeout=2,
                )
        session.close()
    except Exception:
        pass

    # 2. 关闭所有 HTTP session
    for inst in _ai_instances:
        try:
            inst._session.close()
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

# Ollama function calling 工具定义
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


class AIEngine:
    def __init__(self, model: str = ""):
        self.api_base = OLLAMA_HOST
        self._session = requests.Session()
        self.model = model or self._pick_best_model()
        self.conversation_history = []
        self.system_prompt = SYSTEM_PROMPT
        self.max_history = self._load_max_history()
        _register_session(self)

    @staticmethod
    def _load_max_history() -> int:
        try:
            return int(load_json(CONFIG_PATH / "config.json", {}).get("ai", {}).get("max_history", 20))
        except (TypeError, ValueError):
            return 20

    def cleanup(self):
        """退出时清理 HTTP 连接"""
        try:
            self._session.close()
        except Exception:
            pass

    def _pick_best_model(self) -> str:
        """直接选最好的中文模型（带缓存，不重复查 Ollama API）"""
        global _model_cache
        if _model_cache is not None:
            return _model_cache

        try:
            with self._session.get(f"{self.api_base}/api/tags", timeout=5) as resp:
                models = resp.json().get("models", [])
            names = [m["name"] for m in models]
            if not names:
                return ""
            # 优先级：qwen（中文最强）> tinyllama（快）> others
            priority = ["qwen2.5", "qwen2", "tinyllama", "granite4", "llama"]
            for p in priority:
                for name in names:
                    if p in name.lower():
                        print(f"  {Fore.GREEN}  AI 模型: {name}{Style.RESET_ALL}")
                        _model_cache = name
                        return name
            _model_cache = names[0]
            return names[0]
        except Exception:
            return ""

    def _append_history(self, role: str, content: str):
        """追加对话历史并裁剪，防止内存无限增长"""
        self.conversation_history.append({"role": role, "content": content})
        # 保留最近 max_history 条消息（按配置裁剪）
        limit = max(self.max_history * 2, 4)
        if len(self.conversation_history) > limit:
            self.conversation_history = self.conversation_history[-limit:]

    def _build_messages(self) -> list:
        """构建 /api/chat 所需 messages（system + 历史）"""
        return [{"role": "system", "content": self.system_prompt}] + self.conversation_history

    def _try_keyword_tool(self, message: str) -> Optional[dict]:
        """在发送给 AI 前，先匹配关键词直接执行工具（避免模型瞎编）"""
        home = Path.home()
        project_dir = Path(__file__).parent.parent

        def _extract_path(msg: str) -> str:
            """从消息中提取路径，支持快捷名称（桌面/下载/文档）和盘符路径"""
            quick_map = {
                "桌面": str(home / "Desktop"),
                "下载": str(home / "Downloads"),
                "文档": str(home / "Documents"),
            }
            for name, folder in quick_map.items():
                if name in msg:
                    return folder
            # 盘符路径：E:\\回忆
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

        # 特殊处理：整理/排序 → file_sort（需要提取路径）
        if "整理" in message or "排序" in message or "归类" in message:
            path = _extract_path(message)
            if path != "." and os.path.abspath(path) == str(project_dir):
                print("  [!] 不能整理项目自身目录，已跳过")
                return {"name": "noop", "args": {}}
            return {"name": "file_sort", "args": {"path": path}}

        # 特殊处理：列出文件 → file_list（需要提取路径）
        if "列出" in message or "有什么文件" in message or "目录" in message:
            path = _extract_path(message)
            return {"name": "file_list", "args": {"path": path}}

        # 特殊处理：删除空文件 → 直接执行
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

        # 特殊处理：打开应用 → 直接启动
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

        # 常规关键词匹配
        for kw, (tool, args) in KEYWORD_TOOLS.items():
            if kw in message:
                return {"name": tool, "args": args}
        return None

    def chat(self, message: str, stream: bool = True) -> Generator[str, None, None]:
        """与 AI 对话（function calling + 关键词快路径）"""
        if not self.model:
            yield f"\n{Fore.RED}  AI 模型不可用{Style.RESET_ALL}"
            return

        self._append_history("user", message)

        # 先尝试关键词匹配（避免模型瞎编）
        tool_call = self._try_keyword_tool(message)
        if tool_call:
            yield from self._execute_tool_and_continue(tool_call)
            return

        # 原生 function calling
        yield from self._chat_with_tools(stream)

    def _chat_with_tools(self, stream: bool = True) -> Generator[str, None, None]:
        """使用 /api/chat + tools 原生函数调用"""
        working = list(self._build_messages())
        options = {"temperature": 0.3, "num_predict": 256}

        for _ in range(MAX_TOOL_TURNS):
            payload = {
                "model": self.model,
                "messages": working,
                "stream": False,
                "tools": TOOLS,
                "options": options,
            }
            try:
                resp = self._session.post(
                    f"{self.api_base}/api/chat", json=payload, timeout=120,
                )
                if resp.status_code == 404:
                    yield from self._chat_fallback(stream)
                    return
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls") or []

                if content:
                    yield content

                if not tool_calls:
                    # 无工具调用 → 本轮结束
                    if content.strip():
                        self._append_history("assistant", content.strip())
                    return

                # 记录 assistant 的工具调用请求
                assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tool_calls}
                working.append(assistant_msg)

                # 逐个执行工具并把结果回填给模型
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {}) or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    yield f"\n  [执行: {name}] "
                    result = self._run_tool(name, args)
                    working.append({"role": "tool", "content": result})
            except requests.exceptions.ConnectionError:
                yield "\n  Ollama 未运行"
                return
            except requests.exceptions.Timeout:
                yield "\n  AI 响应超时（模型较慢），建议换个更小的模型"
                return
            except Exception as e:
                logger.exception("AI 对话出错")
                yield f"\n  出错: {e}"
                return

    def _chat_fallback(self, stream: bool = True) -> Generator[str, None, None]:
        """备用方案：使用 chat API（不带 tools）"""
        chat_payload = {
            "model": self.model,
            "messages": self._build_messages(),
            "stream": stream,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        try:
            resp = self._session.post(
                f"{self.api_base}/api/chat", json=chat_payload, stream=stream, timeout=120,
            )
            resp.raise_for_status()
            full_response = ""
            if stream:
                for line in resp.iter_lines(decode_unicode=True):
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            full_response += content
                            yield content
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                data = resp.json()
                full_response = data.get("message", {}).get("content", "")
            resp.close()
            if full_response.strip():
                self._append_history("assistant", full_response.strip())
        except Exception:
            yield "\n  AI 对话失败"

    def ask(self, message: str) -> str:
        """一次性问答"""
        result = ""
        for chunk in self.chat(message, stream=False):
            result += chunk
        return result

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

    def _execute_tool_and_continue(self, tool_call: dict) -> Generator[str, None, None]:
        """执行关键词匹配出的工具调用（兼容旧流程）"""
        if tool_call.get("name") == "noop":
            return
        name = tool_call["name"]
        args = tool_call["args"]
        defaults = TOOL_DEFAULTS.get(name, {})
        for key, val in defaults.items():
            args.setdefault(key, val)
        yield f"\n  [执行: {name}] "
        yield f"OK. {self._run_tool(name, args)}"

    def list_available_models(self) -> list:
        try:
            with self._session.get(f"{self.api_base}/api/tags", timeout=5) as resp:
                models = resp.json().get("models", [])
            return [{
                "name": m["name"],
                "size": self._format_size(m.get("size", 0)),
                "params": m.get("details", {}).get("parameter_size", "?"),
                "quant": m.get("details", {}).get("quantization_level", "?"),
            } for m in models]
        except Exception:
            return []

    def pull_model(self, name: str):
        """从 Ollama 拉取模型"""
        print(f"  正在拉取模型: {name}")
        print(f"  {'='*50}")
        try:
            with self._session.post(
                f"{self.api_base}/api/pull",
                json={"name": name, "stream": True},
                stream=True, timeout=300,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if line:
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            if "downloading" in status:
                                total = data.get("total", 0)
                                completed = data.get("completed", 0)
                                if total:
                                    pct = completed / total * 100
                                    bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
                                    print(f"\r  [{bar}] {pct:.0f}% {self._format_size(completed)}/{self._format_size(total)}", end="")
                                else:
                                    print(f"\r  {status}", end="")
                            elif status == "success":
                                print("\n  完成！")
                                break
                            else:
                                print(f"\r  {status}")
                        except json.JSONDecodeError:
                            pass
            _clear_model_cache()
        except Exception as e:
            logger.exception("模型拉取失败")
            print(f"  拉取失败: {e}")

    def _format_size(self, size: int) -> str:
        from .utils import format_size
        return format_size(size)

    def clear_history(self):
        self.conversation_history = []
        print("  对话历史已清空")
