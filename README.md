# 智能桌面助手 (AI Desktop Assistant)

一个 AI 驱动的命令行桌面助手，支持本地模型对话、文件管理、任务自动化、Web 抓取与备份恢复。

## 功能特性

- **AI 对话** — 集成 Ollama 本地模型，支持原生 function calling（自动调用工具）
- **模型管理** — 搜索、下载和部署本地 GGUF 模型，一键拉取 Ollama 模型
- **文件管理** — 智能文件整理、搜索、批量操作
- **任务自动化** — 内置系统/磁盘/进程任务，支持自定义命令任务
- **Web 工具** — 网页抓取、搜索、文件下载
- **备份恢复** — 目录压缩备份与安全恢复（含路径穿越防护）
- **定时任务** — 后台调度器，支持分钟/小时/天间隔

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python main.py
```

Windows 用户可直接双击 `install.bat`（一键安装 + Ollama 引导）和 `launcher.bat`（一键启动）。

## 项目结构

```
├── main.py                # 入口文件（跨平台）
├── install.bat            # Windows 一键安装脚本
├── launcher.bat           # Windows 一键启动脚本
├── pull_qwen.py           # 单独拉取 qwen 中文模型
├── requirements.txt       # 依赖清单
├── pyproject.toml         # 工程配置（现代打包/工具）
├── src/                   # 核心代码
│   ├── cli.py             # CLI 交互界面
│   ├── ai_engine.py       # AI 引擎（Ollama function calling）
│   ├── file_manager.py    # 文件管理
│   ├── model_manager.py   # 模型管理
│   ├── web_automation.py  # Web 自动化
│   ├── task_automation.py # 任务自动化
│   ├── scheduler.py       # 定时任务
│   ├── backup_manager.py  # 备份管理
│   ├── ui.py              # rich 终端美化
│   └── utils.py           # 公共工具（路径/格式化/JSON/日志）
├── config/                # 配置文件
└── tests/                 # pytest 单测
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `chat` | 进入 AI 聊天模式 |
| `chat ask <问题>` | 一次性提问 |
| `file list/find/sort` | 文件浏览/搜索/整理 |
| `web fetch/search/download` | 网页抓取/搜索/下载 |
| `model list/search/download/pull` | 模型管理 |
| `task list/run/add` | 任务自动化 |
| `backup <路径> [名称]` \| `backup list` | 备份 |
| `schedule list/add/remove/start/stop` | 定时任务 |

也可以直接输入自然语言（如"查看系统信息"、"整理桌面"），助手会自动匹配或调用 AI 处理。

## 配置

见 `config/config.json`。主要项：
- `ai.ollama_host` — Ollama API 地址
- `ai.max_history` — 对话历史最大条数（防止内存增长）
- `models.huggingface_mirror` — 模型下载镜像站

## 开发

```bash
# 运行测试
python -m pytest

# 静态检查
python -m ruff check src/ tests/
```

## 常见问题

- **"Ollama 未运行"**：安装并启动 [Ollama](https://ollama.com/download)，或使用 `launcher.bat`。
- **无可用模型**：运行 `ollama pull qwen2.5:0.5b` 或 `model pull qwen2.5:0.5b`。
- **跨平台**：本项目适配 Windows / macOS / Linux，Windows 专属功能会按平台自动降级。
