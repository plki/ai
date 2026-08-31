"""
Web 服务器 - 为智能桌面助手提供 DeepSeek 风格浏览器界面

功能：
- 左侧多会话列表：新建 / 切换 / 删除会话
- 会话历史本地持久化到 data/conversations/
- Markdown 渲染 + 代码高亮（前端内建，无需 CDN）
- 顶栏模型选择器（云端配置模型 + Ollama 模型）
- SSE 流式输出 AI 回复（打字机效果）
- AI 工具调用前前端弹窗确认（思考→确认→执行）
- 支持切换 provider 与配置自己的云端 API（OpenAI 兼容）
"""
import json
import logging
import queue
import threading
import time
import traceback
import uuid

import requests
from flask import Flask, Response, jsonify, render_template_string, request

from .relay import RelayError, RelayManager
from .utils import CONFIG_PATH, DATA_PATH, load_json, save_json

logger = logging.getLogger("web")

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 智能桌面助手</title>
<style>
:root {
  --bg: #f6f7f9; --sidebar: #fff; --sidebar-hover: #f2f3f5;
  --primary: #4d6bfe; --primary-dark: #3b5bfd; --text: #1f2329;
  --text-sub: #8f959e; --border: #e5e6eb; --user-bubble: #d9e4ff;
  --code-bg: #1e1e1e; --msg-bg: #f7f8fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1d23; --sidebar: #20242c; --sidebar-hover: #2a2f38;
    --text: #e6e8ec; --text-sub: #8b93a1; --border: #30343e;
    --user-bubble: #3b5bfd; --msg-bg: #262b34; --code-bg: #15171c;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       background: var(--bg); color: var(--text); display: flex; overflow: hidden; }

#sidebar { width: 260px; background: var(--sidebar); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; flex-shrink: 0; transition: margin-left .25s; }
#sidebar.hidden { margin-left: -260px; }
.sidebar-head { padding: 14px 12px; display: flex; gap: 8px; border-bottom: 1px solid var(--border); }
#sidebarCloseBtn { flex-shrink: 0; line-height: 1; font-size: 14px; padding: 6px 9px; }
#sidebarFoot { padding: 10px 12px; border-top: 1px solid var(--border); }
#settingsSideBtn { width: 100%; justify-content: center; }
.btn { background: #f2f3f5; color: var(--text); border: 1px solid var(--border); padding: 7px 12px;
       border-radius: 8px; cursor: pointer; font-size: 13px; transition: background .15s; white-space: nowrap; }
.btn:hover { background: #e7e9ee; }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); }
.btn.stop { background: #f04142; border-color: #f04142; color: #fff; }
.btn.stop:hover { background: #d93838; }
#newChatBtn { flex: 1; }
#convList { flex: 1; overflow-y: auto; padding: 8px; }
.conv-item { display: flex; align-items: center; gap: 6px; padding: 10px; margin-bottom: 2px;
             border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text); }
.conv-item:hover { background: var(--sidebar-hover); }
.conv-item.active { background: var(--sidebar-hover); }
.conv-item .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-item .d { flex-shrink: 0; display: none; color: #f04142; background: none; border: none; cursor: pointer; font-size: 14px; }
.conv-item:hover .d { display: block; }

#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#topbar { height: 52px; background: var(--sidebar); border-bottom: 1px solid var(--border);
          display: flex; align-items: center; padding: 0 16px; gap: 10px; flex-shrink: 0; }
#title { font-size: 15px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
#modelTag { color: var(--text-sub); font-size: 12px; white-space: nowrap; }
#modelSelect { background: var(--sidebar); color: var(--text); border: 1px solid var(--border);
               padding: 6px 10px; border-radius: 8px; font-size: 13px; outline: none; max-width: 220px; min-width: 0; }
#menuBtn { display: inline-flex; align-items: center; justify-content: center;
           width: 34px; height: 34px; padding: 0; font-size: 17px; border: 1px solid var(--border);
           background: var(--bg); color: var(--text); border-radius: 8px; cursor: pointer; flex-shrink: 0; }
#menuBtn:hover { background: var(--sidebar-hover); }
#settingsTopBtn { flex-shrink: 0; }

#chat { flex: 1; overflow-y: auto; padding: 24px; }
#chat::-webkit-scrollbar { width: 6px; }
#chat::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.row { max-width: 860px; margin: 0 auto 18px; display: flex; }
.row.user { justify-content: flex-end; }
.avatar { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center;
          justify-content: center; font-size: 16px; flex-shrink: 0; margin-right: 10px; background: var(--sidebar-hover); }
.row.user .avatar { margin: 0 0 0 10px; background: var(--primary); order: 2; }
.bubble { max-width: 82%; }
.row.user .bubble { background: var(--user-bubble); color: var(--text); padding: 10px 14px;
                    border-radius: 12px; line-height: 1.6; font-size: 14px; white-space: pre-wrap; word-break: break-word; }
.row.ai .bubble, .row.system .bubble { background: var(--msg-bg); padding: 12px 16px;
                    border-radius: 12px; line-height: 1.7; font-size: 14px; word-break: break-word; }
.row.system .bubble { color: #f59e0b; }
.thinking { display: flex; align-items: center; gap: 10px; color: var(--text-sub); font-size: 13px; }
.spinner { width: 15px; height: 15px; border: 2px solid var(--border); border-top-color: var(--primary);
           border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.md h1, .md h2, .md h3, .md h4 { margin: 14px 0 8px; line-height: 1.4; }
.md h1 { font-size: 20px; } .md h2 { font-size: 18px; } .md h3 { font-size: 16px; }
.md p { margin: 6px 0; }
.md ul, .md ol { margin: 6px 0; padding-left: 22px; }
.md li { margin: 3px 0; }
.md code { background: rgba(127,127,127,.15); padding: 2px 5px; border-radius: 4px; font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 13px; }
.md pre { background: var(--code-bg); border-radius: 10px; padding: 12px 14px; margin: 10px 0;
          overflow-x: auto; position: relative; }
.md pre code { background: none; padding: 0; color: #e6e6e6; font-size: 13px; line-height: 1.6; display: block; }
.md pre .copy { position: absolute; top: 8px; right: 10px; background: rgba(255,255,255,.1); color: #ccc;
                border: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
.md pre .copy:hover { background: rgba(255,255,255,.2); }
.md blockquote { border-left: 3px solid var(--border); color: var(--text-sub); padding: 4px 12px; margin: 8px 0; }
.md table { border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.md th, .md td { border: 1px solid var(--border); padding: 6px 12px; }
.md th { background: var(--sidebar-hover); }
.md a { color: var(--primary); text-decoration: none; }
.md a:hover { text-decoration: underline; }
.md hr { border: none; border-top: 1px solid var(--border); margin: 14px 0; }
.tok-kw { color: #c586c0; } .tok-str { color: #ce9178; } .tok-com { color: #6a9955; }
.tok-num { color: #b5cea8; } .tok-fn { color: #dcdcaa; }

#inputbar { background: var(--sidebar); border-top: 1px solid var(--border); padding: 14px 24px; flex-shrink: 0; }
#inputWrap { max-width: 860px; margin: 0 auto; display: flex; gap: 10px; align-items: flex-end; }
#input { flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 11px 14px;
         border-radius: 12px; font-size: 14px; outline: none; resize: none; min-height: 44px; max-height: 160px;
         font-family: inherit; line-height: 1.5; }
#input:focus { border-color: var(--primary); }
#input::placeholder { color: var(--text-sub); }
#sendBtn { height: 44px; padding: 0 22px; border-radius: 12px; }
#stopBtn { height: 44px; padding: 0 22px; border-radius: 12px; display: none; }

.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 100;
         align-items: center; justify-content: center; }
.modal.open { display: flex; }
.modal-box { background: var(--sidebar); border: 1px solid var(--border); border-radius: 14px; width: 520px;
             max-width: 92%; padding: 22px; max-height: 90vh; overflow-y: auto; }
.modal-box h3 { margin-bottom: 16px; }
.field { margin-bottom: 14px; }
.field label { display: block; font-size: 13px; color: var(--text-sub); margin-bottom: 5px; }
.field input, .field select { width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text);
                              padding: 9px 11px; border-radius: 8px; font-size: 13px; outline: none; }
.field input:focus, .field select:focus { border-color: var(--primary); }
.field .hint { font-size: 12px; color: var(--text-sub); margin-top: 4px; line-height: 1.5; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }

/* ===== API 中转面板 ===== */
.relay-box { width: 640px; }
.relay-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 14px; }
.relay-tab { background: none; border: none; color: var(--text-sub); padding: 8px 14px; font-size: 13px;
             cursor: pointer; border-bottom: 2px solid transparent; }
.relay-tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
.relay-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.relay-toolbar input { flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text);
                       padding: 7px 10px; border-radius: 8px; font-size: 13px; outline: none; }
.relay-hint-text { color: var(--text-sub); font-size: 12px; }
.relay-status { margin: 10px 0; font-size: 13px; color: var(--text-sub); }
.relay-quota-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.relay-key-result { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px;
                    font-size: 13px; word-break: break-all; margin: 12px 0; line-height: 1.6; }
.relay-key-result .key-red { color: #f04142; font-weight: 600; }
.relay-key-card { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 10px;
                  background: var(--msg-bg); }
.relay-key-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.relay-key-head .nm { font-weight: 600; font-size: 14px; flex: 1; }
.relay-key-head .st { font-size: 12px; padding: 2px 8px; border-radius: 10px; }
.relay-key-head .st.on { background: #e6f7e6; color: #18a058; }
.relay-key-head .st.off { background: #ffecec; color: #f04142; }
.relay-key-meta { font-size: 12px; color: var(--text-sub); margin-bottom: 8px; word-break: break-all; }
.relay-key-usage { font-size: 12px; color: var(--text-sub); margin-bottom: 8px; }
.relay-key-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.relay-log-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.relay-log-table th, .relay-log-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.relay-log-table th { color: var(--text-sub); font-weight: 500; }
.relay-empty { color: var(--text-sub); font-size: 13px; padding: 20px 0; text-align: center; }

#sidebarMask { display: none; }

@media (max-width: 768px) {
  #sidebar { position: fixed; left: 0; top: 0; bottom: 0; z-index: 50; width: 85vw; max-width: 300px;
             box-shadow: 2px 0 12px rgba(0,0,0,.2); }
  #sidebar.hidden { margin-left: -300px; }
  body.sb-open #sidebarMask { display: block; position: fixed; inset: 0; background: rgba(0,0,0,.35);
                              z-index: 55; }
  #topbar { padding: 0 10px; gap: 8px; position: relative; z-index: 60; }
  #modelTag { display: none; }
  #modelSelect { max-width: 150px; }
  #title { font-size: 14px; }
  #chat { padding: 14px; }
  #inputbar { padding: 10px 12px; }
  #inputWrap { max-width: 100%; }
  .row { max-width: 100%; }
  .bubble { max-width: 88%; }
  .avatar { width: 30px; height: 30px; font-size: 14px; }
  #settingsTopBtn { font-size: 12px; padding: 6px 9px; }
  .conv-item .d { display: block; }
}

/* ========== 桌面版扩展样式 ========== */
.btn.danger { background: transparent; border-color: transparent; color: #f04142; padding: 2px 6px; font-size: 15px; line-height: 1; }
.btn.danger:hover { background: #fde8e8; }
.btn.ghost { background: transparent; border-color: transparent; }
.btn.sm { padding: 4px 8px; font-size: 12px; }
.btn.icon { width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center;
            justify-content: center; font-size: 16px; flex-shrink: 0; }
.row.tool .bubble { background: var(--msg-bg); padding: 12px 16px; border-radius: 12px;
                    line-height: 1.7; font-size: 14px; word-break: break-word; }
.confirm-box { max-width: 82%; background: var(--msg-bg); padding: 14px 16px; border-radius: 12px;
               line-height: 1.7; font-size: 14px; word-break: break-word; }
.confirm-box .plan { margin-bottom: 12px; }
.confirm-box .btns { display: flex; gap: 8px; }
</style>
</head>
<body>

<!-- 侧边栏 -->
<div id="sidebar" class="hidden">
  <div class="sidebar-head" onclick="if(!event.target.closest('button'))toggleSidebar()" title="点击空白处收起">
    <button class="btn primary" id="newChatBtn">+ 新建对话</button>
    <button class="btn ghost" id="sidebarCloseBtn" onclick="toggleSidebar()" title="收起侧边栏">&#10005;</button>
  </div>
  <div id="convList"></div>
  <div id="sidebarFoot">
    <button class="btn ghost" id="settingsSideBtn" onclick="openSettings()">&#9881; 设置</button>
  </div>
</div>
<div id="sidebarMask" onclick="toggleSidebar()"></div>

<!-- 主区域 -->
<div id="main">
  <div id="topbar">
    <button class="btn icon" id="menuBtn" onclick="toggleSidebar()" title="历史会话">&#9776;</button>
    <div id="title">新对话</div>
    <span id="modelTag"></span>
    <select id="modelSelect" title="切换模型" onchange="onModelChange()"></select>
    <button class="btn" id="relayTopBtn" onclick="openRelay()">&#8644; API 中转</button>
    <button class="btn" id="settingsTopBtn" onclick="openSettings()">&#9881; 设置</button>
  </div>
  <div id="chat"></div>
  <div id="inputbar">
    <div id="inputWrap">
      <textarea id="input" rows="1" placeholder="说出你的需求，AI 会先思考并提出计划，经你确认后再执行..."
                onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"></textarea>
      <button class="btn primary" id="sendBtn" onclick="send()">发送</button>
      <button class="btn stop" id="stopBtn" onclick="stopGeneration()" style="display:none">停止</button>
    </div>
  </div>
</div>

<!-- 设置弹窗 -->
<div class="modal" id="settingsModal">
  <div class="modal-box">
    <h3>AI 设置</h3>
    <div class="field">
      <label>AI 提供方</label>
      <select id="provider">
        <option value="auto">自动（有云端配置优先云端，否则本地 Ollama）</option>
        <option value="cloud">云端 API（OpenAI 兼容）</option>
        <option value="ollama">本地 Ollama</option>
      </select>
    </div>
    <div class="field">
      <label>云端 API Base URL</label>
      <input id="baseUrl" placeholder="如 https://api.deepseek.com/v1">
      <div class="hint">OpenAI 兼容接口，支持任意服务商任意端口：DeepSeek / 通义 / Moonshot / OpenAI 等</div>
    </div>
    <div class="field">
      <label>API Key</label>
      <input id="apiKey" type="password" placeholder="sk-..." autocomplete="off">
    </div>
    <div class="field">
      <label>云端模型名</label>
      <input id="cloudModel" placeholder="如 deepseek-chat / qwen-max">
    </div>
    <div class="field">
      <label>AI 执行前确认</label>
      <select id="confirmTools">
        <option value="true">开启（推荐，AI 先出计划等你确认）</option>
        <option value="false">关闭（AI 自动执行）</option>
      </select>
    </div>
    <div class="modal-actions">
      <button class="btn" onclick="closeSettings()">关闭</button>
      <button class="btn primary" onclick="saveSettings()">保存配置</button>
    </div>
  </div>
</div>

<!-- API 中转弹窗 -->
<div class="modal" id="relayModal">
  <div class="modal-box relay-box">
    <h3>API 中转站</h3>
    <div class="relay-tabs">
      <button class="relay-tab active" data-tab="relayTabUpstream" onclick="switchRelayTab('relayTabUpstream', this)">上游配置</button>
      <button class="relay-tab" data-tab="relayTabKeys" onclick="switchRelayTab('relayTabKeys', this)">子 API</button>
      <button class="relay-tab" data-tab="relayTabLogs" onclick="switchRelayTab('relayTabLogs', this)">调用日志</button>
    </div>

    <div class="relay-panel" id="relayTabUpstream">
      <div class="field">
        <label>上游 Base URL</label>
        <input id="relayBaseUrl" placeholder="如 https://api.deepseek.com/v1">
        <div class="hint">统一主 API 的 OpenAI 兼容地址，所有子 API 请求都会转发到这里</div>
      </div>
      <div class="field">
        <label>主 API Key</label>
        <input id="relayApiKey" type="password" placeholder="sk-..." autocomplete="off">
      </div>
      <div class="field">
        <label>默认模型名</label>
        <input id="relayModel" placeholder="如 deepseek-chat">
      </div>
      <div class="field">
        <label>超时时间（秒）</label>
        <input id="relayTimeout" type="number" value="60" min="1">
      </div>
      <div class="relay-status" id="relayUpStatus"></div>
      <div class="modal-actions">
        <button class="btn primary" onclick="saveRelayUpstream()">保存上游配置</button>
      </div>
    </div>

    <div class="relay-panel" id="relayTabKeys" style="display:none">
      <div class="relay-toolbar">
        <button class="btn primary" onclick="openRelayKeyModal()">+ 新建子 API</button>
        <span class="relay-hint-text">外部调用：POST /v1/chat/completions，Header: Authorization: Bearer &lt;子Key&gt;</span>
      </div>
      <div id="relayKeyList"></div>
    </div>

    <div class="relay-panel" id="relayTabLogs" style="display:none">
      <div class="relay-toolbar">
        <input id="relayLogFilter" placeholder="按子 API 名称筛选" oninput="loadRelayLogs()">
        <button class="btn" onclick="loadRelayLogs()">刷新</button>
      </div>
      <div id="relayLogList"></div>
    </div>

    <div class="modal-actions">
      <button class="btn" onclick="closeRelay()">关闭</button>
    </div>
  </div>
</div>

<!-- 新建/编辑子 API 弹窗 -->
<div class="modal" id="relayKeyModal">
  <div class="modal-box">
    <h3 id="relayKeyModalTitle">新建子 API</h3>
    <div class="field">
      <label>名称</label>
      <input id="relayKeyName" placeholder="如 客厅客户端 / 手机 APP">
    </div>
    <div class="field">
      <label>可用模型（留空 = 不限制）</label>
      <input id="relayKeyModels" placeholder="多个模型用逗号分隔，如 deepseek-chat,qwen-max">
    </div>
    <div class="relay-quota-grid">
      <div class="field"><label>调用次数上限</label><input id="relayKeyMaxCalls" type="number" min="0" value="0" placeholder="0=不限"></div>
      <div class="field"><label>Token 总量上限</label><input id="relayKeyMaxTokens" type="number" min="0" value="0" placeholder="0=不限"></div>
      <div class="field"><label>并发上限</label><input id="relayKeyMaxConcurrent" type="number" min="0" value="0" placeholder="0=不限"></div>
      <div class="field"><label>每日调用上限</label><input id="relayKeyDailyLimit" type="number" min="0" value="0" placeholder="0=不限"></div>
    </div>
    <div class="relay-key-result" id="relayKeyResult" style="display:none"></div>
    <div class="modal-actions">
      <button class="btn" onclick="closeRelayKeyModal()">关闭</button>
      <button class="btn primary" id="relayKeySaveBtn" onclick="saveRelayKey()">创建</button>
    </div>
  </div>
</div>

<script>
let state = { convId: null, es: null, thinkingEl: null, busy: false, model: '' };
let convs = [];

/* ================= 可选访问口令 ================= */
const AUTH_KEY = 'ai_desktop_auth_token';
let authToken = localStorage.getItem(AUTH_KEY) || '';
const _origFetch = window.fetch.bind(window);
window.fetch = function (url, opts) {
  opts = opts || {};
  const u = String(url);
  if (u.indexOf('/api/') === 0 && authToken) {
    opts.headers = Object.assign({}, opts.headers, {'X-Auth-Token': authToken});
  }
  return _origFetch(url, opts).then((resp) => {
    if (resp.status === 401 && u.indexOf('/api/') === 0) {
      const t = window.prompt('该网页版已启用访问口令，请输入口令（无口令请留空取消）：');
      if (t) {
        authToken = t.trim();
        localStorage.setItem(AUTH_KEY, authToken);
        window.location.reload();
      }
    }
    return resp;
  });
};

/* ================= Markdown 渲染与代码高亮 ================= */
const KEYWORDS = {
  python: 'def return if elif else for while import from class try except finally with as in not and or None True False pass lambda yield raise global print len range self',
  javascript: 'function return const let var if else for while import export class new try catch finally async await typeof null undefined true false this',
  bash: 'if then else fi for while do done echo cd ls rm mkdir cp mv cat grep sudo export exit function return case esac',
  json: 'true false null',
  sql: 'SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE DROP ALTER JOIN LEFT RIGHT INNER ON GROUP BY ORDER HAVING LIMIT AND OR NOT AS PRIMARY KEY INT TEXT VARCHAR NULL'
};

function highlight(code, lang) {
  lang = (lang || '').toLowerCase();
  const kw = KEYWORDS[lang];
  if (!kw) return escapeHtml(code);
  const kwSet = new Set(kw.split(' '));
  const out = [];
  let i = 0;
  const s = String(code);
  const pushEsc = (ch) => out.push(escapeHtml(ch));
  const emit = (cls, t) => out.push('<span class="' + cls + '">' + escapeHtml(t) + '</span>');
  while (i < s.length) {
    const ch = s[i];
    // 字符串
    if (ch === '"' || ch === "'") {
      let j = i + 1, raw = ch, closed = false;
      while (j < s.length) {
        raw += s[j];
        if (s[j] === '\\\\') { if (j + 1 < s.length) { raw += s[j + 1]; j++; } }
        else if (s[j] === ch) { closed = true; j++; break; }
        j++;
      }
      emit('tok-str', raw);
      i = j;
      if (!closed) continue;
      continue;
    }
    // 注释
    const isLineCom = (lang === 'python' || lang === 'bash') && ch === '#';
    const isSlashCom = lang === 'javascript' && ch === '/' && s[i + 1] === '/';
    const isSqlCom = lang === 'sql' && ch === '-' && s[i + 1] === '-';
    if (isLineCom || isSlashCom || isSqlCom) {
      let j = i, raw = '';
      while (j < s.length && s[j] !== '\\n') { raw += s[j]; j++; }
      emit('tok-com', raw);
      i = j;
      continue;
    }
    // 数字
    if (/[0-9]/.test(ch) || (ch === '-' && /[0-9]/.test(s[i + 1] || ''))) {
      let j = i, raw = '';
      while (j < s.length && /[0-9a-zA-Z_.]/.test(s[j])) { raw += s[j]; j++; }
      emit('tok-num', raw);
      i = j;
      continue;
    }
    // 标识符/关键字
    if (/[A-Za-z_]/.test(ch)) {
      let j = i, raw = '';
      while (j < s.length && /[A-Za-z0-9_]/.test(s[j])) { raw += s[j]; j++; }
      if (kwSet.has(raw)) emit('tok-kw', raw);
      else pushEsc(raw);
      i = j;
      continue;
    }
    pushEsc(ch);
    i++;
  }
  return out.join('');
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(src) {
  src = String(src || '');
  let lines = src.split(/\\r?\\n/);
  let html = '';
  let i = 0;
  const inline = (s) => escapeHtml(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
    .replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, (m, t, u) => {
      if (!/^(https?:|mailto:)/i.test(u)) return t;
      return '<a href="' + u + '" target="_blank" rel="noopener">' + t + '</a>';
    });
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const buf = []; i++;
      while (i < lines.length && !/^```\\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++;
      html += '<pre><button class="copy" onclick="copyCode(this)">复制</button><code>' + highlight(buf.join('\\n'), lang) + '</code></pre>';
      continue;
    }
    if (/^#{1,4}\\s/.test(line)) {
      const level = line.match(/^(#{1,4})\\s/)[1].length;
      html += '<h' + level + '>' + inline(line.replace(/^#{1,4}\\s/, '')) + '</h' + level + '>';
      i++; continue;
    }
    if (/^>\\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\\s?/, '')); i++; }
      html += '<blockquote>' + inline(buf.join(' ')) + '</blockquote>';
      continue;
    }
    if (/^\\s*[-*]\\s+/.test(line)) {
      html += '<ul>';
      while (i < lines.length && /^\\s*[-*]\\s+/.test(lines[i])) { html += '<li>' + inline(lines[i].replace(/^\\s*[-*]\\s+/, '')) + '</li>'; i++; }
      html += '</ul>';
      continue;
    }
    if (/^\\s*\\d+\\.\\s+/.test(line)) {
      html += '<ol>';
      while (i < lines.length && /^\\s*\\d+\\.\\s+/.test(lines[i])) { html += '<li>' + inline(lines[i].replace(/^\\s*\\d+\\.\\s+/, '')) + '</li>'; i++; }
      html += '</ol>';
      continue;
    }
    if (/^\\s*---+\\s*$/.test(line)) { html += '<hr>'; i++; continue; }
    // 表格
    if (line.includes('|') && i + 1 < lines.length && /^\\s*\\|[\\s:|-]+\\|?\\s*$/.test(lines[i + 1])) {
      const head = line.split('|').slice(1, -1).map(s => inline(s.trim()));
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|')) {
        rows.push('<tr>' + lines[i].split('|').slice(1, -1).map(s => '<td>' + inline(s.trim()) + '</td>').join('') + '</tr>');
        i++;
      }
      html += '<table><thead><tr>' + head.map(h => '<th>' + h + '</th>').join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
      continue;
    }
    if (line.trim() === '') { i++; continue; }
    const buf = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== '' && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
    html += '<p>' + inline(buf.join(' ')) + '</p>';
  }
  return html;
}

function copyCode(btn) {
  const code = btn.nextElementSibling.innerText;
  navigator.clipboard.writeText(code).then(() => { btn.textContent = '已复制'; setTimeout(() => btn.textContent = '复制', 1200); });
}

/* ================= 侧边栏 ================= */
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const hidden = sb.classList.toggle('hidden');
  document.body.classList.toggle('sb-open', !hidden);
}
function closeSidebarIfMobile() {
  document.body.classList.remove('sb-open');
  if (window.innerWidth <= 768) document.getElementById('sidebar').classList.add('hidden');
}

function convTitle(messages) {
  const first = messages.find(m => m.role === 'user');
  return first ? first.content.slice(0, 20) : '新对话';
}

async function loadConversations() {
  try {
    const r = await fetch('/api/conversations');
    const d = await r.json();
    convs = d.conversations || [];
    renderConvList();
    if (!state.convId && convs.length) selectConversation(convs[0].id);
  } catch (e) {}
}

function renderConvList() {
  const list = document.getElementById('convList');
  list.innerHTML = '';
  if (!convs.length) { list.innerHTML = '<div style="padding:16px;color:var(--text-sub);font-size:13px;">暂无会话，点击上方新建</div>'; return; }
  convs.forEach(c => {
    const el = document.createElement('div');
    el.className = 'conv-item' + (c.id === state.convId ? ' active' : '');
    const del = document.createElement('button');
    del.className = 'btn danger d';
    del.title = '删除会话';
    del.textContent = 'x';
    del.onclick = (ev) => delConversation(ev, c.id);
    const span = document.createElement('span');
    span.className = 't';
    span.textContent = c.title;
    el.appendChild(span);
    el.appendChild(del);
    el.onclick = () => selectConversation(c.id);
    list.appendChild(el);
  });
}

async function newConversation() {
  if (state.busy) return;
  try {
    const r = await fetch('/api/conversations', { method: 'POST' });
    const d = await r.json();
    convs.unshift(d.conversation);
    state.convId = d.conversation.id;
    renderConvList();
    document.getElementById('chat').innerHTML = '';
    document.getElementById('title').textContent = '新对话';
    closeSidebarIfMobile();
  } catch (e) {}
}

async function delConversation(ev, id) {
  ev.stopPropagation();
  if (!confirm('确定删除该会话？')) return;
  try {
    await fetch('/api/conversations/' + id, { method: 'DELETE' });
    convs = convs.filter(c => c.id !== id);
    if (state.convId === id) { state.convId = null; document.getElementById('chat').innerHTML = ''; document.getElementById('title').textContent = '新对话'; }
    renderConvList();
    closeSidebarIfMobile();
  } catch (e) {}
}

async function selectConversation(id) {
  if (state.busy && state.convId !== id) return;
  state.convId = id;
  renderConvList();
  document.getElementById('chat').innerHTML = '';
  try {
    const r = await fetch('/api/conversations/' + id + '/messages');
    const d = await r.json();
    (d.messages || []).forEach(m => renderMsg(m.role, m.content, m.tool));
    document.getElementById('title').textContent = d.title || convTitle(d.messages || []);
    document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
    closeSidebarIfMobile();
  } catch (e) {}
}

/* ================= 消息渲染 ================= */
function renderMsg(role, text, toolName) {
  const chat = document.getElementById('chat');
  const row = document.createElement('div');
  row.className = 'row ' + role;
  const avatarHtml = '<div class="avatar">' + (role === 'user' ? '我' : (role === 'ai' ? 'AI' : '!')) + '</div>';
  let bubbleHtml = '';
  if (role === 'user') {
    bubbleHtml = '<div class="bubble">' + escapeHtml(text) + '</div>';
  } else if (role === 'tool') {
    bubbleHtml = '<div class="bubble">' + escapeHtml('工具 ' + (toolName || '') + '：' + text) + '</div>';
  } else if (role === 'system') {
    bubbleHtml = '<div class="bubble">' + escapeHtml(text) + '</div>';
  } else {
    bubbleHtml = '<div class="bubble md">' + renderMarkdown(text) + '</div>';
  }
  if (role === 'user') { row.innerHTML = bubbleHtml + avatarHtml; } else { row.innerHTML = avatarHtml + bubbleHtml; }
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
}

function addThinking() {
  const chat = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = 'row ai';
  el.innerHTML = '<div class="avatar">AI</div><div class="bubble thinking"><span class="spinner"></span> AI 思考中...</div>';
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  state.thinkingEl = el;
}
function removeThinking() { if (state.thinkingEl) { state.thinkingEl.remove(); state.thinkingEl = null; } }

function addConfirm(plan, tools) {
  removeThinking();
  const chat = document.getElementById('chat');
  const box = document.createElement('div');
  box.className = 'row ai';
  const names = (tools || []).map(t => t.name).join('、');
  box.innerHTML = '<div class="avatar">AI</div><div class="confirm-box">' +
    '<div class="plan">计划执行：<b>' + escapeHtml(plan) + '</b>' +
    (names ? '<div style="color:var(--text-sub);font-size:12px;margin-top:4px;">需要调用工具：' + escapeHtml(names) + '</div>' : '') +
    '</div><div class="btns">' +
    '<button class="btn primary" id="yesBtn">允许执行</button>' +
    '<button class="btn danger" id="noBtn">拒绝</button></div></div>';
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
  document.getElementById('yesBtn').onclick = () => doConfirm(true);
  document.getElementById('noBtn').onclick = () => doConfirm(false);
}
function removeConfirm() {
  const box = document.querySelector('.confirm-box');
  if (box) box.closest('.row').remove();
}
async function doConfirm(approved) {
  if (!state.convId && !state.curSid) return;
  const sid = state.curSid;
  document.querySelectorAll('#yesBtn,#noBtn').forEach(b => b.disabled = true);
  try { await fetch('/api/confirm/' + sid, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({approved: approved}) }); } catch (e) {}
}

/* ================= 发送与流式 ================= */
function setBusy(busy) {
  state.busy = busy;
  document.getElementById('sendBtn').style.display = busy ? 'none' : '';
  document.getElementById('stopBtn').style.display = busy ? '' : 'none';
}

async function stopGeneration() {
  const sid = state.curSid;
  if (state.es) { state.es.close(); state.es = null; }
  state.curSid = null;
  if (sid) { try { await fetch('/api/stop/' + sid, { method: 'POST' }); } catch (e) {} }
  removeThinking(); removeConfirm();
  setBusy(false);
  loadConversations();
}

async function send() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text || state.busy) return;
  try {
    if (!state.convId) {
      const r = await fetch('/api/conversations', { method: 'POST' });
      const d = await r.json();
      convs.unshift(d.conversation);
      state.convId = d.conversation.id;
      renderConvList();
    }
    input.value = '';
    renderMsg('user', text);
    addThinking();
    setBusy(true);
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ message: text, conversation_id: state.convId, model: state.model || undefined })
    });
    const data = await resp.json();
    if (!data.ok) {
      removeThinking();
      renderMsg('system', '错误: ' + (data.error || '未知'));
      setBusy(false);
      return;
    }
    state.curSid = data.session_id;
    // 更新会话标题
    const c = convs.find(c => c.id === state.convId);
    if (c && c.title === '新对话') { c.title = text.slice(0, 20); renderConvList(); document.getElementById('title').textContent = c.title; }
    startStream(data.session_id);
  } catch (e) {
    removeThinking();
    renderMsg('system', '请求失败: ' + e);
    setBusy(false);
  }
}

function startStream(sid) {
  const chat = document.getElementById('chat');
  let aiRow = null, aiBubble = null, aiText = '';
  state.es = new EventSource('/api/stream/' + sid);
  state.es.onopen = () => removeThinking();
  state.es.onmessage = function(ev) {
    let data;
    try { data = JSON.parse(ev.data); } catch (e) { return; }
    if (data.type === 'text') {
      if (!aiRow) {
        aiRow = document.createElement('div');
        aiRow.className = 'row ai';
        aiRow.innerHTML = '<div class="avatar">AI</div><div class="bubble md"></div>';
        chat.appendChild(aiRow);
        aiBubble = aiRow.querySelector('.bubble');
      }
      aiText += data.content;
      aiBubble.innerHTML = renderMarkdown(aiText);
      chat.scrollTop = chat.scrollHeight;
    } else if (data.type === 'tool') {
      renderMsg('tool', data.content);
    } else if (data.type === 'confirm') {
      addConfirm(data.plan, data.tools);
    } else if (data.type === 'error') {
      if (!aiRow) { aiRow = renderMsg('ai', ''); aiBubble = aiRow.querySelector('.bubble'); }
      aiText += '\\n[错误] ' + data.content;
      aiBubble.innerHTML = renderMarkdown(aiText);
    } else if (data.type === 'done') {
      if (state.es) { state.es.close(); state.es = null; }
      state.curSid = null;
      removeThinking(); removeConfirm();
      setBusy(false);
      loadConversations();
    }
  };
  state.es.onerror = function() { /* keepalive 中断忽略 */ };
}

/* ================= 模型选择 ================= */
async function refreshModels() {
  try {
    const r = await fetch('/api/models');
    const d = await r.json();
    const sel = document.getElementById('modelSelect');
    sel.innerHTML = '';
    const groups = {};
    (d.models || []).forEach(m => { (groups[m.provider] = groups[m.provider] || []).push(m); });
    let first = null;
    for (const provider of Object.keys(groups)) {
      const og = document.createElement('optgroup');
      og.label = provider === 'cloud' ? '云端模型' : '本地模型';
      groups[provider].forEach(m => {
        const op = document.createElement('option');
        op.value = m.name; op.textContent = m.name;
        if (!first) first = m.name;
        og.appendChild(op);
      });
      sel.appendChild(og);
    }
    state.model = d.current || first || '';
    if (state.model) sel.value = state.model;
    const tag = document.getElementById('modelTag');
    tag.textContent = d.provider === 'cloud' ? '云端' : (d.provider === 'ollama' ? '本地 Ollama' : '未配置');
    document.title = 'AI 智能桌面助手';
  } catch (e) {}
}
function onModelChange() {
  const sel = document.getElementById('modelSelect');
  if (sel.value) state.model = sel.value;
}

/* ================= 设置 ================= */
async function openSettings() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('provider').value = d.provider === 'cloud' ? 'cloud' : (d.provider === 'ollama' ? 'ollama' : 'auto');
    document.getElementById('baseUrl').value = d.cloud_base_url || '';
    document.getElementById('apiKey').value = '';
    document.getElementById('cloudModel').value = d.cloud_model || '';
    document.getElementById('confirmTools').value = d.confirm_tools ? 'true' : 'false';
  } catch (e) {}
  document.getElementById('settingsModal').classList.add('open');
}
function closeSettings() { document.getElementById('settingsModal').classList.remove('open'); }
async function saveSettings() {
  const body = {
    provider: document.getElementById('provider').value,
    base_url: document.getElementById('baseUrl').value.trim(),
    api_key: document.getElementById('apiKey').value.trim(),
    model: document.getElementById('cloudModel').value.trim(),
    confirm_tools: document.getElementById('confirmTools').value === 'true'
  };
  try {
    const r = await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    renderMsg('system', d.message || '已保存');
    closeSettings();
    refreshModels();
  } catch (e) {
    renderMsg('system', '保存失败: ' + e);
  }
}

loadConversations();
refreshModels();

/* ================= API 中转站 ================= */
let relayEditingId = null;

function openRelay() {
  document.getElementById('relayModal').classList.add('open');
  switchRelayTab('relayTabUpstream', document.querySelector('.relay-tab.active') || null);
  loadRelayUpstream();
  loadRelayKeys();
  loadRelayLogs();
}
function closeRelay() { document.getElementById('relayModal').classList.remove('open'); }
function switchRelayTab(tabId, btn) {
  document.querySelectorAll('.relay-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.querySelectorAll('.relay-panel').forEach(p => { p.style.display = 'none'; });
  document.getElementById(tabId).style.display = 'block';
  if (tabId === 'relayTabKeys') loadRelayKeys();
  if (tabId === 'relayTabLogs') loadRelayLogs();
}

/* ---- 上游配置 ---- */
async function loadRelayUpstream() {
  try {
    const r = await fetch('/api/relay/upstream');
    const d = await r.json();
    const up = d.upstream || {};
    document.getElementById('relayBaseUrl').value = up.base_url || '';
    document.getElementById('relayModel').value = up.model || '';
    document.getElementById('relayTimeout').value = up.timeout || 60;
    const st = document.getElementById('relayUpStatus');
    st.textContent = d.ready ? '上游已就绪（主 API Key 已配置）' : (up.base_url ? '上游未就绪：API Key 未配置' : '上游未配置，请填写 Base URL 与主 API Key');
  } catch (e) {}
}
async function saveRelayUpstream() {
  const body = {
    base_url: document.getElementById('relayBaseUrl').value.trim(),
    api_key: document.getElementById('relayApiKey').value.trim(),
    model: document.getElementById('relayModel').value.trim(),
    timeout: document.getElementById('relayTimeout').value || 60
  };
  try {
    const r = await fetch('/api/relay/upstream', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    document.getElementById('relayApiKey').value = '';
    document.getElementById('relayUpStatus').textContent = d.ready ? '保存成功，上游已就绪' : '已保存（上游信息不完整）';
    alert(d.ok ? '上游配置已保存' : '保存失败');
  } catch (e) { alert('保存失败: ' + e); }
}

/* ---- 子 API ---- */
async function loadRelayKeys() {
  const list = document.getElementById('relayKeyList');
  try {
    const r = await fetch('/api/relay/keys');
    const d = await r.json();
    const keys = d.keys || [];
    if (!keys.length) {
      list.innerHTML = '<div class="relay-empty">暂无子 API，点击上方「新建子 API」创建</div>';
      return;
    }
    list.innerHTML = keys.map(k => {
      const q = k.quota || {};
      const u = k.usage || {};
      const shownModels = (k.models || []).length ? k.models.join(', ') : '不限制';
      const stCls = k.status === 'enabled' ? 'on' : 'off';
      const stText = k.status === 'enabled' ? '启用' : '停用';
      return '<div class="relay-key-card">' +
        '<div class="relay-key-head"><span class="nm">' + escapeHtml(k.name) + '</span>' +
        '<span class="st ' + stCls + '">' + stText + '</span></div>' +
        '<div class="relay-key-meta">子 Key：<b>' + escapeHtml(k.key) + '</b><br>可用模型：' + escapeHtml(shownModels) + '</div>' +
        '<div class="relay-key-usage">用量：' + (u.calls || 0) + '/' + (q.max_calls || '∞') + ' 次 · Tokens ' + (u.tokens || 0) + '/' + (q.max_tokens || '∞') +
        ' · 今日 ' + (u.daily_calls || 0) + '/' + (q.daily_limit || '∞') + ' · 并发 ' + (q.max_concurrent || '∞') + '</div>' +
        '<div class="relay-key-actions">' +
        '<button class="btn" onclick="editRelayKey(\'' + k.id + '\')">编辑</button>' +
        (k.status === 'enabled' ? '<button class="btn" onclick="toggleRelayKey(\'' + k.id + '\',\'disabled\')">停用</button>'
                                : '<button class="btn primary" onclick="toggleRelayKey(\'' + k.id + '\',\'enabled\')">启用</button>') +
        '<button class="btn" onclick="resetRelayKey(\'' + k.id + '\')">重置用量</button>' +
        '<button class="btn" onclick="deleteRelayKey(\'' + k.id + '\')">删除</button>' +
        '</div></div>';
    }).join('');
  } catch (e) { list.innerHTML = '<div class="relay-empty">加载失败: ' + escapeHtml(String(e)) + '</div>'; }
}
function openRelayKeyModal() {
  relayEditingId = null;
  document.getElementById('relayKeyModalTitle').textContent = '新建子 API';
  document.getElementById('relayKeySaveBtn').textContent = '创建';
  document.getElementById('relayKeyName').value = '';
  document.getElementById('relayKeyModels').value = '';
  document.getElementById('relayKeyMaxCalls').value = 0;
  document.getElementById('relayKeyMaxTokens').value = 0;
  document.getElementById('relayKeyMaxConcurrent').value = 0;
  document.getElementById('relayKeyDailyLimit').value = 0;
  document.getElementById('relayKeyResult').style.display = 'none';
  document.getElementById('relayKeyModal').classList.add('open');
}
function closeRelayKeyModal() { document.getElementById('relayKeyModal').classList.remove('open'); }
async function editRelayKey(id) {
  relayEditingId = id;
  try {
    const r = await fetch('/api/relay/keys');
    const d = await r.json();
    const k = (d.keys || []).filter(x => x.id === id)[0];
    if (!k) return;
    document.getElementById('relayKeyModalTitle').textContent = '编辑子 API：' + k.name;
    document.getElementById('relayKeySaveBtn').textContent = '保存';
    document.getElementById('relayKeyName').value = k.name;
    document.getElementById('relayKeyModels').value = (k.models || []).join(',');
    const q = k.quota || {};
    document.getElementById('relayKeyMaxCalls').value = q.max_calls || 0;
    document.getElementById('relayKeyMaxTokens').value = q.max_tokens || 0;
    document.getElementById('relayKeyMaxConcurrent').value = q.max_concurrent || 0;
    document.getElementById('relayKeyDailyLimit').value = q.daily_limit || 0;
    document.getElementById('relayKeyResult').style.display = 'none';
    document.getElementById('relayKeyModal').classList.add('open');
  } catch (e) {}
}
async function saveRelayKey() {
  const models = document.getElementById('relayKeyModels').value.split(',').map(s => s.trim()).filter(Boolean);
  const quota = {
    max_calls: document.getElementById('relayKeyMaxCalls').value || 0,
    max_tokens: document.getElementById('relayKeyMaxTokens').value || 0,
    max_concurrent: document.getElementById('relayKeyMaxConcurrent').value || 0,
    daily_limit: document.getElementById('relayKeyDailyLimit').value || 0
  };
  const body = { name: document.getElementById('relayKeyName').value.trim(), models: models, quota: quota };
  try {
    let d;
    if (relayEditingId) {
      const r = await fetch('/api/relay/keys/' + relayEditingId, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
      d = await r.json();
    } else {
      const r = await fetch('/api/relay/keys', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
      d = await r.json();
    }
    if (!d.ok) { alert(d.error || '保存失败'); return; }
    if (!relayEditingId && d.key && d.key.key) {
      const res = document.getElementById('relayKeyResult');
      res.style.display = 'block';
      res.innerHTML = '子 API 创建成功！<br>请复制并妥善保存子 Key：<br><span class="key-red">' + escapeHtml(d.key.key) + '</span><br>' +
        '<span style="font-size:12px">此 Key 可在列表中随时查看，保管好即可。</span>';
      openRelayKeyModal();
      closeRelayKeyModal();
      loadRelayKeys();
    } else {
      closeRelayKeyModal();
      loadRelayKeys();
    }
  } catch (e) { alert('保存失败: ' + e); }
}
async function toggleRelayKey(id, status) {
  try {
    await fetch('/api/relay/keys/' + id, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: status}) });
    loadRelayKeys();
  } catch (e) {}
}
async function resetRelayKey(id) {
  if (!confirm('确认重置该子 API 的用量计数？')) return;
  try {
    await fetch('/api/relay/keys/' + id + '/reset', { method: 'POST' });
    loadRelayKeys();
  } catch (e) {}
}
async function deleteRelayKey(id) {
  if (!confirm('确认删除该子 API？删除后该子 Key 立即失效。')) return;
  try {
    await fetch('/api/relay/keys/' + id, { method: 'DELETE' });
    loadRelayKeys();
  } catch (e) {}
}

/* ---- 调用日志 ---- */
async function loadRelayLogs() {
  const list = document.getElementById('relayLogList');
  const filter = document.getElementById('relayLogFilter').value.trim();
  try {
    const r = await fetch('/api/relay/logs?name=' + encodeURIComponent(filter) + '&limit=100');
    const d = await r.json();
    const logs = d.logs || [];
    if (!logs.length) {
      list.innerHTML = '<div class="relay-empty">暂无调用日志</div>';
      return;
    }
    const rows = logs.map(l => {
      const t = new Date((l.ts || 0) * 1000);
      const tm = t.toLocaleString();
      return '<tr><td>' + escapeHtml(tm) + '</td><td>' + escapeHtml(l.key_name || '') + '</td>' +
        '<td>' + escapeHtml(l.model || '') + '</td><td>' + (l.status_code || 0) + '</td>' +
        '<td>' + (l.tokens || 0) + '</td><td>' + (l.duration_ms || 0) + 'ms</td></tr>';
    }).join('');
    list.innerHTML = '<table class="relay-log-table"><thead><tr><th>时间</th><th>子 API</th><th>模型</th><th>状态</th><th>Tokens</th><th>耗时</th></tr></thead><tbody>' + rows + '</tbody></table>';
  } catch (e) { list.innerHTML = '<div class="relay-empty">加载失败</div>'; }
}
</script>
</body>
</html>
"""


class ChatSession:
    """一次对话会话：后台线程运行 AIEngine，事件经队列推给 SSE，结束后持久化"""

    def __init__(self, session_id: str, engine, conv_id: str = None, user_message: str = ""):
        self.id = session_id
        self.engine = engine
        self.conv_id = conv_id
        self.user_message = user_message
        self.queue = queue.Queue()
        self.confirm_event = threading.Event()
        self.stop_flag = threading.Event()
        self.decision = None
        self.thread = None
        self.running = False
        self.collected = []  # 收集文本用于持久化

    def start(self, message: str):
        self.running = True
        self.thread = threading.Thread(target=self._run, args=(message,), daemon=True)
        self.thread.start()

    def confirm(self, approved: bool):
        self.decision = approved
        self.confirm_event.set()

    def stop(self):
        """请求停止本轮生成：立即中断等待、关闭底层连接"""
        self.stop_flag.set()
        self.confirm_event.set()
        try:
            self.engine.provider.close()
        except Exception:
            pass

    def _run(self, message: str):
        try:
            gen = self.engine.chat(message)
            decision = None
            while True:
                if self.stop_flag.is_set():
                    break
                if decision is None:
                    chunk = next(gen)
                else:
                    chunk = gen.send(decision)
                    decision = None
                if hasattr(chunk, "plan"):
                    tools = [{"name": tc.get("name", ""), "args": tc.get("args", {})}
                             for tc in getattr(chunk, "tool_calls", [])]
                    self.queue.put({"type": "confirm", "plan": chunk.plan, "tools": tools})
                    # 等待确认期间也要响应停止请求
                    while not self.confirm_event.is_set():
                        if self.stop_flag.is_set():
                            break
                        self.confirm_event.wait(0.2)
                    self.confirm_event.clear()
                    if self.stop_flag.is_set():
                        break
                    decision = self.decision
                    self.decision = None
                else:
                    self.collected.append(chunk)
                    self.queue.put({"type": "text", "content": chunk})
        except StopIteration:
            pass
        except Exception as e:
            logger.error("会话线程异常: %s", e)
            traceback.print_exc()
            self.queue.put({"type": "error", "content": str(e)})
        finally:
            self._persist()
            self.queue.put({"type": "done"})
            self.running = False

    def _persist(self):
        """把本轮对话追加到会话文件"""
        if not self.conv_id:
            return
        conv = load_conversation(self.conv_id)
        if conv is None:
            return
        if self.user_message:
            conv["messages"].append({"role": "user", "content": self.user_message})
        text = "".join(self.collected).strip()
        if text:
            conv["messages"].append({"role": "assistant", "content": text})
        conv["updated_at"] = time.time()
        if not conv.get("title") or conv["title"] == "新对话":
            conv["title"] = (self.user_message or "新对话")[:20]
        save_conversation(conv)


# ============ 会话持久化 ============

def _conv_dir():
    # 动态读取 DATA_PATH，便于测试隔离
    return DATA_PATH / "conversations"


def _conv_path(cid: str):
    # 防御路径穿越
    safe = "".join(ch for ch in cid if ch.isalnum() or ch in "-_")
    return _conv_dir() / f"{safe}.json"


def list_conversations() -> list:
    convs = []
    try:
        for f in _conv_dir().glob("*.json"):
            conv = load_json(f, {})
            if not conv.get("id"):
                continue
            convs.append({
                "id": conv["id"],
                "title": conv.get("title") or "新对话",
                "updated_at": conv.get("updated_at", 0),
            })
    except OSError:
        pass
    convs.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return convs


def load_conversation(cid: str):
    """读取会话；不存在返回 None"""
    path = _conv_path(cid)
    if not path.exists():
        return None
    return load_json(path, {})


def save_conversation(conv: dict) -> bool:
    if not conv.get("id"):
        return False
    return save_json(_conv_path(conv["id"]), conv)


def delete_conversation(cid: str) -> bool:
    try:
        _conv_path(cid).unlink()
        return True
    except OSError:
        return False


_SESSIONS = {}


def create_app(relay_manager: RelayManager = None) -> Flask:
    app = Flask(__name__)
    mgr = relay_manager or RelayManager()

    def _relay_error(message: str, status: int, error_type: str = "relay_error"):
        return jsonify({"error": {"message": message, "type": error_type, "status": status}}), status

    def _access_token() -> str:
        cfg = load_json(CONFIG_PATH / "config.json", {})
        return (cfg.get("web", {}) or {}).get("access_token", "") or ""

    @app.before_request
    def _check_token():
        """可选访问口令：配置 web.access_token 后，/api/* 需携带 X-Auth-Token"""
        token = _access_token()
        if not token:
            return None
        path = request.path
        # SSE 流由 12 位随机会话 ID 保护，不做口令校验
        if path.startswith("/api/stream"):
            return None
        if path.startswith("/api/") and request.headers.get("X-Auth-Token") != token:
            return jsonify({"ok": False, "error": "访问口令错误"}), 401
        return None

    @app.route("/")
    def index():
        return render_template_string(PAGE_TEMPLATE)

    # ================= 中转站：公开端点 =================
    @app.route("/v1/chat/completions", methods=["POST"])
    def v1_chat_completions():
        """OpenAI 兼容端点：Bearer 子 Key 鉴权，转发到统一上游"""
        auth = request.headers.get("Authorization", "") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer") else ""
        key = mgr.get_key_by_token(token) if token else None
        if key is None:
            mgr.log("无效Key", (token or "无Token")[:16], (request.get_json(silent=True) or {}).get("model", ""),
                    401, 0, 0)
            return _relay_error("无效的子 API Key", 401, "invalid_key")
        if not mgr.upstream_ready:
            return _relay_error("上游未配置", 503, "upstream_not_configured")

        data = request.get_json(silent=True) or {}
        model = (data.get("model") or "").strip()
        if not model:
            return _relay_error("缺少 model 字段", 400, "missing_model")
        allowed = key.get("models") or []
        if allowed and model not in allowed:
            return _relay_error(f"model 不在白名单: {model}", 400, "model_not_allowed")

        try:
            mgr.check_quota(key)
        except RelayError as e:
            return _relay_error(str(e), e.status, e.error_type)

        up = mgr.get_upstream_credentials()
        url = up["base_url"].rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {up['api_key']}",
            "Content-Type": "application/json",
        }
        body = dict(data)
        if body.get("stream"):
            return _v1_stream(up, url, headers, body, key, mgr)
        return _v1_sync(up, url, headers, body, key, mgr)

    def _v1_sync(up, url, headers, body, key, mgr):
        start = time.time()
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=up["timeout"])
            duration = int((time.time() - start) * 1000)
            if resp.status_code >= 400:
                payload = _upstream_error(resp)
                mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                        resp.status_code, 0, duration)
                return jsonify(payload), resp.status_code
            try:
                payload = resp.json()
            except ValueError:
                mgr.release(key)
                return _relay_error("上游返回非 JSON 响应", 502, "upstream_bad_response")
            tokens = (payload.get("usage") or {}).get("total_tokens", 0) or 0
            mgr.record_usage(key, tokens)
            mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                    200, tokens, duration)
            mgr.release(key)
            return jsonify(payload)
        except requests.exceptions.Timeout:
            mgr.release(key)
            return _relay_error("上游响应超时", 504, "upstream_timeout")
        except requests.exceptions.ConnectionError:
            mgr.release(key)
            return _relay_error("无法连接上游（检查 base_url 与网络）", 502, "upstream_connection_error")
        except Exception as e:
            mgr.release(key)
            logger.exception("中转转发失败")
            return _relay_error(f"中转转发失败: {e}", 502, "upstream_error")
        finally:
            pass

    def _v1_stream(up, url, headers, body, key, mgr):
        start = time.time()

        def generate():
            upstream = None
            try:
                upstream = requests.post(url, headers=headers, json=body, stream=True, timeout=up["timeout"])
                duration = int((time.time() - start) * 1000)
                if upstream.status_code >= 400:
                    payload = _upstream_error(upstream)
                    mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                            upstream.status_code, 0, duration)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    return
                for chunk in upstream.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
                tokens = 0
                mgr.record_usage(key, tokens)
                mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                        200, tokens, int((time.time() - start) * 1000))
            except requests.exceptions.Timeout:
                mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                        504, 0, int((time.time() - start) * 1000))
                yield f"data: {json.dumps({'error': {'message': '上游响应超时', 'type': 'upstream_timeout', 'status': 504}}, ensure_ascii=False)}\n\n"
            except requests.exceptions.ConnectionError:
                mgr.log(key.get("name", ""), key.get("key_prefix", ""), body.get("model", ""),
                        502, 0, int((time.time() - start) * 1000))
                yield f"data: {json.dumps({'error': {'message': '无法连接上游', 'type': 'upstream_connection_error', 'status': 502}}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.exception("中转流式转发失败")
                yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'upstream_error', 'status': 502}}, ensure_ascii=False)}\n\n"
            finally:
                if upstream is not None:
                    upstream.close()
                mgr.release(key)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _upstream_error(resp):
        try:
            payload = resp.json()
            msg = (payload.get("error") or {}).get("message") or payload.get("message") or "上游请求失败"
        except ValueError:
            msg = (resp.text or "")[:300] or "上游请求失败"
        return {"error": {"message": msg, "type": "upstream_error", "status": resp.status_code}}

    # ================= 中转站：管理端点 =================
    @app.route("/api/relay/upstream", methods=["GET", "POST"])
    def api_relay_upstream():
        if request.method == "GET":
            return jsonify({"ok": True, "upstream": mgr.get_upstream(), "ready": mgr.upstream_ready})
        data = request.get_json(silent=True) or {}
        up = mgr.set_upstream(
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            model=data.get("model", ""),
            timeout=data.get("timeout"),
        )
        return jsonify({"ok": True, "upstream": up, "ready": mgr.upstream_ready})

    @app.route("/api/relay/keys", methods=["GET", "POST"])
    def api_relay_keys():
        if request.method == "GET":
            return jsonify({"ok": True, "keys": mgr.list_keys()})
        data = request.get_json(silent=True) or {}
        key = mgr.create_key(name=data.get("name", ""), models=data.get("models"), quota=data.get("quota"))
        return jsonify({"ok": True, "key": key}), 201

    @app.route("/api/relay/keys/<kid>", methods=["PUT", "DELETE"])
    def api_relay_key(kid):
        if request.method == "DELETE":
            if not mgr.delete_key(kid):
                return _relay_error("子 API 不存在", 404, "not_found")
            return jsonify({"ok": True})
        data = request.get_json(silent=True) or {}
        key = mgr.update_key(kid, name=data.get("name"), models=data.get("models"),
                             quota=data.get("quota"), status=data.get("status"))
        return jsonify({"ok": True, "key": key})

    @app.route("/api/relay/keys/<kid>/reset", methods=["POST"])
    def api_relay_key_reset(kid):
        key = mgr.reset_usage(kid)
        return jsonify({"ok": True, "key": key})

    @app.route("/api/relay/logs")
    def api_relay_logs():
        name = (request.args.get("name") or "").strip()
        limit = request.args.get("limit") or 100
        logs = mgr.get_logs(name=name, limit=limit)
        return jsonify({"ok": True, "logs": logs})

    @app.route("/api/status")
    def api_status():
        from .ai_engine import AIEngine
        engine = AIEngine()
        info = {
            "provider": engine.provider.name,
            "model": engine.model or "",
            "cloud_base_url": engine.provider.base_url if engine.provider.name == "cloud" else "",
            "cloud_model": engine.provider.model if engine.provider.name == "cloud" else "",
            "confirm_tools": engine.confirm_tools,
        }
        try:
            engine.provider.close()
        except Exception:
            pass
        return jsonify(info)

    @app.route("/api/models")
    def api_models():
        """返回可选模型列表：云端配置模型 + Ollama 本地模型"""
        from .ai_engine import AIEngine
        engine = AIEngine()
        models = engine.list_available_models()
        try:
            engine.provider.close()
        except Exception:
            pass
        return jsonify({"ok": True, "models": models, "current": engine.model, "provider": engine.provider.name})

    @app.route("/api/conversations", methods=["GET", "POST"])
    def api_conversations():
        if request.method == "GET":
            return jsonify({"ok": True, "conversations": list_conversations()})
        conv = {
            "id": uuid.uuid4().hex[:12],
            "title": "新对话",
            "created_at": time.time(),
            "updated_at": time.time(),
            "messages": [],
        }
        save_conversation(conv)
        return jsonify({"ok": True, "conversation": conv})

    @app.route("/api/conversations/<cid>", methods=["DELETE"])
    def api_conversation_delete(cid):
        if not delete_conversation(cid):
            return jsonify({"ok": False, "error": "会话不存在"}), 404
        return jsonify({"ok": True})

    @app.route("/api/conversations/<cid>/messages")
    def api_conversation_messages(cid):
        conv = load_conversation(cid)
        if conv is None:
            return jsonify({"ok": False, "error": "会话不存在"}), 404
        return jsonify({"ok": True, "title": conv.get("title", "新对话"), "messages": conv.get("messages", [])})

    @app.route("/api/config", methods=["POST"])
    def api_config():
        data = request.get_json(silent=True) or {}
        cfg = load_json(CONFIG_PATH / "config.json", {})
        ai = cfg.setdefault("ai", {})
        if data.get("provider"):
            ai["provider"] = data["provider"]
        if "confirm_tools" in data:
            ai["confirm_tools"] = bool(data["confirm_tools"])
        cloud = ai.setdefault("cloud", {})
        # 字段只要出现在请求中就覆盖（含空串清空）
        for field in ("base_url", "api_key", "model"):
            if field in data:
                cloud[field] = (data.get(field) or "").strip()
        save_json(CONFIG_PATH / "config.json", cfg)

        # 云端配置完整性校验（不做网络请求，避免阻塞）
        msg = "配置已保存"
        if data.get("provider") == "cloud":
            from .ai_engine import AIEngine
            if not cloud.get("base_url") or not cloud.get("api_key") or not cloud.get("model"):
                msg = "配置已保存（云端信息不完整，请补全）"
            else:
                engine = AIEngine()
                engine.provider.close()
                msg = "云端 API 配置已保存，可在对话中使用"
        return jsonify({"ok": True, "message": msg})

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        from .ai_engine import AIEngine
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "消息不能为空"}), 400
        conv_id = (data.get("conversation_id") or "").strip()
        engine = AIEngine()
        # 用户选择模型优先
        chosen = (data.get("model") or "").strip()
        if chosen:
            engine.model = chosen
        if not engine.model:
            engine.provider.close()
            return jsonify({"ok": False, "error": "未配置 AI 模型：请在「设置」中配置云端 API 或启动本地 Ollama"})
        # 会话归属
        if not conv_id:
            conv_id = uuid.uuid4().hex[:12]
            save_conversation({"id": conv_id, "title": "新对话", "created_at": time.time(),
                               "updated_at": time.time(), "messages": []})
        sess = ChatSession(uuid.uuid4().hex[:12], engine, conv_id=conv_id, user_message=message)
        # 会话数保护，防止内存无限增长
        if len(_SESSIONS) > 30:
            for old_sid, old in list(_SESSIONS.items()):
                if not old.running:
                    old.engine.provider.close()
                    _SESSIONS.pop(old_sid, None)
        _SESSIONS[sess.id] = sess
        sess.start(message)
        return jsonify({"ok": True, "session_id": sess.id, "conversation_id": conv_id})

    @app.route("/api/confirm/<sid>", methods=["POST"])
    def api_confirm(sid):
        data = request.get_json(silent=True) or {}
        sess = _SESSIONS.get(sid)
        if not sess:
            return jsonify({"ok": False, "error": "会话不存在或已超时"}), 404
        sess.confirm(bool(data.get("approved", False)))
        return jsonify({"ok": True})

    @app.route("/api/stop/<sid>", methods=["POST"])
    def api_stop(sid):
        """停止本会话的生成"""
        sess = _SESSIONS.get(sid)
        if not sess:
            return jsonify({"ok": False, "error": "会话不存在或已结束"}), 404
        sess.stop()
        return jsonify({"ok": True})

    @app.route("/api/stream/<sid>")
    def api_stream(sid):
        sess = _SESSIONS.get(sid)
        if not sess:
            return jsonify({"ok": False, "error": "会话不存在"}), 404

        def generate():
            try:
                while True:
                    try:
                        item = sess.queue.get(timeout=30)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    if item.get("type") == "done":
                        break
            finally:
                try:
                    sess.engine.provider.close()
                except Exception:
                    pass
                _SESSIONS.pop(sid, None)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def run_web_server(host: str = None, port: int = None):
    """启动 Web 服务器（阻塞）"""
    cfg = load_json(CONFIG_PATH / "config.json", {}).get("web", {})
    host = host or cfg.get("host", "0.0.0.0")
    port = int(port or cfg.get("port", 7860))
    app = create_app()
    print(f"  [web] AI 智能桌面助手网页版已启动: http://{host}:{port}")
    print("  [web] 按 Ctrl+C 停止")
    try:
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
