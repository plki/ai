"""备份管理器测试 - 备份/恢复/路径穿越防护"""
import zipfile
from pathlib import Path

from src.backup_manager import BackupManager
from src.utils import DATA_PATH


class TestBackupManager:
    def setup_method(self):
        # 使用独立备份目录，避免污染真实数据
        self.bm = BackupManager()
        self.bm.backup_root = DATA_PATH / "_test_backups"
        self.bm.backup_root.mkdir(parents=True, exist_ok=True)
        self.bm.index_file = self.bm.backup_root / "backup_index.json"
        self.bm.index = {"backups": []}

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.bm.backup_root, ignore_errors=True)

    def test_backup_creates_zip(self, tmp_path: Path):
        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("hello", encoding="utf-8")
        ok = self.bm.backup_directory(str(src))
        assert ok is True
        assert self.bm.index["backups"]
        zip_path = Path(self.bm.index["backups"][-1]["backup_path"])
        assert zip_path.exists()

    def test_backup_missing_dir(self, tmp_path: Path, capsys):
        ok = self.bm.backup_directory(str(tmp_path / "missing"))
        assert ok is False

    def test_restore_preserves_content(self, tmp_path: Path):
        src = tmp_path / "data"
        src.mkdir()
        (src / "note.txt").write_text("restore me", encoding="utf-8")
        self.bm.backup_directory(str(src))

        dest = tmp_path / "out"
        self.bm.restore(len(self.bm.index["backups"]), dest=str(dest))
        assert (dest / "data" / "note.txt").read_text(encoding="utf-8") == "restore me"

    def test_restore_rejects_path_traversal(self, tmp_path: Path):
        # 构造包含 ../ 的恶意压缩包
        evil_zip = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.write(str(Path(__file__)), "safe.txt")
            zf.writestr("../../escape.txt", "x")

        dest = tmp_path / "dest"
        dest.mkdir()

        # 手动注册一个恶意备份到索引
        self.bm.index["backups"].append({
            "name": "evil",
            "source": str(dest),
            "backup_path": str(evil_zip),
            "timestamp": "20260101_000000",
        })
        self.bm.restore(len(self.bm.index["backups"]), dest=str(dest))

        # 越界文件不应写入目标目录外
        assert not (tmp_path.parent / "escape.txt").exists()
        # 越界条目被跳过，但合法文件仍解压
        assert Path(dest / "safe.txt").exists()
