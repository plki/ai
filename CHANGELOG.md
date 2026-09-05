# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-09-05

### Added

- **API 中转站** (`src/relay.py`)
  - 管理员在网页配置上游主 API（Base URL + API Key + 模型）
  - 创建/编辑/删除子 API Key，外部调用方使用子 Key 访问
  - 配额控制：调用次数上限、Token 总量上限、并发上限、每日调用上限
  - 完整调用日志（JSONL），支持按子 API 名称筛选
  - 路径穿越防护：所有路径操作使用 `resolve()` 规范化

- **官网全新升级**（独立仓库 [ai-desktop-assistant-website](https://github.com/plki/ai-desktop-assistant-website)）
  - 神经网络动态背景（Canvas 粒子连线动效）
  - 明暗双模式主题切换
  - 全功能展示：功能特性、工作原理、免费开源、云端版本、产品对比、常见问题、CTA
  - 响应式布局，移动端优化

- **产品 logo 更新**
  - 纯色圆角背景 + 白色 "A" 字母 + AI 节点图案
  - 提供 PNG（256x256）和 SVG 矢量格式
  - 更新网站侧边栏和桌面端展示图

- **网页版访问口令** (`config web-token <口令>`)
  - 设置后访问 `/web` 需验证口令，无口令者无法进入

- **测试覆盖**
  - `tests/test_relay.py`：432 行，覆盖中转站全流程
  - `tests/test_web_server.py`：增强测试用例

### Changed

- **品牌重塑**：产品名从"智能桌面助手"改为英文品牌 **AI Desktop Assistant**
- **网页版 UI**：侧边栏可关闭（点击关闭按钮隐藏），移动端 375px 完美适配
- **备份恢复**（`src/backup_manager.py`）：强化路径穿越防护，仅解压安全成员
- **README.md**：品牌名、截图、功能描述全面更新
- `.gitignore`：排除 `__pycache__/`，避免污染仓库

### Fixed

- API 中转面板 JS 引号转义问题（导致脚本注入/失效）
- 侧边栏无法关闭与设置入口在特定分辨率下不可见
- 多项安全与逻辑 bug
