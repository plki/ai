"""
任务自动化模块 - 预设任务 & 自定义任务管理
"""
import os
import json
import subprocess
import psutil
import platform
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style

class TaskAutomation:
    def __init__(self):
        self.tasks_file = Path(__file__).parent.parent / "config" / "tasks.json"
        self.tasks = self._load_tasks()

    def _load_tasks(self):
        """加载任务列表"""
        default_tasks = {
            "tasks": [
                {
                    "name": "系统信息",
                    "description": "查看操作系统、CPU、内存信息",
                    "type": "builtin",
                    "handler": "system_info"
                },
                {
                    "name": "磁盘分析",
                    "description": "查看各磁盘使用情况",
                    "type": "command",
                    "command": "wmic logicaldisk get caption,size,freespace /format:table"
                },
                {
                    "name": "清理临时文件",
                    "description": "删除 Windows 临时文件释放空间",
                    "type": "command",
                    "command": "del /f /s /q %temp%\\* >nul 2>&1 & echo 临时文件已清理"
                },
                {
                    "name": "网络诊断",
                    "description": "测试网络连通性 (ping 114.114.114.114)",
                    "type": "command",
                    "command": "ping 114.114.114.114 -n 4"
                },
                {
                    "name": "进程列表",
                    "description": "查看当前运行的进程 (按内存排序 Top 10)",
                    "type": "builtin",
                    "handler": "process_list"
                },
                {
                    "name": "关机定时",
                    "description": "设置定时关机 (默认 30 分钟后)",
                    "type": "command",
                    "command": "shutdown /s /t 1800"
                },
                {
                    "name": "取消关机",
                    "description": "取消已设置的定时关机",
                    "type": "command",
                    "command": "shutdown /a"
                },
                {
                    "name": "WiFi 密码查看",
                    "description": "查看当前连接的 WiFi 密码",
                    "type": "command",
                    "command": "netsh wlan show profile name=* key=clear | findstr /R \"^.*配置文件.*$ ^.*关键内容.*$\""
                },
            ]
        }

        if self.tasks_file.exists():
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        with open(self.tasks_file, 'w', encoding='utf-8') as f:
            json.dump(default_tasks, f, ensure_ascii=False, indent=2)
        return default_tasks

    def list_tasks(self):
        """列出所有可用任务"""
        print(f"\n{Fore.CYAN}📋 可用任务列表{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        tasks = self.tasks.get("tasks", [])
        if not tasks:
            print(f"{Fore.YELLOW}  暂无可用任务{Style.RESET_ALL}")
            return

        for i, task in enumerate(tasks, 1):
            tag = ""
            t = task.get("type", "")
            if t == "builtin":
                tag = f"{Fore.MAGENTA}[内置]{Style.RESET_ALL}"
            elif t == "command":
                tag = f"{Fore.CYAN}[命令]{Style.RESET_ALL}"

            print(f"  {Fore.GREEN}{i:2d}. {task['name']}{Style.RESET_ALL}  {tag}")
            print(f"      {Fore.WHITE}{task['description']}{Style.RESET_ALL}")

        print(f"\n{Fore.GREEN}使用 'task run <名称/编号>' 运行任务{Style.RESET_ALL}")
        print(f"{Fore.GREEN}使用 'task add <名称> <描述> <命令>' 添加自定义任务{Style.RESET_ALL}")

    def run_task(self, name_or_index: str):
        """运行指定任务"""
        tasks = self.tasks.get("tasks", [])
        task = None

        # 按编号查找
        if name_or_index.isdigit():
            idx = int(name_or_index) - 1
            if 0 <= idx < len(tasks):
                task = tasks[idx]

        # 按名称查找
        if not task:
            for t in tasks:
                if name_or_index.lower() in t["name"].lower():
                    task = t
                    break

        if not task:
            print(f"{Fore.RED}[X] 未找到任务: {name_or_index}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}  使用 'task list' 查看可用任务{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}▶️  执行任务: {task['name']}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}📝 {task['description']}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        task_type = task.get("type", "command")
        try:
            if task_type == "builtin":
                handler = task.get("handler", "")
                if handler == "system_info":
                    self._handle_system_info()
                elif handler == "process_list":
                    self._handle_process_list()
                else:
                    print(f"{Fore.RED}[X] 未知的内置任务: {handler}{Style.RESET_ALL}")

            elif task_type == "command":
                result = subprocess.run(
                    task["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(f"{Fore.YELLOW}{result.stderr}{Style.RESET_ALL}")
                status = Fore.GREEN if result.returncode == 0 else Fore.RED
                print(f"{status}[OK] 任务完成 (返回码: {result.returncode}){Style.RESET_ALL}")

            else:
                print(f"{Fore.RED}[X] 不支持的任务类型: {task_type}{Style.RESET_ALL}")

        except subprocess.TimeoutExpired:
            print(f"{Fore.RED}[X] 任务超时 (>60秒){Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[X] 任务失败: {e}{Style.RESET_ALL}")

    def add_task(self, name: str, description: str, command: str):
        """添加自定义任务"""
        new_task = {
            "name": name,
            "description": description,
            "type": "command",
            "command": command,
        }
        self.tasks["tasks"].append(new_task)
        self._save_tasks()
        print(f"{Fore.GREEN}[OK] 任务已添加: {name}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   描述: {description}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   命令: {command}{Style.RESET_ALL}")

    def _handle_system_info(self):
        """内置：显示系统信息"""
        info = [
            ("操作系统", f"{platform.system()} {platform.version()}"),
            ("主机名", platform.node()),
            ("处理器", platform.processor()),
            ("CPU 核心", f"{psutil.cpu_count(logical=True)} 逻辑核心"),
            ("CPU 使用率", f"{psutil.cpu_percent(interval=0.5)}%"),
            ("内存总量", self._format_size(psutil.virtual_memory().total)),
            ("内存可用", self._format_size(psutil.virtual_memory().available)),
            ("内存使用率", f"{psutil.virtual_memory().percent}%"),
            ("Python 版本", platform.python_version()),
        ]

        max_key = max(len(k) for k, _ in info)
        for key, val in info:
            print(f"  {Fore.CYAN}{key.rjust(max_key)}{Style.RESET_ALL} : {Fore.WHITE}{val}{Style.RESET_ALL}")

    def _handle_process_list(self):
        """内置：按内存排序显示 Top 10 进程"""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory': proc.info['memory_info'].rss if proc.info['memory_info'] else 0,
                    'cpu': proc.info['cpu_percent'] or 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        processes.sort(key=lambda p: p['memory'], reverse=True)

        print(f"  {'PID':<8} {'内存':<10} {'CPU':<8} {'名称'}")
        print(f"  {'---':<8} {'----':<10} {'---':<8} {'----'}")
        for p in processes[:10]:
            mem = self._format_size(p['memory'])
            print(f"  {Fore.GREEN}{p['pid']:<8}{Style.RESET_ALL} "
                  f"{Fore.YELLOW}{mem:<10}{Style.RESET_ALL} "
                  f"{Fore.WHITE}{p['cpu']:<8.1f}{Style.RESET_ALL} "
                  f"{p['name']}")

    def _save_tasks(self):
        with open(self.tasks_file, 'w', encoding='utf-8') as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
