"""
调度器模块 - 定时任务管理
"""
import json
import threading
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from colorama import Fore, Style


class Scheduler:
    def __init__(self):
        self.schedule_file = Path(__file__).parent.parent / "config" / "schedule.json"
        self.tasks = self._load_tasks()
        self._running = False
        self._thread = None

    def _load_tasks(self):
        if self.schedule_file.exists():
            try:
                return json.load(open(self.schedule_file, 'r', encoding='utf-8'))
            except:
                pass
        default = {"tasks": []}
        self._save(default)
        return default

    def _save(self, data=None):
        with open(self.schedule_file, 'w', encoding='utf-8') as f:
            json.dump(data or self.tasks, f, ensure_ascii=False, indent=2)

    def add_task(self, name: str, task_type: str, config: dict, cron: str):
        """添加定时任务"""
        task = {
            "id": len(self.tasks["tasks"]) + 1,
            "name": name,
            "type": task_type,
            "config": config,
            "cron": cron,
            "enabled": True,
            "last_run": None,
            "created": str(datetime.now()),
        }
        self.tasks["tasks"].append(task)
        self._save()
        print(f"{Fore.GREEN}[OK] 定时任务已添加: {name} ({cron}){Style.RESET_ALL}")

    def list_tasks(self):
        """列出定时任务"""
        print(f"\n{Fore.CYAN}⏰ 定时任务列表{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        tasks = self.tasks.get("tasks", [])
        if not tasks:
            print(f"{Fore.YELLOW}  暂无定时任务{Style.RESET_ALL}")
            print(f"{Fore.WHITE}  使用 'schedule add' 添加{Style.RESET_ALL}")
            return

        for t in tasks:
            status = f"{Fore.GREEN}启用{Style.RESET_ALL}" if t.get("enabled") else f"{Fore.RED}禁用{Style.RESET_ALL}"
            last = t.get("last_run", "从未运行") or "从未运行"
            print(f"  {Fore.GREEN}{t['id']}. {t['name']}{Style.RESET_ALL}  [{status}]")
            print(f"     ⏰ 周期: {t['cron']}  |  上次: {last}")
            print(f"     📝 类型: {t['type']}")

    def remove_task(self, task_id: int):
        """删除定时任务"""
        before = len(self.tasks["tasks"])
        self.tasks["tasks"] = [t for t in self.tasks["tasks"] if t["id"] != task_id]
        if len(self.tasks["tasks"]) < before:
            self._save()
            print(f"{Fore.GREEN}[OK] 已删除定时任务 #{task_id}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[X] 未找到定时任务 #{task_id}{Style.RESET_ALL}")

    def start(self):
        """启动调度器（后台线程）"""
        if self._running:
            print(f"{Fore.YELLOW}[!] 调度器已在运行{Style.RESET_ALL}")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"{Fore.GREEN}[OK] 调度器已启动 (后台运行){Style.RESET_ALL}")

    def stop(self):
        """停止调度器"""
        self._running = False
        print(f"{Fore.YELLOW}⏹️  调度器已停止{Style.RESET_ALL}")

    def _run_loop(self):
        """调度器主循环"""
        while self._running:
            now = datetime.now()
            for task in self.tasks.get("tasks", []):
                if not task.get("enabled"):
                    continue

                last_run = task.get("last_run")
                if last_run:
                    last_dt = datetime.fromisoformat(last_run)
                else:
                    last_dt = None

                # 解析 cron 表达式（简化版：仅支持间隔分钟/小时/天）
                cron = task.get("cron", "")
                should_run = False

                if cron.endswith("m"):
                    minutes = int(cron[:-1])
                    if not last_dt or (now - last_dt).total_seconds() >= minutes * 60:
                        should_run = True
                elif cron.endswith("h"):
                    hours = int(cron[:-1])
                    if not last_dt or (now - last_dt).total_seconds() >= hours * 3600:
                        should_run = True
                elif cron.endswith("d"):
                    days = int(cron[:-1])
                    if not last_dt or (now - last_dt).days >= days:
                        should_run = True

                if should_run:
                    self._execute_task(task)

            time.sleep(30)  # 每 30 秒检查一次

    def _execute_task(self, task: dict):
        """执行单个定时任务"""
        print(f"\n{Fore.CYAN}⏰ [调度器] 执行定时任务: {task['name']}{Style.RESET_ALL}")

        try:
            task_type = task.get("type")
            config = task.get("config", {})

            if task_type == "backup":
                from .backup_manager import BackupManager
                bm = BackupManager()
                bm.backup_directory(config.get("source", "."))

            elif task_type == "command":
                result = subprocess.run(
                    config.get("command", ""),
                    shell=True, capture_output=True, text=True, timeout=60
                )
                print(f"  命令执行完成 (code={result.returncode})")

            elif task_type == "cleanup":
                # 清理临时文件
                subprocess.run("del /f /s /q %temp%\\* >nul 2>&1", shell=True)
                subprocess.run("del /f /s /q C:\\Windows\\Temp\\* >nul 2>&1", shell=True)
                print(f"  [OK] 临时文件已清理")

            # 更新最后运行时间
            task["last_run"] = str(datetime.now())
            self._save()

        except Exception as e:
            print(f"{Fore.RED}  [X] 任务执行失败: {e}{Style.RESET_ALL}")
