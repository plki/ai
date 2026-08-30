"""
Web 服务器 - 为智能桌面助手提供浏览器界面

- SSE 流式输出 AI 回复（打字机效果）
- AI 工具调用前前端弹窗确认（思考→确认→执行）
- 支持切换 provider 与配置自己的云端 API（OpenAI 兼容）
"""
import json
import logging
import queue
import threading
import traceback
import uuid

from flask import Flask, Response, jsonify, render_template_string, request

from .utils import CONFIG_PATH, load_json, save_json

logger = logging.getLogger("web")

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>智能桌面助手</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #0f172a;
       color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; }
header { background: #1e293b; padding: 12px 20px; display: flex; align-items: center;
         justify-content: space-between; border-bottom: 1px solid #334155; }
header .logo { font-weight: 700; font-size: 17px; color: #38bdf8; }
header .sub { color: #94a3b8; font-size: 12px; margin-left: 8px; }
header .actions { display: flex; gap: 8px; }
.btn { background: #334155; color: #e2e8f0; border: 1px solid #475569; padding: 6px 14px;
       border-radius: 6px; cursor: pointer; font-size: 13px; transition: background .15s; }
.btn:hover { background: #475569; }
.btn.primary { background: #0ea5e9; border-color: #0ea5e9; color: #fff; }
.btn.primary:hover { background: #0284c7; }
.btn.danger { background: #ef4444; border-color: #ef4444; color: #fff; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
#chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.msg { max-width: 82%; padding: 10px 14px; border-radius: 12px; line-height: 1.65;
       white-space: pre-wrap; word-break: break-word; font-size: 14px; }
.msg.user { align-self: flex-end; background: #0ea5e9; color: #fff; border-bottom-right-radius: 3px; }
.msg.ai { align-self: flex-start; background: #1e293b; border: 1px solid #334155; border-bottom-left-radius: 3px; }
.msg.system { align-self: center; background: #3a2a1a; color: #fbbf24; border: 1px solid #92400e; font-size: 13px; }
.msg.tool { align-self: flex-start; background: #0c1a2a; border: 1px dashed #155e75; color: #67e8f9;
            font-family: monospace; font-size: 12.5px; max-width: 90%; }
#inputbar { background: #1e293b; padding: 12px 16px; display: flex; gap: 10px; border-top: 1px solid #334155; }
#input { flex: 1; background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 10px 12px;
         border-radius: 8px; font-size: 14px; outline: none; resize: none; min-height: 42px; max-height: 140px;
         font-family: inherit; }
#input:focus { border-color: #0ea5e9; }
.modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 100;
         align-items: center; justify-content: center; }
.modal.open { display: flex; }
.modal-box { background: #1e293b; border: 1px solid #334155; border-radius: 12px; width: 500px;
             max-width: 92%; padding: 20px; max-height: 90vh; overflow-y: auto; }
.modal-box h3 { margin-bottom: 14px; color: #38bdf8; }
.field { margin-bottom: 12px; }
.field label { display: block; font-size: 12px; color: #94a3b8; margin-bottom: 4px; }
.field input, .field select { width: 100%; background: #0f172a; border: 1px solid #334155; color: #e2e8f0;
                              padding: 8px 10px; border-radius: 6px; font-size: 13px; outline: none; }
.field input:focus, .field select:focus { border-color: #0ea5e9; }
.field .hint { font-size: 11px; color: #64748b; margin-top: 3px; line-height: 1.5; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.confirm-box { align-self: flex-start; background: #1e293b; border: 1px solid #7c3aed; border-radius: 12px;
               padding: 12px 14px; max-width: 90%; }
.confirm-box .plan { color: #e9d5ff; font-size: 13px; margin-bottom: 8px; line-height: 1.6; }
.confirm-box .btns { display: flex; gap: 8px; }
.thinking { align-self: flex-start; display: flex; align-items: center; gap: 8px; color: #94a3b8; font-size: 13px; }
.spinner { width: 14px; height: 14px; border: 2px solid #475569; border-top-color: #0ea5e9; border-radius: 50%;
           animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <div class="logo">AI 智能桌面助手 <span class="sub prod" id="modelTag"></span></div>
  <div class="actions">
    <button class="btn" onclick="openSettings()">设置</button>
    <button class="btn" onclick="clearChat()">清空对话</button>
  </div>
</header>

<div id="chat"></div>

<div id="inputbar">
  <textarea id="input" rows="1" placeholder="说出你的需求，AI 会先思考并提出计划，经你确认后再执行..."
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"></textarea>
  <button class="btn primary" id="sendBtn" onclick="send()">发送</button>
</div>

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
      <input id="cloudModel" placeholder="如 deepseek-chat / gpt-4o-mini">
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
let curSid = null;
let es = null;
let thinkingEl = null;

function addMsg(role, text) {
  const chat = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function addThinking() {
  const chat = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = 'thinking';
  el.innerHTML = '<span class="spinner"></span> AI 思考中...';
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  thinkingEl = el;
}

function removeThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

function addConfirm(plan, tools) {
  removeThinking();
  const chat = document.getElementById('chat');
  const box = document.createElement('div');
  box.className = 'confirm-box';
  box.innerHTML = '<div class="plan">计划执行：<b>' + escapeHtml(plan) + '</b></div>' +
    '<div class="plan" style="color:#94a3b8;font-size:12px;">' + escapeHtml('需要调用工具：' + (tools || []).map(t => t.name).join('、')) + '</div>' +
    '<div class="btns">' +
    '<button class="btn primary" id="yesBtn">允许执行</button>' +
    '<button class="btn danger" id="noBtn">拒绝</button>' +
    '</div>';
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
  document.getElementById('yesBtn').onclick = () => doConfirm(true);
  document.getElementById('noBtn').onclick = () => doConfirm(false);
}

function removeConfirm() {
  const box = document.querySelector('.confirm-box');
  if (box) box.remove();
}

async function doConfirm(approved) {
  if (!curSid) return;
  const box = document.querySelector('.confirm-box');
  if (box) box.querySelectorAll('.btn').forEach(b => b.disabled = true);
  try {
    await fetch('/api/confirm/' + curSid, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({approved: approved})
    });
  } catch (e) { console.error(e); }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function send() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text || es) return;                    // 有对话进行中则忽略
  input.value = '';
  addMsg('user', text);
  addThinking();
  document.getElementById('sendBtn').disabled = true;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text})
    });
    const data = await resp.json();
    if (!data.ok) {
      removeThinking();
      addMsg('system', '错误: ' + (data.error || '未知'));
      document.getElementById('sendBtn').disabled = false;
      return;
    }
    curSid = data.session_id;
    startStream(data.session_id);
  } catch (e) {
    removeThinking();
    addMsg('system', '请求失败: ' + e);
    document.getElementById('sendBtn').disabled = false;
  }
}

function startStream(sid) {
  const chat = document.getElementById('chat');
  let aiEl = null;
  es = new EventSource('/api/stream/' + sid);

  es.onopen = () => removeThinking();

  es.onmessage = function(ev) {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === 'text') {
        if (!aiEl) { aiEl = addMsg('ai', ''); }
        aiEl.textContent += data.content;
        chat.scrollTop = chat.scrollHeight;
      } else if (data.type === 'tool') {
        addMsg('tool', data.content);
      } else if (data.type === 'confirm') {
        addConfirm(data.plan, data.tools);
      } else if (data.type === 'error') {
        if (!aiEl) { aiEl = addMsg('ai', ''); }
        aiEl.textContent += '[错误] ' + data.content;
      } else if (data.type === 'done') {
        es.close(); es = null; curSid = null;
        removeThinking(); removeConfirm();
        document.getElementById('sendBtn').disabled = false;
        refreshStatus();
      }
    } catch (e) { console.error(e); }
  };
  es.onerror = function() {
    // 心跳中断会触发，忽略；客户端 keepalive 维持连接，不会真正 disable
  };
}

function clearChat() {
  document.getElementById('chat').innerHTML = '';
  if (es) { es.close(); es = null; }
  curSid = null;
  removeThinking();
  document.getElementById('sendBtn').disabled = false;
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const tag = document.getElementById('modelTag');
    tag.textContent = d.provider === 'cloud' ? ('云端 ' + (d.model || ''))
                     : d.provider === 'ollama' ? ('本地 ' + (d.model || ''))
                     : '未配置模型';
  } catch (e) {}
}

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

function closeSettings() {
  document.getElementById('settingsModal').classList.remove('open');
}

async function saveSettings() {
  const body = {
    provider: document.getElementById('provider').value,
    base_url: document.getElementById('baseUrl').value.trim(),
    api_key: document.getElementById('apiKey').value.trim(),
    model: document.getElementById('cloudModel').value.trim(),
    confirm_tools: document.getElementById('confirmTools').value === 'true'
  };
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const d = await r.json();
    addMsg('system', d.message || '已保存');
    closeSettings();
    refreshStatus();
  } catch (e) {
    addMsg('system', '保存失败: ' + e);
  }
}

refreshStatus();
</script>
</body>
</html>
"""


class ChatSession:
    """一次对话会话：后台线程运行 AIEngine，事件经队列推给 SSE"""

    def __init__(self, session_id: str, engine):
        self.id = session_id
        self.engine = engine
        self.queue = queue.Queue()
        self.confirm_event = threading.Event()
        self.decision = None
        self.thread = None
        self.running = False

    def start(self, message: str):
        self.running = True
        self.thread = threading.Thread(target=self._run, args=(message,), daemon=True)
        self.thread.start()

    def confirm(self, approved: bool):
        self.decision = approved
        self.confirm_event.set()

    def _run(self, message: str):
        try:
            gen = self.engine.chat(message)
            decision = None
            while True:
                if decision is None:
                    chunk = next(gen)
                else:
                    chunk = gen.send(decision)
                    decision = None
                if hasattr(chunk, "plan"):
                    tools = [{"name": tc.get("name", ""), "args": tc.get("args", {})}
                             for tc in getattr(chunk, "tool_calls", [])]
                    self.queue.put({"type": "confirm", "plan": chunk.plan, "tools": tools})
                    self.confirm_event.wait()
                    self.confirm_event.clear()
                    decision = self.decision
                    self.decision = None
                else:
                    self.queue.put({"type": "text", "content": chunk})
        except StopIteration:
            pass
        except Exception as e:
            logger.error("会话线程异常: %s", e)
            traceback.print_exc()
            self.queue.put({"type": "error", "content": str(e)})
        finally:
            self.queue.put({"type": "done"})
            self.running = False


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
        sid = uuid.uuid4().hex[:12]
        engine = AIEngine()
        if not engine.model:
            engine.provider.close()
            return jsonify({"ok": False, "error": "未配置 AI 模型：请在「设置」中配置云端 API 或启动本地 Ollama"})
        sess = ChatSession(sid, engine)
        # 会话数保护，防止内存无限增长
        if len(_SESSIONS) > 30:
            for old_sid, old in list(_SESSIONS.items()):
                if not old.running:
                    old.engine.provider.close()
                    _SESSIONS.pop(old_sid, None)
        _SESSIONS[sid] = sess
        sess.start(message)
        return jsonify({"ok": True, "session_id": sid})

    @app.route("/api/confirm/<sid>", methods=["POST"])
    def api_confirm(sid):
        data = request.get_json(silent=True) or {}
        sess = _SESSIONS.get(sid)
        if not sess:
            return jsonify({"ok": False, "error": "会话不存在或已超时"}), 404
        sess.confirm(bool(data.get("approved", False)))
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
    print(f"  [web] 智能桌面助手网页版已启动: http://{host}:{port}")
    print("  [web] 按 Ctrl+C 停止")
    try:
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
