# 智能桌面助手 (AI Desktop Assistant)

一个 AI 驱动的命令行桌面助手，支持本地模型部署、文件管理和自动化任务。

## 功能特性

- **🤖 本地模型管理** — 下载和部署 AI 模型，一键运行
- **📁 文件管理** — 智能文件整理、搜索、批量操作
- **⚡ 自动化任务** — 自动执行重复性操作
- **💬 智能对话** — 自然语言交互

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 项目结构

```
E:\aiyidai\
├── main.py               # 入口文件
├── requirements.txt      # 依赖清单
├── README.md             # 说明文档
├── src/                  # 核心代码
│   ├── cli.py            # CLI 交互界面
│   ├── file_manager.py   # 文件管理模块
│   ├── model_manager.py  # 模型管理模块
│   └── task_automation.py # 任务自动化模块
├── config/               # 配置文件
└── data/                 # 数据目录
    ├── models/           # 下载的模型
    └── temp/             # 临时文件
```
