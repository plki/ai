# 智能桌面助手 · 官网

「智能桌面助手」产品官网静态页。纯 HTML + CSS，无构建步骤，可直接部署到 Cloudflare Pages。

## 快速部署（Cloudflare Pages 一键拉取）

方式一：作为独立仓库部署

1. 将本目录推送到 GitHub（新建仓库即可）：

   ```bash
   git init
   git add .
   git commit -m "feat: 智能桌面助手官网"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. 登录 https://dash.cloudflare.com → **Workers 与 Pages** → **创建** → **Pages** → **连接到 Git**
3. 选择刚推送的仓库，配置如下：
   - **框架预设**：None
   - **构建命令**：留空
   - **输出目录**：留空（本目录即为站点根）
4. 点击 **保存并部署**，约 1 分钟后即可通过 `https://<项目名>.pages.dev` 访问。

方式二：放在现有仓库的子目录

- 将本目录放入仓库后推送，Cloudflare Pages 连接同一仓库时，把 **根目录** 设为 `website`，其余配置同上。

## 文件结构

```
website/
├── index.html   # 官网单页（全部样式内联，无需外部资源）
└── README.md    # 本说明
```

## 本地预览

```bash
python3 -m http.server 8000
# 浏览器访问 http://localhost:8000
```