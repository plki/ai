"""
模型管理模块 - 从 HuggingFace / ModelScope 下载和部署本地模型
"""
import os
import json
import requests
import hashlib
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# HuggingFace 镜像站
HF_MIRRORS = [
    "https://hf-mirror.com",
    "https://huggingface.co",
]

class ModelManager:
    def __init__(self):
        self.config_path = Path(__file__).parent.parent / "config" / "config.json"
        self.config = self._load_config()
        self.models_dir = self._resolve_path(
            Path(self.config.get("models", {}).get("download_dir", "data/models"))
        )
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # 推荐的小模型列表（方便一键下载）
        self.recommended_models = [
            {
                "name": "Qwen2.5-0.5B-Instruct-GGUF",
                "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
                "size": "~350MB",
                "desc": "阿里通义千问 0.5B (轻量, 中文强)",
            },
            {
                "name": "Llama-3.2-1B-Instruct-Q4",
                "repo": "hugging-quants/Llama-3.2-1B-Instruct-Q4_K_M-GGUF",
                "file": "llama-3.2-1b-instruct-q4_k_m.gguf",
                "size": "~700MB",
                "desc": "Meta Llama 3.2 1B (英文强)",
            },
            {
                "name": "TinyLlama-1.1B-Chat-GGUF",
                "repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                "file": "tinyllama-1.1b-chat-v1.0-q4_k_m.gguf",
                "size": "~700MB",
                "desc": "TinyLlama 1.1B (均衡)",
            },
            {
                "name": "DeepSeek-R1-Distill-Qwen-1.5B",
                "repo": "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
                "file": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
                "size": "~1GB",
                "desc": "DeepSeek R1 蒸馏版 (推理强)",
            },
        ]

    def _load_config(self):
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _resolve_path(self, path: Path) -> Path:
        if not path.is_absolute():
            return Path(__file__).parent.parent / path
        return path

    def _get_mirror(self) -> str:
        """获取可用的镜像站"""
        return self.config.get("models", {}).get(
            "huggingface_mirror", HF_MIRRORS[0]
        )

    def list_models(self):
        """列出已下载的模型"""
        print(f"\n{Fore.CYAN}📦 已下载的模型{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        models = list(self.models_dir.iterdir()) if self.models_dir.exists() else []
        if not models:
            print(f"{Fore.YELLOW}  暂无已下载的模型{Style.RESET_ALL}")
            print(f"{Fore.WHITE}  使用 'model search' 查看推荐模型{Style.RESET_ALL}")
            return

        for model in sorted(models):
            if model.is_dir():
                size = self._get_size(model)
                size_str = self._format_size(size)
                info_file = model / "info.json"
                if info_file.exists():
                    try:
                        info = json.load(open(info_file, 'r', encoding='utf-8'))
                        status = info.get("status", "未知")
                        if status == "completed":
                            status_tag = f"{Fore.GREEN}[OK]{Style.RESET_ALL}"
                        elif status == "downloading":
                            status_tag = f"{Fore.YELLOW}⏳{Style.RESET_ALL}"
                        else:
                            status_tag = f"{Fore.WHITE}📦{Style.RESET_ALL}"
                    except:
                        status_tag = f"{Fore.WHITE}📦{Style.RESET_ALL}"
                else:
                    status_tag = f"{Fore.WHITE}📦{Style.RESET_ALL}"
                print(f"  {status_tag} {Fore.BLUE}{model.name}{Style.RESET_ALL}  {Fore.YELLOW}{size_str}{Style.RESET_ALL}")

        print(f"\n{Fore.CYAN}总计: {len(models)} 个模型{Style.RESET_ALL}")

    def search_models(self, keyword: str = ""):
        """显示推荐模型列表"""
        print(f"\n{Fore.CYAN}🔍 推荐模型{Style.RESET_ALL}")
        if keyword:
            print(f"{Fore.WHITE}搜索关键词: {keyword}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        filtered = self.recommended_models
        if keyword:
            keyword_lower = keyword.lower()
            filtered = [
                m for m in filtered
                if keyword_lower in m["name"].lower()
                or keyword_lower in m["desc"].lower()
            ]

        if not filtered:
            print(f"{Fore.YELLOW}  未找到匹配的模型{Style.RESET_ALL}")
            return

        for i, model in enumerate(filtered, 1):
            print(f"\n  {Fore.GREEN}{i}. {model['name']}{Style.RESET_ALL}")
            print(f"     {Fore.WHITE}📝 {model['desc']}{Style.RESET_ALL}")
            print(f"     {Fore.YELLOW}📦 大小: {model['size']}{Style.RESET_ALL}")
            print(f"     {Fore.CYAN}📂 仓库: {model['repo']}{Style.RESET_ALL}")

        print(f"\n{Fore.GREEN}使用 'model download <名称>' 开始下载！{Style.RESET_ALL}")

    def download_model(self, name_or_index: str):
        """下载模型（支持名称或编号）"""
        # 按编号查找
        if name_or_index.isdigit():
            idx = int(name_or_index) - 1
            if 0 <= idx < len(self.recommended_models):
                model_info = self.recommended_models[idx]
            else:
                print(f"{Fore.RED}[X] 无效编号: {name_or_index}{Style.RESET_ALL}")
                return
        else:
            # 按名称查找
            matches = [m for m in self.recommended_models
                      if name_or_index.lower() in m["name"].lower()]
            if not matches:
                print(f"{Fore.RED}[X] 未找到模型: {name_or_index}{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}  使用 'model search' 查看可用模型列表{Style.RESET_ALL}")
                return
            model_info = matches[0]

        name = model_info["name"]
        repo = model_info["repo"]
        filename = model_info["file"]

        model_dir = self.models_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)
        file_path = model_dir / filename

        # 写 info.json
        info = {
            "name": name,
            "repo": repo,
            "file": filename,
            "status": "downloading",
            "download_time": str(datetime.now()),
        }
        with open(model_dir / "info.json", 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        # 构建下载 URL
        mirror = self._get_mirror()
        url = f"{mirror}/{repo}/resolve/main/{filename}"
        print(f"\n{Fore.CYAN}📥 开始下载: {name}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   源: {url}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   保存到: {file_path}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        success = self._download_file(url, file_path)

        if success:
            info["status"] = "completed"
            info["completed_time"] = str(datetime.now())
            with open(model_dir / "info.json", 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            print(f"\n{Fore.GREEN}[OK] 模型下载完成！{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   路径: {file_path}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   大小: {self._format_size(file_path.stat().st_size)}{Style.RESET_ALL}")
        else:
            info["status"] = "failed"
            with open(model_dir / "info.json", 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=2)

    def _download_file(self, url: str, dest: Path) -> bool:
        """下载文件带进度条"""
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024 * 1024  # 1MB chunks

            with open(dest, 'wb') as f:
                with tqdm(
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    desc=f"{Fore.GREEN}下载中{Style.RESET_ALL}",
                    bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=block_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            return True

        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}[X] 下载失败: {e}{Style.RESET_ALL}")
            if dest.exists():
                dest.unlink()
            return False

    def delete_model(self, name: str):
        """删除模型"""
        model_dir = self.models_dir / name
        if not model_dir.exists():
            print(f"{Fore.RED}[X] 模型不存在: {name}{Style.RESET_ALL}")
            return

        import shutil
        size = self._get_size(model_dir)
        confirm = input(f"{Fore.YELLOW}确定删除 '{name}' ({self._format_size(size)})? (y/n): {Style.RESET_ALL}")
        if confirm.lower() == 'y':
            shutil.rmtree(model_dir)
            print(f"{Fore.GREEN}[OK] 已删除: {name}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")

    def _get_size(self, path: Path) -> int:
        total = 0
        try:
            for f in path.rglob('*'):
                if f.is_file():
                    total += f.stat().st_size
        except (PermissionError, OSError):
            pass
        return total

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
