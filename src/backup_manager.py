"""
备份管理模块 - 目录备份与恢复
"""
import os
import shutil
import json
import zipfile
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style
from tqdm import tqdm


class BackupManager:
    def __init__(self):
        self.backup_root = Path(__file__).parent.parent / "data" / "backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.index_file = self.backup_root / "backup_index.json"
        self.index = self._load_index()

    def _load_index(self):
        if self.index_file.exists():
            try:
                return json.load(open(self.index_file, 'r', encoding='utf-8'))
            except:
                pass
        index = {"backups": []}
        self._save_index(index)
        return index

    def _save_index(self, index=None):
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index or self.index, f, ensure_ascii=False, indent=2)

    def backup_directory(self, source_path: str, name: str = None) -> bool:
        """备份指定目录"""
        source = Path(source_path).resolve()
        if not source.exists():
            print(f"{Fore.RED}[X] 路径不存在: {source}{Style.RESET_ALL}")
            return False

        if not source.is_dir():
            print(f"{Fore.RED}[X] 请指定目录，而非文件: {source}{Style.RESET_ALL}")
            return False

        if not name:
            name = source.name

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{name}_{timestamp}"
        backup_dir = self.backup_root / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{Fore.CYAN}📦 备份: {source}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   目标: {backup_dir}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        # 先压缩备份
        zip_path = str(backup_dir) + ".zip"
        total_size = sum(f.stat().st_size for f in source.rglob('*') if f.is_file())

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                files = list(source.rglob('*'))
                with tqdm(total=len(files), desc="备份中", unit="个") as pbar:
                    for f in files:
                        if f.is_file():
                            arcname = str(f.relative_to(source.parent))
                            zf.write(f, arcname)
                        pbar.update(1)

            backup_info = {
                "name": name,
                "source": str(source),
                "backup_path": zip_path,
                "timestamp": timestamp,
                "size": os.path.getsize(zip_path),
                "files_count": len(files),
            }

            self.index["backups"].append(backup_info)
            self._save_index()

            size_str = self._format_size(backup_info["size"])
            print(f"\n{Fore.GREEN}[OK] 备份完成！{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   文件: {zip_path}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   大小: {size_str}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   数量: {len(files)} 个文件{Style.RESET_ALL}")

            # 删除临时目录
            shutil.rmtree(backup_dir, ignore_errors=True)
            return True

        except Exception as e:
            print(f"{Fore.RED}[X] 备份失败: {e}{Style.RESET_ALL}")
            shutil.rmtree(backup_dir, ignore_errors=True)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            return False

    def list_backups(self):
        """列出所有备份"""
        print(f"\n{Fore.CYAN}📦 备份列表{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        backups = self.index.get("backups", [])
        if not backups:
            print(f"{Fore.YELLOW}  暂无备份{Style.RESET_ALL}")
            return

        for i, b in enumerate(reversed(backups), 1):
            ts = b.get("timestamp", "")
            size = self._format_size(b.get("size", 0))
            name = b.get("name", "未知")
            source = b.get("source", "")
            print(f"  {Fore.GREEN}{i}. {name}{Style.RESET_ALL}")
            print(f"     {Fore.WHITE}📅 {ts}  📦 {size}{Style.RESET_ALL}")
            print(f"     {Fore.CYAN}📂 {source}{Style.RESET_ALL}")

    def restore(self, index: int, dest: str = None):
        """恢复备份"""
        backups = self.index.get("backups", [])
        if not backups or index < 1 or index > len(backups):
            print(f"{Fore.RED}[X] 无效的备份编号{Style.RESET_ALL}")
            return

        b = backups[index - 1]
        zip_path = b.get("backup_path", "")

        if not os.path.exists(zip_path):
            print(f"{Fore.RED}[X] 备份文件不存在: {zip_path}{Style.RESET_ALL}")
            return

        dest_path = Path(dest) if dest else Path(b.get("source", "."))
        dest_path.mkdir(parents=True, exist_ok=True)

        print(f"\n{Fore.CYAN}🔄 恢复备份: {b['name']}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   到: {dest_path}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(dest_path)
            print(f"{Fore.GREEN}[OK] 恢复完成！{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[X] 恢复失败: {e}{Style.RESET_ALL}")

    def auto_backup(self, path: str = None, interval_hours: int = 24):
        """设置自动备份（返回定时任务配置）"""
        if not path:
            path = str(Path.home() / "Documents")
        config = {
            "type": "auto_backup",
            "source": path,
            "interval_hours": interval_hours,
        }
        config_path = Path(__file__).parent.parent / "config" / "auto_backup.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"{Fore.GREEN}[OK] 自动备份已配置: 每 {interval_hours} 小时备份 {path}{Style.RESET_ALL}")

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
