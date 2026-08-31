"""Web 服务器测试 - 会话确认逻辑、SSE 端点、配置保存"""

import json

import pytest


class FakeAIEngine:
    """模拟 AI 引擎：第一次回复后请求确认工具，确认后继续"""

    def __init__(self):
        self.model = "test-model"
        self.confirm_tools = True
        self.provider = FakeProvider()
        self.session = object()

    def chat(self, message):
        from src.ai_engine import ConfirmRequest

        def _gen():
            yield "我先看看系统信息"
            req = ConfirmRequest(
                plan="查看系统信息",
                tool_calls=[{"name": "task_run", "args": {"name": "系统信息"}}],
            )
            decision = yield req
            if decision:
                yield "\n  [执行: task_run] OK."
                yield "查询完成，系统正常。"
            else:
                yield "\n  [已取消]"

        return _gen()

    def list_available_models(self):
        return [{"name": "test-model", "size": "1.0 GB", "params": "?", "quant": "?", "provider": "ollama"}]


class FakeProvider:
    name = "ollama"

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    import src.ai_engine as ai_mod  # noqa: I001
    from src import web_server
    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)
    # 使用临时配置目录，避免污染真实 config.json
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps({"ai": {"provider": "auto", "confirm_tools": True, "cloud": {}}}),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(web_server, "CONFIG_PATH", cfg_dir)
    monkeypatch.setattr(web_server, "DATA_PATH", data_dir)
    app = web_server.create_app()
    app.testing = True
    return app.test_client()


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "智能桌面助手" in resp.get_data(as_text=True)


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["provider"] in ("ollama", "cloud")
    assert "model" in data


def test_chat_no_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 400


def test_chat_starts_session(client):
    resp = client.post("/api/chat", json={"message": "帮我查系统信息"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["session_id"]


def test_session_confirm_flow(monkeypatch):
    """核心：会话线程 文本→确认→确认后继续→done"""
    import src.ai_engine as ai_mod
    from src import web_server
    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)

    sess = web_server.ChatSession("s1", FakeAIEngine())
    sess.start("hi")

    # 读取事件：应为 text → confirm
    ev1 = sess.queue.get(timeout=5)
    assert ev1["type"] == "text"
    assert "系统信息" in ev1["content"]

    ev2 = sess.queue.get(timeout=5)
    assert ev2["type"] == "confirm"
    assert "查看系统信息" in ev2["plan"]
    assert ev2["tools"][0]["name"] == "task_run"

    # 确认执行 → 继续输出文本直至 done
    sess.confirm(True)
    texts_after = []
    while True:
        ev = sess.queue.get(timeout=5)
        if ev["type"] == "done":
            break
        texts_after.append(ev)
    joined = "".join(e.get("content", "") for e in texts_after)
    assert "执行" in joined
    assert "系统正常" in joined
    sess.thread.join(timeout=5)


def test_session_confirm_deny(monkeypatch):
    """拒绝时输出取消信息"""
    import src.ai_engine as ai_mod
    from src import web_server
    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)

    sess = web_server.ChatSession("s2", FakeAIEngine())
    sess.start("hi")
    sess.queue.get(timeout=5)   # text
    sess.queue.get(timeout=5)   # confirm

    sess.confirm(False)
    texts = []
    while True:
        ev = sess.queue.get(timeout=5)
        if ev["type"] == "done":
            break
        texts.append(ev)
    joined = "".join(e.get("content", "") for e in texts)
    assert "取消" in joined
    sess.thread.join(timeout=5)


def test_confirm_unknown_session(client):
    resp = client.post("/api/confirm/nonexistent", json={"approved": True})
    assert resp.status_code == 404


def test_config_save_clear(client):
    """保存并清空云端配置"""
    resp = client.post("/api/config", json={
        "provider": "cloud",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-x",
        "model": "m1",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp = client.post("/api/config", json={"base_url": "", "api_key": "", "model": ""})
    assert resp.status_code == 200


def test_models_endpoint(client):
    """模型列表接口返回可选项"""
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "models" in data
    assert "current" in data
    assert "provider" in data


def test_conversations_crud(client):
    """会话列表 / 新建 / 消息 / 删除"""
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.get_json()["conversations"] == []

    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    cid = resp.get_json()["conversation"]["id"]
    assert cid

    resp = client.get("/api/conversations")
    assert [c["id"] for c in resp.get_json()["conversations"]] == [cid]

    resp = client.get(f"/api/conversations/{cid}/messages")
    assert resp.status_code == 200
    assert resp.get_json()["messages"] == []

    resp = client.delete(f"/api/conversations/{cid}")
    assert resp.status_code == 200
    resp = client.get("/api/conversations")
    assert resp.get_json()["conversations"] == []


def test_conversation_404(client):
    resp = client.get("/api/conversations/nonexistent/messages")
    assert resp.status_code == 404
    resp = client.delete("/api/conversations/nonexistent")
    assert resp.status_code == 404


def test_chat_persists_messages(client):
    """对话完成后，消息持久化到会话文件"""
    from src import web_server

    # 先创建会话
    resp = client.post("/api/conversations")
    cid = resp.get_json()["conversation"]["id"]

    resp = client.post("/api/chat", json={"message": "帮我查系统信息", "conversation_id": cid})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["conversation_id"] == cid
    sid = data["session_id"]

    sess = web_server._SESSIONS[sid]
    # 读取事件直至 done（自动确认）
    while True:
        ev = sess.queue.get(timeout=5)
        if ev["type"] == "confirm":
            sess.confirm(True)
        if ev["type"] == "done":
            break

    conv = web_server.load_conversation(cid)
    assert conv is not None
    roles = [m["role"] for m in conv["messages"]]
    assert "user" in roles
    assert "assistant" in roles
    assert conv["title"] == "帮我查系统信息"


def test_stop_unknown_session(client):
    resp = client.post("/api/stop/nonexistent")
    assert resp.status_code == 404


def test_access_token_gate(monkeypatch, tmp_path):
    """配置 web.access_token 后，/api/* 需携带 X-Auth-Token"""
    import src.ai_engine as ai_mod
    from src import web_server
    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)

    cfg_dir = tmp_path / "cfg2"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps({"web": {"access_token": "secret123"}}),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data2"
    data_dir.mkdir()
    monkeypatch.setattr(web_server, "CONFIG_PATH", cfg_dir)
    monkeypatch.setattr(web_server, "DATA_PATH", data_dir)
    app = web_server.create_app()
    app.testing = True
    c = app.test_client()

    # 无口令 → 401
    resp = c.get("/api/status")
    assert resp.status_code == 401
    # 页面本身不受限
    resp = c.get("/")
    assert resp.status_code == 200
    # 口令错误 → 401
    resp = c.get("/api/status", headers={"X-Auth-Token": "wrong"})
    assert resp.status_code == 401
    # 口令正确 → 200
    resp = c.get("/api/status", headers={"X-Auth-Token": "secret123"})
    assert resp.status_code == 200


def test_access_token_off_by_default(client):
    """默认不配置口令时，所有接口行为不变"""
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_stop_endpoint_while_running(client):
    """生成中调用 /api/stop 后会话正常结束，不再输出新内容"""
    from src import web_server

    resp = client.post("/api/chat", json={"message": "帮我查系统信息"})
    sid = resp.get_json()["session_id"]
    sess = web_server._SESSIONS[sid]
    sess.queue.get(timeout=5)  # 第一条 text

    resp = client.post(f"/api/stop/{sid}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # 会话线程应自行结束
    sess.thread.join(timeout=5)
    assert sess.thread.is_alive() is False
    assert sess.running is False


def test_session_stop_flag(monkeypatch):
    """stop() 设置停止标志，线程最终收到 done 事件"""
    import src.ai_engine as ai_mod
    from src import web_server
    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)

    sess = web_server.ChatSession("s-stop", FakeAIEngine())
    sess.start("hi")
    sess.queue.get(timeout=5)  # text
    sess.stop()

    # 停止后剩余事件应为 done
    while True:
        ev = sess.queue.get(timeout=5)
        if ev["type"] == "done":
            break
    sess.thread.join(timeout=5)
    assert sess.running is False
