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
    monkeypatch.setattr(web_server, "CONFIG_PATH", cfg_dir)
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
