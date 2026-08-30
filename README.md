# 智能桌面助手 (AI Desktop Assistant)

一个 AI 驱动的桌面助手，支持本地 Ollama 与自己的云端 API，提供命令行与网页双界面。AI 会先思考并提出执行计划，经你确认后再操作。

## 功能特性

- **AI 对话（双引擎）** — 本地 Ollama + 任意 OpenAI 兼容云端 API（DeepSeek / 通义 / Moonshot / OpenAI 等）
- **思考→确认→执行** — AI 提出计划后先展示，你确认才真正执行工具，安全可控
- **双界面** — 命令行（rich 美化）与网页版（浏览器访问，SSE 流式输出）
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

# 命令行界面
python main.py

# 网页界面（浏览器访问 http://localhost:7860）
python main.py web
```

Windows 用户可直接双击 `install.bat`（一键安装 + Ollama 引导）和 `launcher.bat`（一键启动）。

## 使用自己的云端 API

支持任意 OpenAI 兼容接口（可自定义 Base URL、端口、API Key、模型名）：

```bash
# 在 CLI 中配置
config provider cloud
config api https://api.deepseek.com/v1 sk-你的key deepseek-chat

# 或直接修改 config/config.json
# "ai": { "provider": "cloud", "cloud": { "base_url": "...", "api_key": "...", "model": "..." } }
```

网页版：点击左下角「设置」，填入 Base URL / API Key / 模型名即可；也可直接在顶栏模型选择器中切换云端 / 本地模型。

云端模式也支持 function calling 工具调用，与本地 Ollama 体验一致。

### 网页版特色（v0.6.0）

- **多会话管理**：左侧会话列表，支持新建、切换、删除，类似 DeepSeek 聊天界面
- **历史持久化**：对话自动保存到 `data/conversations/`，刷新页面不丢失，可继续聊天
- **Markdown 渲染 + 代码高亮**：AI 回复中的表格、代码块、列表自动美化（内置解析器，无需联网）
- **模型选择器**：顶栏一键切换云端模型 / 本地 Ollama 模型

## 思考→确认→执行 模式

默认开启。当 AI 决定调用工具时，会先展示执行计划：

```
[计划] 将执行以下操作:
  -> 查看系统信息
  是否执行? (y/n):
```

- 输入 `y` 执行，`n` 取消
- 关闭确认：`config confirm off`（AI 自动执行）
- 网页版会在对话中弹出「允许执行 / 拒绝」按钮

## 项目结构

```
├── main.py                # 入口文件（CLI / web 启动）
├── install.bat            # Windows 一键安装脚本
├── launcher.bat           # Windows 一键启动脚本
├── pull_qwen.py           # 单独拉取 qwen 中文模型
├── requirements.txt       # 依赖清单
├── pyproject.toml         # 工程配置（现代打包/工具）
├── src/                   # 核心代码
│   ├── cli.py             # CLI 交互界面
│   ├── ai_engine.py       # AI 引擎（Ollama + 云端双 provider）
│   ├── web_server.py      # 网页版服务器（Flask + SSE）
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
| `config show` | 查看当前 AI 配置 |
| `config provider cloud\|ollama\|auto` | 切换 AI 提供方 |
| `config api <url> <key> <模型>` | 配置自己的云端 API |
| `config confirm on\|off` | 开关「执行前确认」 |
| `web serve` | 启动网页版界面 |
| `file list/find/sort` | 文件浏览/搜索/整理 |
| `web fetch/search/download` | 网页抓取/搜索/下载 |
| `model list/search/download/pull` | 模型管理 |
| `task list/run/add` | 任务自动化 |
| `backup <路径> [名称]` \| `backup list` | 备份 |
| `schedule list/add/remove/start/stop` | 定时任务 |

也可以直接输入自然语言（如"查看系统信息"、"整理桌面"），助手会自动匹配或调用 AI 处理。

## 配置

见 `config/config.json`。主要项：
- `ai.provider` — `auto`（云端优先）/ `cloud` / `ollama`
- `ai.cloud` — 云端 API 的 base_url / api_key / model / timeout
- `ai.confirm_tools` — 是否在 AI 执行工具前确认（默认 true）
- `ai.ollama_host` — 本地 Ollama API 地址
- `ai.max_history` — 对话历史最大条数（防止内存增长）
- `web.host` / `web.port` — 网页版监听地址与端口（默认 7860）
- `models.huggingface_mirror` — 模型下载镜像站

## 开发

```bash
# 运行测试
python -m pytest

# 静态检查
python -m ruff check src/ tests/
```

## 常见问题

- **"未配置 AI 模型"**：在「设置」中配置云端 API，或安装并启动 [Ollama](https://ollama.com/download) 后 `ollama pull qwen2.5:0.5b`。
- **云端 API 报认证失败**：检查 API Key 是否正确、余额是否充足。
- **跨平台**：本项目适配 Windows / macOS / Linux，Windows 专属功能会按平台自动降级。
