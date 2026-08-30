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

from flask import Flask, Response, jsonify, render_template_string, request

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

/* ========== 侧边栏 ========== */
#sidebar { width: 260px; background: var(--sidebar); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; flex-shrink: 0; transition: margin-left .25s; }
#sidebar.hidden { margin-left: -260px; }
.sidebar-head { padding: 14px 12px; display: flex; gap: 8px; border-bottom: 1px solid var(--border); }
.btn { background: #f2f3f5; color: var(--text); border: 1px solid var(--border); padding: 7px 12px;
       border-radius: 8px; cursor: pointer; font-size: 13px; transition: background .15s; white-space: nowrap; }
.btn:hover { background: #e7e9ee; }
.btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn.primary:hover { background: var(--primary-dark); }
.btn.danger { background: transparent; border-color: transparent; color: #f04142; padding: 2px 6px; font-size: 15px; line-height: 1; }
.btn.danger:hover { background: #fde8e8; }
.btn.ghost { background: transparent; border-color: transparent; }
.btn.sm { padding: 4px 8px; font-size: 12px; }
.btn.stop { background: #f04142; border-color: #f04142; color: #fff; }
.btn.stop:hover { background: #d93838; }
#newChatBtn { flex: 1; }
#convList { flex: 1; overflow-y: auto; padding: 8px; }
.conv-item { display: flex; align-items: center; gap: 6px; padding: 10px 10px; margin-bottom: 2px;
             border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text);
             transition: background .12s; }
.conv-item:hover { background: var(--sidebar-hover); }
.conv-item.active { background: var(--sidebar-hover); }
.conv-item .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-item .d { flex-shrink: 0; display: none; }
.conv-item:hover .d { display: block; }

/* ========== 主区域 ========== */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#topbar { height: 52px; background: var(--sidebar); border-bottom: 1px solid var(--border);
          display: flex; align-items: center; padding: 0 16px; gap: 10px; flex-shrink: 0; }
#title { font-size: 15px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
#modelTag { color: var(--text-sub); font-size: 12px; white-space: nowrap; }
#modelSelect { background: var(--sidebar); color: var(--text); border: 1px solid var(--border);
               padding: 6px 10px; border-radius: 8px; font-size: 13px; outline: none; max-width: 220px; min-width: 0; }
.btn.icon { width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center;
            justify-content: center; font-size: 16px; flex-shrink: 0; }
#menuBtn { display: inline-flex; align-items: center; justify-content: center;
           width: 34px; height: 34px; padding: 0; font-size: 17px; border: 1px solid var(--border);
           background: var(--bg); color: var(--text); border-radius: 8px; cursor: pointer; flex-shrink: 0; }
#menuBtn:hover { background: var(--sidebar-hover); }
#settingsTopBtn { flex-shrink: 0; }

@media (max-width: 768px) {
  #sidebar { position: fixed; left: 0; top: 0; bottom: 0; z-index: 50; width: 85vw; max-width: 300px;
             box-shadow: 2px 0 12px rgba(0,0,0,.2); }
  #sidebar.hidden { margin-left: -300px; }
  #topbar { padding: 0 10px; gap: 8px; }
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
}
</style>
</head>
<body>

<!-- 侧边栏 -->
<div id="sidebar" class="hidden">
  <div class="sidebar-head" onclick="if(!event.target.closest('button'))toggleSidebar()" title="点击空白处收起">
    <button class="btn primary" id="newChatBtn">+ 新建对话</button>
  </div>
  <div id="convList"></div>
</div>

<!-- 主区域 -->
<div id="main">
  <div id="topbar">
    <button class="btn icon" id="menuBtn" onclick="toggleSidebar()" title="历史会话">&#9776;</button>
    <div id="title">新对话</div>
    <span id="modelTag"></span>
    <select id="modelSelect" title="切换模型" onchange="onModelChange()"></select>
    <button class="btn" id="settingsTopBtn" onclick="openSettings()">设置</button>
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

<script>
let state = { convId: null, es: null, thinkingEl: null, busy: false, model: '' };
let convs = [];

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
  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
    .replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
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
  sb.classList.toggle('hidden');
}
function closeSidebarIfMobile() { if (window.innerWidth <= 768) document.getElementById('sidebar').classList.add('hidden'); }

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
  try {
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
  const r = await fetch('/api/status');
  const d = await r.json();
  document.getElementById('provider').value = d.provider === 'cloud' ? 'cloud' : (d.provider === 'ollama' ? 'ollama' : 'auto');
  document.getElementById('baseUrl').value = d.cloud_base_url || '';
  document.getElementById('apiKey').value = '';
  document.getElementById('cloudModel').value = d.cloud_model || '';
  document.getElementById('confirmTools').value = d.confirm_tools ? 'true' : 'false';
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


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(PAGE_TEMPLATE)

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

        # 云端校验
        msg = "配置已保存"
        if data.get("provider") == "cloud":
            from .ai_engine import AIEngine, ProviderError
            if not cloud.get("base_url") or not cloud.get("api_key") or not cloud.get("model"):
                msg = "配置已保存（云端信息不完整，请补全）"
            else:
                try:
                    engine = AIEngine()
                    engine.provider.close()
                    msg = "云端 API 配置已保存并校验通过"
                except ProviderError as e:
                    msg = f"配置已保存，但校验未通过: {e}"
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
