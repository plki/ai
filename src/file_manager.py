"""
文件管理模块 - 文件浏览、搜索、整理
"""
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style

from .utils import dir_size, format_size


class FileManager:
    def __init__(self):
        self.current_dir = Path.cwd()

    def list_files(self, path: str = "."):
        """列出目录内容"""
        target = Path(path).resolve()
        if not target.exists():
            print(f"{Fore.RED}[X] 路径不存在: {target}{Style.RESET_ALL}")
            return
        if not target.is_dir():
            print(f"{Fore.RED}[X] 不是目录: {target}{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}📁 目录: {target}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        # 按类型分组
        dirs = []
        files = []
        try:
            for item in target.iterdir():
                if item.is_dir():
                    dirs.append(item)
                else:
                    files.append(item)
        except PermissionError:
            print(f"{Fore.RED}[X] 没有权限访问该目录{Style.RESET_ALL}")
            return

        # 显示目录
        for d in sorted(dirs):
            size_info = format_size(dir_size(d))
            print(f"  {Fore.BLUE}📂 {d.name}/{Style.RESET_ALL}  {Fore.WHITE}{size_info}{Style.RESET_ALL}")

        # 显示文件
        for f in sorted(files):
            try:
                size = f.stat().st_size
                modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                continue
            print(f"  {Fore.GREEN}📄 {f.name}{Style.RESET_ALL}  {Fore.YELLOW}{format_size(size)}{Style.RESET_ALL}  {Fore.WHITE}{modified}{Style.RESET_ALL}")

        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}总计: {len(dirs)} 个目录, {len(files)} 个文件{Style.RESET_ALL}")

    def find_files(self, keyword: str, search_path: str = "."):
        """搜索文件"""
        target = Path(search_path).resolve()
        print(f"\n{Fore.CYAN}🔍 正在搜索: {keyword} 在 {target}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        count = 0
        max_results = 50
        try:
            for item in target.rglob(f"*{keyword}*"):
                if count >= max_results:
                    print(f"{Fore.YELLOW}...(显示前 {max_results} 条结果){Style.RESET_ALL}")
                    break
                try:
                    if item.is_file():
                        size_str = format_size(item.stat().st_size)
                        print(f"  {Fore.GREEN}📄 {item.relative_to(target)}{Style.RESET_ALL}  {Fore.YELLOW}{size_str}{Style.RESET_ALL}")
                    else:
                        print(f"  {Fore.BLUE}📂 {item.relative_to(target)}/{Style.RESET_ALL}")
                except OSError:
                    continue
                count += 1
        except PermissionError:
            pass

        if count == 0:
            print(f"{Fore.YELLOW}  未找到匹配的文件{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}找到 {count} 个结果{Style.RESET_ALL}")

    def sort_files_by_type(self, path: str = "."):
        """按文件类型整理"""
        target = Path(path).resolve()
        if not target.is_dir():
            print(f"{Fore.RED}[X] 无效目录: {target}{Style.RESET_ALL}")
            return

        # 安全保护：拒绝整理项目自身目录
        project_dir = Path(__file__).parent.parent.resolve()
        if target == project_dir:
            print(f"{Fore.RED}[X] 不能整理项目自身目录!{Style.RESET_ALL}")
            return

        # 文件类型分类映射
        type_map = {
            "图片": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico'],
            "文档": ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.pdf', '.txt', '.md'],
            "压缩包": ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
            "视频": ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv'],
            "音频": ['.mp3', '.wav', '.flac', '.aac', '.ogg'],
            "代码": ['.py', '.js', '.ts', '.html', '.css', '.java', '.cpp', '.c', '.h', '.rs', '.go'],
            "可执行文件": ['.exe', '.msi', '.bat', '.cmd', '.ps1'],
        }

        print(f"\n{Fore.CYAN}📁 正在整理: {target}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        moved = 0
        for item in target.iterdir():
            if item.is_file():
                ext = item.suffix.lower()
                for category, exts in type_map.items():
                    if ext in exts:
                        dest_dir = target / category
                        dest_dir.mkdir(exist_ok=True)
                        try:
                            import shutil
                            shutil.move(str(item), str(dest_dir / item.name))
                        except OSError as e:
                            print(f"  {Fore.RED}移动失败: {item.name} ({e}){Style.RESET_ALL}")
                            break
                        moved += 1
                        print(f"  {Fore.GREEN}📄 {item.name} → {category}/{Style.RESET_ALL}")
                        break

        if moved == 0:
            print(f"{Fore.YELLOW}  没有需要整理的文件{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}已整理 {moved} 个文件{Style.RESET_ALL}")
