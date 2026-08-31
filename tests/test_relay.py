"""API 中转站测试 - 子 Key CRUD、端到端转发、配额、流式、日志"""

import json
import time


def make_manager(tmp_path):
    from src.relay import RelayManager

    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return RelayManager(config_path=cfg / "relay.json", log_path=data / "relay_logs.jsonl")


def make_app(tmp_path):
    from src import web_server

    mgr = make_manager(tmp_path)
    app = web_server.create_app(relay_manager=mgr)
    app.testing = True
    return app.test_client(), mgr


class FakeUpstream:
    """模拟统一上游：记录请求、返回固定 chat.completions 响应"""

    last_request = None
    mode = "ok"  # ok | error
    fail_mode = None  # timeout | connection

    @classmethod
    def handler(cls, url, headers=None, json=None, timeout=None, **kw):
        cls.last_request = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        if cls.fail_mode == "timeout":
            raise TimeoutError("timeout")
        if cls.fail_mode == "connection":
            raise ConnectionError("conn")
        if cls.mode == "error":
            class Resp:
                status_code = 500
                text = "server error"

                @staticmethod
                def json():
                    return {"error": {"message": "upstream boom"}}
            return Resp()
        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "id": "chatcmpl-test",
                    "model": json.get("model"),
                    "choices": [{"message": {"role": "assistant", "content": "你好，我是中转回复"}, "index": 0}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
        return Resp()


def setup_upstream(client, base_url="https://up.example.com/v1", api_key="sk-master"):
    resp = client.post("/api/relay/upstream", json={
        "base_url": base_url, "api_key": api_key, "model": "deepseek-chat", "timeout": 30,
    })
    assert resp.status_code == 200
    return resp.get_json()


def create_key(client, **kw):
    data = {"name": kw.get("name", "测试子API"), "models": kw.get("models", ["deepseek-chat"]),
            "quota": kw.get("quota", {})}
    resp = client.post("/api/relay/keys", json=data)
    assert resp.status_code == 201
    return resp.get_json()["key"]


# ---------------- CRUD ----------------

def test_upstream_save_masked(tmp_path):
    client, _ = make_app(tmp_path)
    resp = client.post("/api/relay/upstream", json={"base_url": "https://up.example.com/v1", "api_key": "sk-master"})
    assert resp.status_code == 200
    up = resp.get_json()["upstream"]
    assert "sk-master" not in up.get("api_key", "")
    assert resp.get_json()["ready"] is True

    resp = client.get("/api/relay/upstream")
    assert resp.get_json()["upstream"]["base_url"] == "https://up.example.com/v1"


def test_key_crud(tmp_path):
    client, _ = make_app(tmp_path)
    setup_upstream(client)

    # 创建
    resp = client.post("/api/relay/keys", json={"name": "客厅", "models": ["deepseek-chat"], "quota": {"max_calls": 10}})
    assert resp.status_code == 201
    k = resp.get_json()["key"]
    kid = k["id"]
    assert k["key"].startswith("sk-relay-")
    assert len(k["key"]) >= 32
    # 界面列表可随时查看完整 key
    resp = client.get("/api/relay/keys")
    got = resp.get_json()["keys"]
    assert any(x["id"] == kid and x["key"] == k["key"] for x in got)

    # 编辑
    resp = client.put(f"/api/relay/keys/{kid}", json={"name": "客厅Pro", "models": ["deepseek-chat", "qwen-max"], "status": "disabled"})
    assert resp.status_code == 200
    k2 = resp.get_json()["key"]
    assert k2["name"] == "客厅Pro"
    assert k2["status"] == "disabled"
    assert k2["models"] == ["deepseek-chat", "qwen-max"]

    # 重置
    resp = client.post(f"/api/relay/keys/{kid}/reset")
    assert resp.status_code == 200
    assert resp.get_json()["key"]["usage"]["calls"] == 0

    # 删除
    resp = client.delete(f"/api/relay/keys/{kid}")
    assert resp.status_code == 200
    resp = client.get("/api/relay/keys")
    assert all(x["id"] != kid for x in resp.get_json()["keys"])

    # 不存在
    resp = client.delete("/api/relay/keys/nope")
    assert resp.status_code == 404


# ---------------- 端到端转发 ----------------

def test_v1_forward_sync(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, quota={"max_calls": 0})

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "你好"}]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["choices"][0]["message"]["content"] == "你好，我是中转回复"
    assert body["usage"]["total_tokens"] == 15
    # 透传检查：上游收到主 Key 与 body
    assert FakeUpstream.last_request["headers"]["Authorization"] == "Bearer sk-master"
    assert FakeUpstream.last_request["json"]["model"] == "deepseek-chat"
    assert "stream" not in FakeUpstream.last_request["json"]
    # 用量已统计
    resp = client.get("/api/relay/keys")
    got = [x for x in resp.get_json()["keys"] if x["id"] == k["id"]][0]
    assert got["usage"]["calls"] == 1
    assert got["usage"]["tokens"] == 15


def test_v1_forward_tools_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client)

    tools = [{"type": "function", "function": {"name": "get_time", "description": "获取时间", "parameters": {"type": "object", "properties": {}}}}]
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "几点了"}], "tools": tools})
    assert resp.status_code == 200
    assert FakeUpstream.last_request["json"]["tools"] == tools


def test_v1_invalid_or_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    client, _ = make_app(tmp_path)
    resp = client.post("/v1/chat/completions", json={"model": "x", "messages": []})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["type"] == "invalid_key"
    resp = client.post("/v1/chat/completions", headers={"Authorization": "Bearer sk-bogus"},
                       json={"model": "x", "messages": []})
    assert resp.status_code == 401


def test_v1_disabled_key(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client)
    client.put(f"/api/relay/keys/{k['id']}", json={"status": "disabled"})

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 403
    assert resp.get_json()["error"]["type"] == "disabled"


def test_v1_upstream_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    client, _ = make_app(tmp_path)
    # 不配置上游
    k = create_key(client)
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 503


def test_v1_model_not_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, models=["deepseek-chat"])

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "qwen-max", "messages": []})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["type"] == "model_not_allowed"


# ---------------- 配额 ----------------

def test_quota_max_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, quota={"max_calls": 2})

    for _ in range(2):
        resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                           json={"model": "deepseek-chat", "messages": []})
        assert resp.status_code == 200
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 429
    assert resp.get_json()["error"]["type"] == "quota_exceeded"


def test_quota_max_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    # 每次调用 15 tokens，上限 10 → 第 2 次应超限
    k = create_key(client, quota={"max_tokens": 10})
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 200
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 429


def test_quota_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, quota={"daily_limit": 1})
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 200
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 429


def test_quota_concurrent(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, mgr = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, quota={"max_concurrent": 1})

    # 用 manager 直接占用并发位
    key_obj = mgr.get_key_by_token(k["key"])
    mgr.check_quota(key_obj)  # acquire 成功
    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 429
    assert resp.get_json()["error"]["type"] == "concurrency_limited"
    mgr.release(key_obj)


# ---------------- 流式 ----------------

class FakeStreamUpstream:
    @classmethod
    def handler(cls, url, headers=None, json=None, timeout=None, **kw):
        class Resp:
            status_code = 200

            @staticmethod
            def iter_content(chunk_size=4096):
                yield 'data: {"id":"s1","choices":[{"delta":{"content":"你"}}]}\n\n'.encode()
                yield 'data: {"id":"s1","choices":[{"delta":{"content":"好"}}]}\n\n'.encode()
                yield b"data: [DONE]\n\n"

            @staticmethod
            def close():
                pass
        return Resp()


def test_v1_stream(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeStreamUpstream.handler)
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client)

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "stream": True, "messages": []})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/event-stream")
    text = resp.get_data(as_text=True)
    assert '{"content":"你"}' in text
    assert '{"content":"好"}' in text
    assert "[DONE]" in text
    # 流式调用也计数
    resp = client.get("/api/relay/keys")
    got = [x for x in resp.get_json()["keys"] if x["id"] == k["id"]][0]
    assert got["usage"]["calls"] == 1


# ---------------- 日志 ----------------

def test_logs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client, name="日志测试")

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 200
    time.sleep(0.01)
    resp = client.post("/v1/chat/completions", headers={"Authorization": "Bearer sk-bogus"},
                       json={"model": "deepseek-chat", "messages": []})

    resp = client.get("/api/relay/logs")
    logs = resp.get_json()["logs"]
    assert len(logs) == 2
    # 时间倒序：最近一次是无效 Key 的 401
    assert logs[0]["status_code"] == 401
    assert logs[0]["key_name"] == "无效Key"
    assert any(e["key_name"] == "日志测试" and e["status_code"] == 200 for e in logs)
    assert any(e["tokens"] == 15 for e in logs)

    resp = client.get("/api/relay/logs?name=日志测试")
    assert all(e["key_name"] == "日志测试" for e in resp.get_json()["logs"])


def test_upstream_error_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "error"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client)

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"]["message"] == "upstream boom"


def test_upstream_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.fail_mode = "timeout"
    client, _ = make_app(tmp_path)
    setup_upstream(client)
    k = create_key(client)

    resp = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                       json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 502


def test_access_token_does_not_gate_v1(tmp_path, monkeypatch):
    """web.access_token 只拦 /api/* 管理接口，/v1/chat/completions 走子 Key 鉴权"""
    import src.ai_engine as ai_mod
    import src.web_server as web_server
    from src.relay import RelayManager

    monkeypatch.setattr("src.web_server.requests.post", FakeUpstream.handler)
    FakeUpstream.mode = "ok"
    FakeUpstream.fail_mode = None

    class FakeAIEngine:
        model = "test-model"
        confirm_tools = True

        class provider:
            name = "ollama"

            @staticmethod
            def close():
                pass

        def list_available_models(self):
            return []

    monkeypatch.setattr(ai_mod, "AIEngine", FakeAIEngine)

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(
        json.dumps({"web": {"access_token": "secret123"}}), encoding="utf-8"
    )
    monkeypatch.setattr(web_server, "CONFIG_PATH", cfg_dir)
    monkeypatch.setattr(web_server, "DATA_PATH", tmp_path / "data")

    mgr = RelayManager(config_path=tmp_path / "relay.json", log_path=tmp_path / "relay_logs.jsonl")
    app = web_server.create_app(relay_manager=mgr)
    app.testing = True
    c = app.test_client()

    # 管理接口无口令 → 401
    assert c.get("/api/relay/keys").status_code == 401
    # 带口令 → 200
    assert c.get("/api/relay/keys", headers={"X-Auth-Token": "secret123"}).status_code == 200

    # 配置上游 + 创建子 Key
    c.post("/api/relay/upstream", json={"base_url": "https://up.example.com/v1", "api_key": "sk-master"},
           headers={"X-Auth-Token": "secret123"})
    k = c.post("/api/relay/keys", json={"name": "隔离测试"},
               headers={"X-Auth-Token": "secret123"}).get_json()["key"]

    # /v1/* 不经过管理口令：无 X-Auth-Token 也能用子 Key 调用
    resp = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {k['key']}"},
                  json={"model": "deepseek-chat", "messages": []})
    assert resp.status_code == 200
