"""
AI 引擎 - 集成本地 Ollama 模型
优化版：generate API 为主（更快）、qwen 中文模型优先
"""
import json
import time
import requests
import subprocess
import atexit
from typing import Generator, Optional
from colorama import Fore, Style

OLLAMA_HOST = "http://127.0.0.1:11434"

# 全局 session 清理注册表
_ai_instances = []

# 模型列表缓存（避免每次创建 AIEngine 都查 Ollama API）
_model_cache = None


def _register_session(instance):
    _ai_instances.append(instance)


def _cleanup_all_sessions():
    """清理所有资源：HTTP 连接 + 子进程 + 通知 Ollama 卸载模型"""
    # 1. 直接杀 llama-server.exe（最可靠）
    try:
        subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"],
                       capture_output=True, timeout=3)
    except Exception:
        pass

    # 2. 通知 Ollama 卸载模型
    try:
        session = requests.Session()
        for inst in _ai_instances:
            if inst.model:
                session.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": inst.model, "keep_alive": 0},
                    timeout=2
                )
        session.close()
    except Exception:
        pass

    # 3. 关闭所有 HTTP session
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
3. 需要工具时用 <tool>函数(参数=值)</tool> 格式

可用工具：
file_list(path) file_find(keyword,path) file_sort(path)
web_fetch(url) web_search(keyword) web_download(url)
task_run(name) system_info()"""

# 关键词 → 工具映射（在发送给 AI 前先匹配，避免模型瞎编）
# 值格式：(工具名, 参数字典, 可选路径提取函数)
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


class AIEngine:
    def __init__(self, model: str = ""):
        self.api_base = OLLAMA_HOST
        # Session 必须在 _pick_best_model 之前创建
        self._session = requests.Session()
        self.model = model or self._pick_best_model()
        self.conversation_history = []
        self.system_prompt = SYSTEM_PROMPT
        _register_session(self)

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
            resp = self._session.get(f"{self.api_base}/api/tags", timeout=5)
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
                        resp.close()
                        return name
            _model_cache = names[0]
            return names[0]
        except Exception:
            return ""

    def _try_keyword_tool(self, message: str) -> Optional[dict]:
        """在发送给 AI 前，先匹配关键词直接执行工具（避免模型瞎编）"""
        import re, os
        from pathlib import Path

        PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def _extract_path(msg: str) -> str:
            """从消息中提取路径，支持快捷名称（桌面/下载/文档）和盘符路径"""
            # 快捷名称映射
            home = Path.home()
            quick_map = {
                "桌面": str(home / "Desktop"),
                "下载": str(home / "Downloads"),
                "文档": str(home / "Documents"),
            }
            for name, folder in quick_map.items():
                if name in msg:
                    return folder
            # 盘符路径：E:\回忆
            m = re.search(r'([A-Za-z]:\\[^\s]*)', msg)
            if not m:
                return "."
            path = m.group(1)
            # 去掉尾部动作词
            for suffix in ["帮我整理", "帮我排序", "帮我归类", "整理一下", "整理", "排序", "归类",
                           "帮我列出", "列出", "帮我查找", "查找", "搜索", "帮我搜索"]:
                if path.endswith(suffix):
                    path = path[:-len(suffix)]
                    break
            return path if path.strip(":\\/") else "."

        # 特殊处理：整理/排序 → file_sort（需要提取路径）
        if "整理" in message or "排序" in message or "归类" in message:
            path = _extract_path(message)
            # 安全保护：拒绝对自己项目目录整理（仅当显式指定路径时）
            if path != "." and os.path.abspath(path) == PROJECT_DIR:
                print(f"  [!] 不能整理项目自身目录，已跳过")
                return {"name": "noop", "args": {}}
            return {"name": "file_sort", "args": {"path": path}}

        # 特殊处理：列出文件 → file_list（需要提取路径）
        if "列出" in message or "有什么文件" in message or "目录" in message:
            path = _extract_path(message)
            return {"name": "file_list", "args": {"path": path}}

        # 特殊处理：删除空文件 → 直接执行
        if any(kw in message for kw in ["删除空文本", "删除空文件", "清理空文本", "清理空文件",
                                          "删除没有的空文本", "删除没有的空文件"]):
            from pathlib import Path
            home = Path.home()
            # 找桌面上的空 .txt 文件
            desktop = home / "Desktop"
            empty_files = [f for f in desktop.iterdir() if f.is_file() and f.suffix.lower() == ".txt" and f.stat().st_size == 0]
            if empty_files:
                print(f"\n  [找到 {len(empty_files)} 个空文本文件]")
                for f in empty_files:
                    f.unlink()
                    print(f"  已删除: {f.name}")
            else:
                print(f"\n  [桌面没有空文本文件]")
            return {"name": "noop", "args": {}}

        # 特殊处理：打开应用 → 直接启动
        if any(kw in message for kw in ["打开", "启动", "运行"]):
            msg_lower = message.lower()
            # 检测要打开的应用名
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
            launched = False
            for name, cmd in app_map.items():
                if name in msg_lower:
                    import subprocess
                    subprocess.Popen(cmd, shell=True)
                    print(f"\n  [已打开: {name}]")
                    launched = True
                    break
            if launched:
                return {"name": "noop", "args": {}}

        # 常规关键词匹配
        for kw, (tool, args) in KEYWORD_TOOLS.items():
            if kw in message:
                return {"name": tool, "args": args}
        return None

    def chat(self, message: str, stream: bool = True) -> Generator[str, None, None]:
        """与 AI 对话（generate API 为主，比 chat API 快一倍）"""
        if not self.model:
            yield f"\n{Fore.RED}  AI 模型不可用{Style.RESET_ALL}"
            return

        self.conversation_history.append({"role": "user", "content": message})

        # 先尝试关键词匹配（避免模型瞎编）
        tool_call = self._try_keyword_tool(message)
        if tool_call:
            # _execute_tool_and_continue 自己会输出 [执行: xxx]
            yield from self._execute_tool_and_continue(tool_call)
            return

        # 构建对话历史文本（用标记格式防止 AI 输出 "Assistant:" 等）
        history_text = ""
        for m in self.conversation_history[-6:]:
            if m["role"] == "user":
                history_text += f"用户: {m['content']}\n"
            else:
                history_text += f"助手: {m['content']}\n"

        full_prompt = f"{self.system_prompt}\n\n{history_text}助手: "

        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": stream,
            "options": {"temperature": 0.3, "num_predict": 256}
        }

        try:
            resp = self._session.post(
                f"{self.api_base}/api/generate",
                json=payload, stream=stream, timeout=120
            )
            if resp.status_code == 404:
                yield from self._chat_fallback(message, stream)
                return
            resp.raise_for_status()

            full_response = ""
            if stream:
                for line in resp.iter_lines(decode_unicode=True):
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("response", "")
                            full_response += content
                            yield content
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                data = resp.json()
                content = data.get("response", "")
                full_response = content
                yield content

            resp.close()

            if full_response.strip():
                full_response = full_response.strip()
                self.conversation_history.append({
                    "role": "assistant", "content": full_response
                })
                tool_call = self._parse_tool_call(full_response)
                if tool_call:
                    yield from self._execute_tool_and_continue(tool_call)

        except requests.exceptions.ConnectionError:
            yield f"\n  Ollama 未运行"
        except requests.exceptions.Timeout:
            yield f"\n  AI 响应超时（模型较慢），建议换个更小的模型"
        except Exception as e:
            yield f"\n  出错: {e}"

    def _chat_fallback(self, message: str, stream: bool = True):
        """备用方案：使用 chat API"""
        chat_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"【用中文回复】{message}"}
            ],
            "stream": stream,
            "options": {"temperature": 0.3, "num_predict": 256}
        }
        try:
            resp = self._session.post(
                f"{self.api_base}/api/chat",
                json=chat_payload, stream=stream, timeout=120
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
                self.conversation_history.append({
                    "role": "assistant", "content": full_response.strip()
                })
        except Exception:
            yield f"\n  AI 对话失败"

    def ask(self, message: str) -> str:
        """一次性问答"""
        result = ""
        for chunk in self.chat(message, stream=False):
            result += chunk
        return result

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        import re
        # 优先匹配 <tool> 标签格式
        match = re.search(r'<tool>(\w+)\(([^)]*)\)</tool>', text)
        if match:
            tool_name = match.group(1)
            raw_args = match.group(2)
        else:
            # 备选：匹配裸函数调用格式 file_list(path="xxx") 或 function_name()
            match = re.search(r'^(\w+)\(([^)]*)\)\s*$', text.strip())
            if match:
                tool_name = match.group(1)
                raw_args = match.group(2)
            else:
                return None

        args = {}
        if raw_args.strip():
            for part in raw_args.split(","):
                if "=" in part:
                    key, val = part.split("=", 1)
                    args[key.strip()] = val.strip().strip("'\"")
        return {"name": tool_name, "args": args}

    def _execute_tool_and_continue(self, tool_call: dict):
        from .file_manager import FileManager
        from .model_manager import ModelManager
        from .web_automation import WebAutomation
        from .task_automation import TaskAutomation
        from .backup_manager import BackupManager
        name = tool_call["name"]
        args = tool_call["args"]

        # noop = 已由关键词匹配直接处理，不再输出多余信息
        if name == "noop":
            return

        yield f"\n  [执行: {name}] "
        try:
            result = ""
            if name == "file_list":
                FileManager().list_files(args.get("path", "."))
                result = "文件列表已显示"
            elif name == "file_find":
                FileManager().find_files(args.get("keyword", ""), args.get("path", "."))
                result = "搜索结果已显示"
            elif name == "file_sort":
                FileManager().sort_files_by_type(args.get("path", "."))
                result = "文件整理完成"
            elif name == "web_fetch":
                WebAutomation().fetch_page(args.get("url", ""))
                result = "网页内容已获取"
            elif name == "web_search":
                WebAutomation().search(args.get("keyword", ""))
                result = "搜索结果已显示"
            elif name == "web_download":
                WebAutomation().download_file(args.get("url", ""))
                result = "下载完成"
            elif name == "task_run":
                TaskAutomation().run_task(args.get("name", ""))
                result = "任务执行完成"
            elif name == "model_search":
                ModelManager().search_models(args.get("keyword", ""))
                result = "模型列表已显示"
            elif name == "model_download":
                ModelManager().download_model(args.get("name", ""))
                result = "模型下载中"
            elif name == "backup":
                BackupManager().backup_directory(args.get("path", ""))
                result = "备份完成"
            elif name == "system_info":
                TaskAutomation().run_task("系统信息")
                result = "系统信息已显示"
            else:
                result = f"未知工具: {name}"
            yield f"OK. {result}\n"
            yield f"刚刚执行了{name}"
        except Exception as e:
            yield f"\n  执行失败: {e}"

    def list_available_models(self) -> list:
        try:
            resp = self._session.get(f"{self.api_base}/api/tags", timeout=5)
            models = resp.json().get("models", [])
            resp.close()
            return [{
                "name": m["name"],
                "size": self._format_size(m.get("size", 0)),
                "params": m.get("details", {}).get("parameter_size", "?"),
                "quant": m.get("details", {}).get("quantization_level", "?"),
            } for m in models]
        except Exception:
            return []

    def pull_model(self, name: str):
        print(f"  正在拉取模型: {name}")
        print(f"  {'='*50}")
        try:
            resp = self._session.post(
                f"{self.api_base}/api/pull",
                json={"name": name, "stream": True},
                stream=True, timeout=300
            )
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
                            print(f"\n  完成！")
                            break
                        else:
                            print(f"\r  {status}")
                    except json.JSONDecodeError:
                        pass
            resp.close()
        except Exception as e:
            print(f"  拉取失败: {e}")

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def clear_history(self):
        self.conversation_history = []
        print("  对话历史已清空")
