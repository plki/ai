# AI 云聊 · Cloudflare 免费部署版

这是「智能桌面助手」网页版的**云聊天版**，面向不需要安装、直接用浏览器访问的用户。

- 纯前端界面 + Cloudflare Pages Functions（API 中转）
- 支持任意 OpenAI 兼容接口（DeepSeek / 通义 / Moonshot / OpenAI 等）
- SSE 流式输出、Markdown 渲染、代码高亮、多会话历史（浏览器 localStorage）
- API Key 只保存在用户自己的浏览器，不上传服务器

## 目录结构

```
cloudflare/
├── public/                 # 静态前端（浏览器直接加载）
│   └── index.html
├── functions/
│   └── api/
│       ├── chat.js         # POST /api/chat  → OpenAI 兼容 /chat/completions (SSE 流式)
│       └── models.js       # GET  /api/models → 拉取模型列表
├── wrangler.toml           # Cloudflare Pages 配置
└── README.md
```

## 部署到 Cloudflare（免费）

### 方式一：Git 连接（推荐，自动构建）

1. 打开 https://dash.cloudflare.com 并登录
2. 左侧菜单进入 **Workers 与 Pages** → **创建** → **Pages** → **连接到 Git**
3. 选择本仓库（`plki/ai`），框架预设选 **None**，构建命令留空，构建输出目录留空
4. 在「配置」里把 **根目录** 设为 `cloudflare`（重要，这样 `functions/` 才会被识别）
5. 点击 **保存并部署**，稍等片刻即得到 `https://<项目名>.pages.dev` 地址

> **重要警告：不要填写「部署命令」。** 如果填了 `npx wrangler deploy`，它是 Workers 的命令，而且会在仓库根目录执行（读不到本目录的 `wrangler.toml`），会报错 `Missing entry-point to Worker script or to assets directory`。Git 连接方式留空部署命令即可，Cloudflare 会自动构建。
>
> 若确实要用部署命令（不推荐），必须同时满足：根目录设为 `cloudflare`，命令填 `npx wrangler pages deploy`。

### 方式二：Wrangler CLI 上传

```bash
# 需要先安装 wrangler 并登录（免费）
npm install -g wrangler
wrangler login

# 部署（在 cloudflare 目录内执行）
cd cloudflare
wrangler pages deploy . --project-name ai-cloud-chat
```

部署完成后即可访问 `https://ai-cloud-chat.pages.dev`。

## 使用说明

1. 打开部署好的页面，点右上角 **设置**
2. 填写你的 **Base URL**（如 `https://api.deepseek.com/v1`）、**API Key**、**模型名**（如 `deepseek-chat`）
3. 保存后即可对话。支持流式输出、多会话切换、Markdown 与代码高亮

> API Key 仅存入访问者浏览器 localStorage；中转函数不持久化任何 Key 或对话内容。

## 免费额度

- Cloudflare Workers/Pages Functions：每天 10 万请求免费
- 静态资源：无限流量
- 个人开发 / 小规模分享完全够用
