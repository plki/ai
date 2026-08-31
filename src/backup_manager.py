"""
备份管理模块 - 目录备份与恢复
"""
import os
import zipfile
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style
from tqdm import tqdm

from .utils import DATA_PATH, format_size, get_logger, load_json, save_json

logger = get_logger("backup")


class BackupManager:
    def __init__(self):
        self.backup_root = DATA_PATH / "backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.index_file = self.backup_root / "backup_index.json"
        self.index = self._load_index()

    def _load_index(self):
        data = load_json(self.index_file, None)
        if data is None:
            data = {"backups": []}
            save_json(self.index_file, data)
        if not isinstance(data.get("backups"), list):
            data["backups"] = []
        return data

    def _save_index(self, index=None):
        save_json(self.index_file, index or self.index)

    def backup_directory(self, source_path: str, name: str = None) -> bool:
        """备份指定目录（流式遍历，避免全量载入内存）"""
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
        zip_path = self.backup_root / f"{backup_name}.zip"

        print(f"\n{Fore.CYAN}📦 备份: {source}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   目标: {zip_path}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        file_count = 0
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                pbar = tqdm(desc="备份中", unit="个")
                # 生成器流式遍历：逐文件处理，不把全部路径载入内存
                for f in source.rglob('*'):
                    pbar.update(1)
                    if f.is_file():
                        try:
                            arcname = str(f.relative_to(source.parent))
                            zf.write(f, arcname)
                            file_count += 1
                        except OSError:
                            continue
                pbar.close()

            backup_info = {
                "name": name,
                "source": str(source),
                "backup_path": str(zip_path),
                "timestamp": timestamp,
                "size": os.path.getsize(zip_path),
                "files_count": file_count,
            }

            self.index["backups"].append(backup_info)
            self._save_index()

            size_str = format_size(backup_info["size"])
            print(f"\n{Fore.GREEN}[OK] 备份完成！{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   文件: {zip_path}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   大小: {size_str}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   数量: {file_count} 个文件{Style.RESET_ALL}")
            return True

        except Exception as e:
            logger.exception("备份失败")
            print(f"{Fore.RED}[X] 备份失败: {e}{Style.RESET_ALL}")
            if zip_path.exists():
                try:
                    zip_path.unlink()
                except OSError:
                    pass
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
            size = format_size(b.get("size", 0))
            name = b.get("name", "未知")
            source = b.get("source", "")
            print(f"  {Fore.GREEN}{i}. {name}{Style.RESET_ALL}")
            print(f"     {Fore.WHITE}📅 {ts}  📦 {size}{Style.RESET_ALL}")
            print(f"     {Fore.CYAN}📂 {source}{Style.RESET_ALL}")

    def restore(self, index: int, dest: str = None):
        """恢复备份（带 zip 路径穿越防护）"""
        backups = self.index.get("backups", [])
        if not backups or index < 1 or index > len(backups):
            print(f"{Fore.RED}[X] 无效的备份编号{Style.RESET_ALL}")
            return

        b = backups[index - 1]
        zip_path = Path(b.get("backup_path", ""))

        if not zip_path.exists():
            print(f"{Fore.RED}[X] 备份文件不存在: {zip_path}{Style.RESET_ALL}")
            return

        dest_path = Path(dest).resolve() if dest else Path(b.get("source", ".")).resolve()
        dest_path.mkdir(parents=True, exist_ok=True)

        print(f"\n{Fore.CYAN}🔄 恢复备份: {b['name']}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   到: {dest_path}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # 防路径穿越：规范化后必须落在目标目录内，仅解压安全成员
                safe_members = []
                for member in zf.infolist():
                    target = (dest_path / member.filename).resolve()
                    try:
                        target.relative_to(dest_path)
                    except ValueError:
                        print(f"{Fore.YELLOW}  [跳过] 越界路径: {member.filename}{Style.RESET_ALL}")
                        continue
                    safe_members.append(member)
                zf.extractall(dest_path, members=safe_members)
            print(f"{Fore.GREEN}[OK] 恢复完成！{Style.RESET_ALL}")
        except Exception as e:
            logger.exception("恢复失败")
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
        config_path = DATA_PATH / "auto_backup.json"
        save_json(config_path, config)
        print(f"{Fore.GREEN}[OK] 自动备份已配置: 每 {interval_hours} 小时备份 {path}{Style.RESET_ALL}")
