"""
调度器模块 - 定时任务管理
"""
import subprocess
import threading
import time
from datetime import datetime

from colorama import Fore, Style

from .utils import PROJECT_ROOT, get_logger, load_json, save_json

logger = get_logger("scheduler")


class Scheduler:
    def __init__(self):
        self.schedule_file = PROJECT_ROOT / "config" / "schedule.json"
        self.tasks = self._load_tasks()
        self._running = False
        self._thread = None

    def _load_tasks(self):
        data = load_json(self.schedule_file, None)
        if data is None:
            data = {"tasks": []}
            save_json(self.schedule_file, data)
        if not isinstance(data.get("tasks"), list):
            data["tasks"] = []
        return data

    def _save(self, data=None):
        save_json(self.schedule_file, data or self.tasks)

    def add_task(self, name: str, task_type: str, config: dict, cron: str):
        """添加定时任务"""
        task = {
            "id": self._next_id(),
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

    def _next_id(self) -> int:
        ids = [t.get("id", 0) for t in self.tasks.get("tasks", [])]
        return max(ids, default=0) + 1

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
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="scheduler")
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
                    try:
                        last_dt = datetime.fromisoformat(last_run)
                    except ValueError:
                        last_dt = None
                else:
                    last_dt = None

                cron = task.get("cron", "")
                if self._should_run(cron, last_dt, now):
                    self._execute_task(task)

            time.sleep(30)  # 每 30 秒检查一次

    @staticmethod
    def _should_run(cron: str, last_dt, now: datetime) -> bool:
        """解析简化版 cron 表达式（支持 m/h/d 间隔）"""
        if not cron:
            return False
        try:
            if cron.endswith("m"):
                minutes = int(cron[:-1])
                return not last_dt or (now - last_dt).total_seconds() >= minutes * 60
            if cron.endswith("h"):
                hours = int(cron[:-1])
                return not last_dt or (now - last_dt).total_seconds() >= hours * 3600
            if cron.endswith("d"):
                days = int(cron[:-1])
                return not last_dt or (now - last_dt).total_seconds() >= days * 86400
        except ValueError:
            return False
        return False

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
                    shell=True, capture_output=True, text=True, timeout=60,
                )
                print(f"  命令执行完成 (code={result.returncode})")

            elif task_type == "cleanup":
                from .task_automation import TaskAutomation
                TaskAutomation().run_task("清理临时文件")

            # 更新最后运行时间
            task["last_run"] = str(datetime.now())
            self._save()

        except Exception as e:
            logger.exception("定时任务执行失败")
            print(f"{Fore.RED}  [X] 任务执行失败: {e}{Style.RESET_ALL}")
