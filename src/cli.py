"""
CLI 交互界面 - 智能桌面助手的命令行入口
集成 AI 对话、文件管理、Web 自动化、任务调度、备份
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime
from colorama import init, Fore, Style
from rich.console import Console
from rich import box

# UTF-8 编码
if sys.stdout.encoding and sys.stdout.encoding.upper() != 'UTF-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

init(autoreset=True)

from . import ui

console = Console()

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_banner():
    """打印启动界面"""
    from . import ui as ui_mod
    ui_mod.print_banner_rich()

    # 检查 Ollama 状态（快速检测）
    try:
        import requests
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if models:
                names = ", ".join(m["name"] for m in models[:3])
                ui_mod.print_success(f"AI: {names}")
            else:
                ui_mod.print_warning("Ollama 已连接但无模型")
        else:
            ui_mod.print_error("Ollama 连接异常")
    except:
        ui_mod.print_warning("Ollama 未运行 (AI 功能不可用)")

    console.print()
    console.print("[bold green][?] help 查看命令  |  chat 进入聊天模式  |  exit 退出[/bold green]")
    console.print()


def print_help():
    """打印帮助信息"""
    sections = [
        ("[chat] AI 对话", [
            ("chat", "进入 AI 聊天模式（自然对话 + 自动调用工具）"),
            ("chat ask <问题>", "一次性提问，不进入聊天模式"),
            ("chat models", "查看可用的 AI 模型"),
        ]),
        ("[file] 文件管理", [
            ("file list [路径]", "列出目录内容"),
            ("file find <关键词> [路径]", "搜索文件"),
            ("file sort [路径]", "按类型自动整理文件"),
        ]),
        ("[web] Web 功能", [
            ("web fetch <URL>", "获取网页内容"),
            ("web search <关键词>", "搜索信息"),
            ("web download <URL> [文件名]", "下载文件"),
            ("web deploy <URL>", "自动识别并部署应用"),
        ]),
        ("[AI] 模型管理", [
            ("model list", "列出已下载的模型"),
            ("model search [关键词]", "搜索推荐模型"),
            ("model download <名称/编号>", "下载模型"),
            ("model pull <名称>", "从 Ollama 拉取 AI 模型"),
        ]),
        ("[task] 任务自动化", [
            ("task list", "查看可用任务（8个内置任务）"),
            ("task run <名称/编号>", "运行任务"),
            ("task add <名> <描述> <命令>", "添加自定义任务"),
        ]),
        ("[backup] 备份管理", [
            ("backup <路径> [名称]", "备份指定目录"),
            ("backup list", "查看所有备份"),
        ]),
        ("[schedule] 定时任务", [
            ("schedule list", "查看定时任务"),
            ("schedule add", "添加定时任务"),
        ]),
        ("[system] 系统", [
            ("help", "显示此帮助"),
            ("clear", "清屏"),
            ("exit", "退出"),
        ]),
    ]
    ui.print_help_rich(sections)


def run_cli():
    """CLI 主循环"""
    import sys
    config = load_config()
    print_banner()

    while True:
        try:
            sys.stdout.flush()
            cmd = input(f"\n{Fore.CYAN}[AI] > {Style.RESET_ALL}").strip()
            if not cmd:
                continue

            parts = cmd.split()
            action = parts[0].lower()

            if action == "exit":
                print(f"\n{Fore.YELLOW}[再见] 下次再来玩~{Style.RESET_ALL}", flush=True)
                break

            elif action == "help":
                print_help()

            elif action == "clear":
                os.system('cls' if os.name == 'nt' else 'clear')
                print_banner()

            elif action == "chat":
                handle_chat_command(parts[1:])

            elif action == "file":
                handle_file_command(parts[1:])

            elif action == "model":
                handle_model_command(parts[1:])

            elif action == "web":
                handle_web_command(parts[1:])

            elif action == "task":
                handle_task_command(parts[1:])

            elif action == "backup":
                handle_backup_command(parts[1:])

            elif action == "schedule":
                handle_schedule_command(parts[1:])

            else:
                # 自然语言：先尝试关键词匹配，否则交给 AI
                if not handle_natural_language(cmd):
                    print(f"{Fore.YELLOW}[?] 不理解: \"{cmd}\"{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}  试试: help 查看命令 | chat 进入聊天模式{Style.RESET_ALL}")

        except EOFError:
            # stdin 断开（管道重定向结束）
            print(f"\n{Fore.YELLOW}[再见]{Style.RESET_ALL}", flush=True)
            break
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}[再见]{Style.RESET_ALL}", flush=True)
            break
        except Exception as e:
            print(f"{Fore.RED}[?] 出错了: {e}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()


# ========== 命令处理器 ==========

def handle_chat_command(args):
    """聊天模式"""
    from .ai_engine import AIEngine

    if args and args[0] == "ask":
        # 单次提问
        question = " ".join(args[1:])
        if not question:
            print(f"{Fore.RED}用法: chat ask <问题>{Style.RESET_ALL}")
            return
        ai = AIEngine()
        print(f"\n{Fore.CYAN}[chat] AI 思考中...{Style.RESET_ALL}", flush=True)
        for chunk in ai.chat(question):
            print(chunk, end="", flush=True)
        print()

    elif args and args[0] == "models":
        # 查看可用模型
        ai = AIEngine()
        models = ai.list_available_models()
        if models:
            print(f"\n{Fore.CYAN}[AI] 可用 AI 模型{Style.RESET_ALL}", flush=True)
            print(f"{Fore.WHITE}{'='*55}{Style.RESET_ALL}")
            for i, m in enumerate(models, 1):
                print(f"  {Fore.GREEN}{i}. {m['name']}{Style.RESET_ALL}")
                print(f"     {Fore.WHITE}参数: {m['params']}  |  量化: {m['quant']}  |  大小: {m['size']}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[!] 未检测到模型，请先安装 Ollama 并拉取模型{Style.RESET_ALL}")

    else:
        if args:
            print(f"{Fore.RED}未知子命令: {args[0]} (支持: ask, models){Style.RESET_ALL}")
            return
        # 进入聊天模式
        ai = AIEngine()
        if not ai.model:
            print(f"{Fore.RED}[?] 没有可用的 AI 模型，请先拉取模型{Style.RESET_ALL}")
            return

        # 进入聊天模式前刷新缓冲区
        import sys
        sys.stdout.flush()

        from rich.panel import Panel
        chat_panel = Panel(
            f"[bold green][chat] AI 聊天模式[/bold green]  [dim](模型: {ai.model})[/dim]\n"
            f"[white]直接和我聊天吧！我可以帮你查信息、整理文件、执行任务...[/white]\n"
            f"[yellow]输入 /exit 退出  |  /clear 清空历史  |  /help 查看提示[/yellow]",
            box=box.HEAVY,
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(chat_panel)

        while True:
            try:
                sys.stdout.flush()
                user_input = input(f"\n{Fore.MAGENTA}[chat] 你说 > {Style.RESET_ALL}").strip()
                if not user_input:
                    continue

                if user_input == "/exit":
                    break
                elif user_input == "/clear":
                    ai.clear_history()
                    continue
                elif user_input == "/help":
                    print(f"{Fore.YELLOW}[tip] 提示: 直接说你想做什么就行{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}   例如: 帮我整理桌面 | 备份我的文档 | 查看系统信息 | 搜索 Python 教程{Style.RESET_ALL}")
                    continue

                print(f"\n{Fore.CYAN}[AI] AI 回复:{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}[wait] 思考中...{Style.RESET_ALL}", end="", flush=True)
                full_reply = ""
                for chunk in ai.chat(user_input):
                    if chunk.strip():
                        if full_reply == "":
                            print("\r" + " " * 40 + "\r", end="", flush=True)
                        print(chunk, end="", flush=True)
                        full_reply += chunk
                print()
                if not full_reply.strip():
                    print(f"{Fore.YELLOW}（AI 没有返回内容，可能是模型响应超时）{Style.RESET_ALL}")

            except EOFError:
                # stdin 断开（管道/重定向结束），退出聊天模式
                break
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[退出聊天模式]{Style.RESET_ALL}")
                break


def handle_file_command(args):
    from .file_manager import FileManager
    fm = FileManager()
    if not args:
        print(f"{Fore.RED}用法: file list|find|sort [参数]{Style.RESET_ALL}")
        return
    sub = args[0].lower()
    if sub == "list":
        fm.list_files(args[1] if len(args) > 1 else ".")
    elif sub == "find":
        if len(args) < 2:
            print(f"{Fore.RED}请指定搜索关键词{Style.RESET_ALL}")
            return
        fm.find_files(args[1], args[2] if len(args) > 2 else ".")
    elif sub == "sort":
        fm.sort_files_by_type(args[1] if len(args) > 1 else ".")
    else:
        print(f"{Fore.RED}未知子命令: {sub}{Style.RESET_ALL}")


def handle_model_command(args):
    from .model_manager import ModelManager
    mm = ModelManager()

    if not args:
        print(f"{Fore.RED}用法: model list|search|download|pull [参数]{Style.RESET_ALL}")
        return
    sub = args[0].lower()
    if sub == "list":
        mm.list_models()
    elif sub == "search":
        mm.search_models(args[1] if len(args) > 1 else "")
    elif sub == "download":
        if len(args) < 2:
            print(f"{Fore.RED}请指定模型名称或编号{Style.RESET_ALL}")
            return
        mm.download_model(args[1])
    elif sub == "pull":
        from .ai_engine import AIEngine
        ai = AIEngine()
        name = args[1] if len(args) > 1 else ""
        if not name:
            print(f"{Fore.RED}用法: model pull <模型名> (如: qwen2.5:0.5b){Style.RESET_ALL}")
            return
        ai.pull_model(name)
    else:
        print(f"{Fore.RED}未知子命令: {sub}{Style.RESET_ALL}")


def handle_web_command(args):
    from .web_automation import WebAutomation
    wa = WebAutomation()
    if not args:
        print(f"{Fore.RED}用法: web fetch|download|search|deploy [参数]{Style.RESET_ALL}")
        return
    sub = args[0].lower()
    if sub == "fetch":
        if len(args) < 2:
            print(f"{Fore.RED}请指定 URL{Style.RESET_ALL}")
            return
        wa.fetch_page(args[1])
    elif sub == "download":
        if len(args) < 2:
            print(f"{Fore.RED}请指定 URL{Style.RESET_ALL}")
            return
        wa.download_file(args[1], args[2] if len(args) > 2 else None)
    elif sub == "search":
        if len(args) < 2:
            print(f"{Fore.RED}请指定搜索关键词{Style.RESET_ALL}")
            return
        wa.search(" ".join(args[1:]))
    elif sub == "deploy":
        if len(args) < 2:
            print(f"{Fore.RED}请指定 URL{Style.RESET_ALL}")
            return
        wa.deploy_from_url(args[1])
    else:
        print(f"{Fore.RED}未知子命令: {sub}{Style.RESET_ALL}")


def handle_task_command(args):
    from .task_automation import TaskAutomation
    ta = TaskAutomation()
    if not args:
        print(f"{Fore.RED}用法: task list|run|add [参数]{Style.RESET_ALL}")
        return
    sub = args[0].lower()
    if sub == "list":
        ta.list_tasks()
    elif sub == "run":
        if len(args) < 2:
            print(f"{Fore.RED}请指定任务名称或编号{Style.RESET_ALL}")
            return
        ta.run_task(args[1])
    elif sub == "add":
        if len(args) < 4:
            print(f"{Fore.RED}用法: task add <名称> <描述> <命令>{Style.RESET_ALL}")
            return
        ta.add_task(args[1], args[2], " ".join(args[3:]))
    else:
        print(f"{Fore.RED}未知子命令: {sub}{Style.RESET_ALL}")


def handle_backup_command(args):
    from .backup_manager import BackupManager
    bm = BackupManager()
    if not args:
        print(f"{Fore.RED}用法: backup <路径> [名称] | backup list{Style.RESET_ALL}")
        return
    if args[0] == "list":
        bm.list_backups()
    else:
        name = args[1] if len(args) > 1 else None
        bm.backup_directory(args[0], name)


def handle_schedule_command(args):
    from .scheduler import Scheduler
    s = Scheduler()
    if not args:
        print(f"{Fore.RED}用法: schedule list|add|remove|start|stop{Style.RESET_ALL}")
        return
    sub = args[0].lower()
    if sub == "list":
        s.list_tasks()
    elif sub == "add":
        print(f"{Fore.CYAN}[memo] 添加定时任务（简易版）{Style.RESET_ALL}")
        name = input("  任务名称: ").strip()
        task_type = input("  类型 (backup/command/cleanup): ").strip()
        if task_type == "backup":
            source = input("  要备份的目录: ").strip()
            s.add_task(name, "backup", {"source": source}, "24h")
        elif task_type == "command":
            cmd = input("  要执行的命令: ").strip()
            s.add_task(name, "command", {"command": cmd}, "1h")
        elif task_type == "cleanup":
            s.add_task(name, "cleanup", {}, "24h")
        else:
            print(f"{Fore.RED}不支持的類型{Style.RESET_ALL}")
    elif sub == "remove":
        if len(args) < 2:
            print(f"{Fore.RED}请指定任务 ID{Style.RESET_ALL}")
            return
        s.remove_task(int(args[1]))
    elif sub == "start":
        s.start()
    elif sub == "stop":
        s.stop()
    else:
        print(f"{Fore.RED}未知子命令: {sub}{Style.RESET_ALL}")


def handle_natural_language(text: str) -> bool:
    """自然语言理解（关键词匹配 + AI 兜底）"""
    text_lower = text.lower()

    # 问候
    if any(kw in text for kw in ["你好", "嗨", "hi", "hello", "在吗"]):
        print(f"\n{Fore.GREEN}你好！我是智能桌面助手 [AI]")
        print(f"{Fore.WHITE}我可以帮你管理文件、下载模型、查信息、执行任务...")
        print(f"{Fore.WHITE}输入 chat 进入聊天模式，或者直接告诉我想做什么！{Style.RESET_ALL}")
        return True

    # 文件操作
    if any(kw in text for kw in ["列出文件", "目录", "文件夹", "有什么文件"]):
        from .file_manager import FileManager
        path = text.split()[-1] if any(c in text for c in ":\\/") else "."
        FileManager().list_files(path)
        return True

    if any(kw in text for kw in ["搜索文件", "查找文件", "找文件"]):
        from .file_manager import FileManager
        keyword = text.replace("搜索文件", "").replace("查找文件", "").replace("找文件", "").strip()
        if keyword:
            FileManager().find_files(keyword)
        else:
            print(f"{Fore.YELLOW}搜索什么？例如: 搜索文件 report.pdf{Style.RESET_ALL}")
        return True

    if "整理" in text and ("文件" in text or "桌面" in text or "目录" in text):
        from .file_manager import FileManager
        # 找路径
        parts = text.split()
        path = None
        for i, p in enumerate(parts):
            if p in ["桌面", "下载", "文档"]:
                if p == "桌面":
                    path = str(Path.home() / "Desktop")
                elif p == "下载":
                    path = str(Path.home() / "Downloads")
                elif p == "文档":
                    path = str(Path.home() / "Documents")
                break
        FileManager().sort_files_by_type(path or ".")
        return True

    # Web 操作
    if text.startswith("http://") or text.startswith("https://"):
        from .web_automation import WebAutomation
        WebAutomation().fetch_page(text)
        return True

    if any(kw in text for kw in ["搜索", "查一下", "搜一下"]):
        from .web_automation import WebAutomation
        keyword = text.replace("搜索", "").replace("查一下", "").replace("搜一下", "").strip()
        if keyword:
            WebAutomation().search(keyword)
        else:
            print(f"{Fore.YELLOW}搜什么？例如: 搜索 Python教程{Style.RESET_ALL}")
        return True

    if "下载" in text and any(w.startswith("http") for w in text.split()):
        from .web_automation import WebAutomation
        url = [w for w in text.split() if w.startswith("http")][0]
        WebAutomation().download_file(url)
        return True

    # 系统操作
    if any(kw in text for kw in ["系统信息", "电脑配置", "本机信息", "配置"]):
        from .task_automation import TaskAutomation
        ta = TaskAutomation()
        ta.run_task("系统信息")
        return True

    if any(kw in text for kw in ["清理垃圾", "清理", "加速"]):
        from .task_automation import TaskAutomation
        ta = TaskAutomation()
        ta.run_task("清理临时文件")
        return True

    if any(kw in text for kw in ["磁盘", "硬盘", "空间"]):
        from .task_automation import TaskAutomation
        ta = TaskAutomation()
        ta.run_task("磁盘分析")
        return True

    if "网络" in text and ("诊断" in text or "测" in text or "检查" in text):
        from .task_automation import TaskAutomation
        ta = TaskAutomation()
        ta.run_task("网络诊断")
        return True

    if any(kw in text for kw in ["进程", "任务管理器", "运行的程序"]):
        from .task_automation import TaskAutomation
        ta = TaskAutomation()
        ta.run_task("进程列表")
        return True

    # 模型操作
    if any(kw in text for kw in ["下载模型", "模型下载", "安装模型"]):
        from .model_manager import ModelManager
        ModelManager().search_models()
        return True

    if any(kw in text for kw in ["模型列表", "已下载的模型", "我的模型"]):
        from .model_manager import ModelManager
        ModelManager().list_models()
        return True

    # 备份
    if "备份" in text:
        from .backup_manager import BackupManager
        bm = BackupManager()
        # 找路径
        parts = text.split()
        for i, p in enumerate(parts):
            if p in ["桌面", "下载", "文档"]:
                from pathlib import Path
                if p == "桌面":
                    bm.backup_directory(str(Path.home() / "Desktop"))
                elif p == "下载":
                    bm.backup_directory(str(Path.home() / "Downloads"))
                elif p == "文档":
                    bm.backup_directory(str(Path.home() / "Documents"))
                return True
        bm.list_backups()
        return True

    # 帮助
    if any(kw in text for kw in ["你能做什么", "功能", "你可以"]):
        print_help()
        return True

    if any(kw in text for kw in ["谢谢", "感谢", "thank"]):
        print(f"{Fore.YELLOW}不客气！有什么需要随时叫我 [:)]{Style.RESET_ALL}")
        return True

    # 都不匹配，返回 False 让主循环提示
    return False


if __name__ == "__main__":
    run_cli()
