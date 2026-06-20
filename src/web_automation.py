"""
Web 自动化模块 - 网页抓取、应用部署
"""
import os
import re
import requests
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from colorama import Fore, Style
from bs4 import BeautifulSoup
from tqdm import tqdm

class WebAutomation:
    def __init__(self):
        self.download_dir = Path(__file__).parent.parent / "data" / "downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def fetch_page(self, url: str):
        """获取网页内容"""
        print(f"\n{Fore.CYAN}🌐 正在访问: {url}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or 'utf-8'

            soup = BeautifulSoup(resp.text, 'html.parser')

            # 提取页面信息
            title = soup.title.string.strip() if soup.title else "无标题"
            print(f"{Fore.GREEN}📄 标题: {title}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}📏 大小: {len(resp.text):,} 字符{Style.RESET_ALL}")

            # 提取链接
            links = soup.find_all('a', href=True)
            valid_links = [l for l in links if l['href'].strip() and not l['href'].startswith('#')]
            print(f"{Fore.WHITE}🔗 链接数: {len(valid_links)}{Style.RESET_ALL}")

            # 提取下载链接
            downloads = self._find_download_links(soup, url)
            if downloads:
                print(f"\n{Fore.YELLOW}📥 发现可下载资源:{Style.RESET_ALL}")
                for i, d in enumerate(downloads[:10], 1):
                    print(f"  {Fore.GREEN}{i}. {d['name']}{Style.RESET_ALL}")
                    print(f"     {Fore.WHITE}   {d['url']}{Style.RESET_ALL}")

            return {
                "title": title,
                "content": resp.text,
                "links": valid_links[:20],
                "downloads": downloads,
            }

        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}[X] 访问失败: {e}{Style.RESET_ALL}")
            return None

    def download_file(self, url: str, filename: str = None):
        """从 URL 下载文件"""
        if not filename:
            # 从 URL 提取文件名
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "downloaded_file"
            # 清理文件名
            filename = re.sub(r'[\\/*?:"<>|]', '_', filename)

        dest = self.download_dir / filename
        print(f"\n{Fore.CYAN}📥 下载文件: {filename}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}   源: {url}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        try:
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()

            total_size = int(resp.headers.get('content-length', 0))
            block_size = 1024 * 1024

            with open(dest, 'wb') as f:
                with tqdm(
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    desc="下载中",
                    bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
                ) as pbar:
                    for chunk in resp.iter_content(chunk_size=block_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            size = dest.stat().st_size
            print(f"\n{Fore.GREEN}[OK] 下载完成！{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   路径: {dest}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   大小: {self._format_size(size)}{Style.RESET_ALL}")
            return str(dest)

        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}[X] 下载失败: {e}{Style.RESET_ALL}")
            return None

    def deploy_from_url(self, url: str):
        """从 URL 部署应用（自动识别并安装）"""
        print(f"\n{Fore.CYAN}🚀 正在分析: {url}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        page = self.fetch_page(url)
        if not page:
            return

        soup = BeautifulSoup(page['content'], 'html.parser')
        text = soup.get_text().lower()

        # 识别部署类型
        deploy_type = self._detect_deploy_type(url, text)

        if deploy_type == "python_package":
            self._deploy_python_package(url)
        elif deploy_type == "github_repo":
            self._deploy_github_repo(url)
        elif deploy_type == "exe_installer":
            self._deploy_exe(url)
        elif deploy_type == "web_app":
            print(f"{Fore.GREEN}🌐 这是一个网页应用，直接打开即可使用{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   URL: {url}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}❓ 无法自动识别部署类型{Style.RESET_ALL}")
            print(f"{Fore.WHITE}   你可以手动指定: pip/github/exe/npm{Style.RESET_ALL}")

    def _find_download_links(self, soup, base_url):
        """查找页面中的下载链接"""
        downloads = []
        download_keywords = ['download', '下载', '.exe', '.msi', '.zip', '.tar.gz']

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            text = (a_tag.get_text() or '').strip()

            # 补全相对路径
            if href.startswith('/'):
                parsed = urlparse(base_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif not href.startswith('http'):
                continue

            # 检查是否是下载链接
            is_download = any(kw in href.lower() or kw in text.lower()
                            for kw in download_keywords)
            if is_download:
                downloads.append({
                    'name': text or os.path.basename(href),
                    'url': href,
                })

        return downloads

    def _detect_deploy_type(self, url, page_text):
        """检测部署类型"""
        if 'pypi.org' in url or 'pypi' in page_text:
            return "python_package"
        elif 'github.com' in url:
            return "github_repo"
        elif '.exe' in url or '.msi' in url:
            return "exe_installer"
        elif any(kw in page_text for kw in ['web app', 'website', '在线工具']):
            return "web_app"
        return "unknown"

    def _deploy_python_package(self, url):
        """部署 Python 包"""
        print(f"\n{Fore.CYAN}🐍 正在安装 Python 包...{Style.RESET_ALL}")
        try:
            package_name = url.rstrip('/').split('/')[-1]
            result = subprocess.run(
                f"pip install {package_name} -q",
                shell=True, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                print(f"{Fore.GREEN}[OK] 安装成功: {package_name}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[X] 安装失败: {result.stderr}{Style.RESET_ALL}")
        except subprocess.TimeoutExpired:
            print(f"{Fore.RED}[X] 安装超时{Style.RESET_ALL}")

    def _deploy_github_repo(self, url):
        """部署 GitHub 仓库"""
        print(f"\n{Fore.CYAN}📦 正在处理 GitHub 仓库...{Style.RESET_ALL}")

        # 检查 git 是否可用
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"{Fore.YELLOW}[!] 未安装 Git，尝试直接下载 ZIP{Style.RESET_ALL}")
            zip_url = url.rstrip('/') + "/archive/refs/heads/main.zip"
            self.download_file(zip_url)
            return

        repo_name = url.rstrip('/').split('/')[-1]
        dest = self.download_dir / repo_name
        if dest.exists():
            print(f"{Fore.YELLOW}  仓库已存在: {dest}{Style.RESET_ALL}")
            return

        print(f"  正在克隆: {url}")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            print(f"{Fore.GREEN}[OK] 克隆成功: {dest}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[X] 克隆失败: {result.stderr}{Style.RESET_ALL}")

    def _deploy_exe(self, url):
        """下载并提示安装 exe"""
        path = self.download_file(url)
        if path:
            print(f"\n{Fore.YELLOW}💡 文件已下载到: {path}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}💡 是否现在运行安装程序? (y/n){Style.RESET_ALL}")
            # 这个交互留给用户手动操作

    def search(self, keyword: str, max_results: int = 5):
        """简易网页搜索（使用 DuckDuckGo 或直接抓取）"""
        print(f"\n{Fore.CYAN}🔍 搜索: {keyword}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'='*60}{Style.RESET_ALL}")

        search_url = f"https://html.duckduckgo.com/html/?q={keyword}"
        try:
            resp = requests.get(search_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            results = soup.select('.result__body')
            if not results:
                # 备选：直接展示前几个链接
                links = soup.find_all('a', href=True)
                count = 0
                for link in links:
                    href = link['href']
                    if href.startswith('http') and count < max_results:
                        text = link.get_text().strip() or href
                        print(f"  {Fore.GREEN}{count+1}. {text[:80]}{Style.RESET_ALL}")
                        print(f"     {Fore.WHITE}{href}{Style.RESET_ALL}")
                        count += 1
            else:
                for i, result in enumerate(results[:max_results], 1):
                    title_el = result.select_one('.result__title a')
                    snippet_el = result.select_one('.result__snippet')
                    title = title_el.get_text().strip() if title_el else "无标题"
                    url = title_el['href'] if title_el and title_el.get('href') else ""
                    snippet = snippet_el.get_text().strip() if snippet_el else ""
                    print(f"  {Fore.GREEN}{i}. {title}{Style.RESET_ALL}")
                    print(f"     {Fore.WHITE}{snippet[:100]}{Style.RESET_ALL}")
                    print(f"     {Fore.CYAN}{url}{Style.RESET_ALL}")

            print(f"\n{Fore.GREEN}使用 'web open <编号>' 打开链接查看详情{Style.RESET_ALL}")

        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}[X] 搜索失败: {e}{Style.RESET_ALL}")

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
