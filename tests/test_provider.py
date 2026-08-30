"""AI 引擎测试 - provider 抽象与云端 API 配置"""

import pytest

from src.ai_engine import (
    AIEngine,
    CloudProvider,
    ConfirmRequest,
    ProviderError,
)


class TestProviderSelection:
    def test_cloud_provider_configured(self, monkeypatch):
        """配置了 base_url/api_key 且 provider=cloud 时使用云端"""
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {
                "provider": "cloud",
                "cloud": {
                    "base_url": "https://api.example.com/v1",
                    "api_key": "sk-test",
                    "model": "test-model",
                },
            },
        )
        engine = AIEngine()
        assert engine.provider.name == "cloud"
        assert engine.model == "test-model"
        engine.cleanup()

    def test_auto_prefers_cloud(self, monkeypatch):
        """provider=auto 且云端配置完整时优先云端"""
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {
                "provider": "auto",
                "cloud": {
                    "base_url": "https://api.example.com/v1",
                    "api_key": "sk-test",
                    "model": "m",
                },
            },
        )
        engine = AIEngine()
        assert engine.provider.name == "cloud"
        engine.cleanup()

    def test_auto_falls_back_ollama(self, monkeypatch):
        """provider=auto 且无云端配置时用本地 Ollama"""
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {"provider": "auto", "cloud": {}, "ollama_host": "http://127.0.0.1:11434"},
        )
        engine = AIEngine()
        assert engine.provider.name == "ollama"
        engine.cleanup()

    def test_ollama_provider_explicit(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {"provider": "ollama", "cloud": {}, "ollama_host": "http://127.0.0.1:11434"},
        )
        engine = AIEngine()
        assert engine.provider.name == "ollama"
        engine.cleanup()


class TestCloudProvider:
    def test_check_incomplete(self):
        p = CloudProvider("", "", "")
        ok, msg = p.check()
        assert not ok
        assert "base_url" in msg

    def test_check_complete(self):
        p = CloudProvider("https://api.example.com/v1", "sk-1", "model-x")
        ok, msg = p.check()
        assert ok
        assert msg == "ok"

    def test_chat_url_build(self):
        p = CloudProvider("https://api.example.com/v1", "sk-1", "model-x")
        assert p._url() == "https://api.example.com/v1/chat/completions"
        # 已含 /chat/completions 时不重复拼接
        p2 = CloudProvider("https://api.example.com/v1/chat/completions", "sk-1", "m")
        assert p2._url() == "https://api.example.com/v1/chat/completions"

    def test_chat_connection_error(self, monkeypatch):
        """连接失败应抛出 ProviderError 而非裸异常"""
        p = CloudProvider("http://127.0.0.1:9", "sk-1", "m", timeout=2)

        class FakeSession:
            def post(self, *a, **k):
                import requests
                raise requests.exceptions.ConnectionError("conn")

        p.session = FakeSession()
        with pytest.raises(ProviderError):
            p.chat("m", [{"role": "user", "content": "hi"}], [])


class TestConfirmFlow:
    def test_confirm_request_dataclass(self):
        req = ConfirmRequest(plan="列出文件", tool_calls=[{"name": "file_list", "args": {}}])
        assert req.plan == "列出文件"
        assert req.tool_names == ["file_list"]

    def test_chat_yields_confirm_when_keyword_with_confirm_on(self, monkeypatch):
        """开启确认时，关键词快路径先 yield ConfirmRequest"""
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {"provider": "ollama", "cloud": {}, "confirm_tools": True},
        )
        engine = AIEngine()
        engine.model = "test"
        gen = engine.chat("帮我看看系统信息")
        first = next(gen)
        assert isinstance(first, ConfirmRequest)
        # 发送 False → 取消，不执行
        gen.send(False)
        for _ in gen:
            pass
        engine.cleanup()

    def test_chat_executes_without_confirm_when_off(self, monkeypatch, capsys):
        """关闭确认时直接执行，不 yield ConfirmRequest"""
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {"provider": "ollama", "cloud": {}, "confirm_tools": False},
        )
        engine = AIEngine()
        engine.model = "test"
        out = list(engine.chat("帮我看看系统信息"))
        assert not any(isinstance(x, ConfirmRequest) for x in out)
        assert any("[执行" in str(x) for x in out)
        engine.cleanup()


class TestListModels:
    def test_cloud_returns_configured_model(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_engine._load_ai_config",
            lambda: {
                "provider": "cloud",
                "cloud": {"base_url": "https://api.example.com/v1", "api_key": "k", "model": "m"},
            },
        )
        engine = AIEngine()
        models = engine.list_available_models()
        assert models and models[0]["name"] == "m"
        assert models[0]["provider"] == "cloud"
        engine.cleanup()
