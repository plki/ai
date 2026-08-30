"""调度器测试 - cron 表达式解析与任务查找"""
from datetime import datetime, timedelta
from pathlib import Path

from src.scheduler import Scheduler
from src.task_automation import TaskAutomation


class TestCronEval:
    def setup_method(self):
        self.sched = Scheduler()

    def test_no_cron(self):
        assert self.sched._should_run("", None, datetime.now()) is False

    def test_first_run_minutes(self):
        now = datetime.now()
        assert self.sched._should_run("5m", None, now) is True

    def test_not_due_yet(self):
        now = datetime.now()
        last = now - timedelta(minutes=2)
        assert self.sched._should_run("5m", last, now) is False

    def test_due_after_interval(self):
        now = datetime.now()
        last = now - timedelta(minutes=6)
        assert self.sched._should_run("5m", last, now) is True

    def test_hours(self):
        now = datetime.now()
        last = now - timedelta(hours=2)
        assert self.sched._should_run("1h", last, now) is True
        last2 = now - timedelta(minutes=30)
        assert self.sched._should_run("1h", last2, now) is False

    def test_days(self):
        now = datetime.now()
        last = now - timedelta(days=2)
        assert self.sched._should_run("1d", last, now) is True

    def test_invalid_cron(self):
        assert self.sched._should_run("abc", None, datetime.now()) is False


class TestTaskLookup:
    def test_run_by_index(self, capsys, tmp_path: Path):
        ta = TaskAutomation()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        tasks_file = config_dir / "tasks.json"
        tasks_file.write_text(
            '{"tasks": [{"name": "系统信息", "type": "builtin", "handler": "system_info"}]}',
            encoding="utf-8",
        )
        ta.tasks_file = tasks_file
        ta.tasks = ta._load_tasks()
        ta.run_task("1")
        out = capsys.readouterr().out
        assert "操作系统" in out

    def test_run_by_name(self, tmp_path: Path):
        ta = TaskAutomation()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        tasks_file = config_dir / "tasks.json"
        tasks_file.write_text(
            '{"tasks": [{"name": "测试任务", "type": "builtin", "handler": "system_info"}]}',
            encoding="utf-8",
        )
        ta.tasks_file = tasks_file
        ta.tasks = ta._load_tasks()
        assert ta.tasks["tasks"][0]["name"] == "测试任务"

    def test_missing_task(self, capsys, tmp_path: Path):
        ta = TaskAutomation()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        tasks_file = config_dir / "tasks.json"
        tasks_file.write_text('{"tasks": []}', encoding="utf-8")
        ta.tasks_file = tasks_file
        ta.tasks = ta._load_tasks()
        ta.run_task("不存在")
        out = capsys.readouterr().out
        assert "未找到任务" in out
