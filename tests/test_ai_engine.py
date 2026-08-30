"""AI 引擎测试 - 对话历史裁剪与工具解析"""

from src.ai_engine import AIEngine


class TestHistoryTrim:
    def test_history_never_exceeds_limit(self):
        engine = AIEngine()
        engine.max_history = 5
        for i in range(50):
            engine._append_history("user", f"msg-{i}")
        # max_history=5 -> limit=10 条
        assert len(engine.conversation_history) <= 10
        # 保留的是最新的消息
        assert engine.conversation_history[-1]["content"] == "msg-49"

    def test_history_within_limit_kept(self):
        engine = AIEngine()
        engine.max_history = 20
        for i in range(3):
            engine._append_history("user", f"m{i}")
        assert len(engine.conversation_history) == 3

    def test_clear_history(self, capsys):
        engine = AIEngine()
        engine._append_history("user", "hello")
        engine.clear_history()
        assert engine.conversation_history == []


class TestKeywordTools:
    def test_system_info_keyword(self):
        engine = AIEngine()
        tool = engine._try_keyword_tool("帮我看看系统信息")
        assert tool == {"name": "task_run", "args": {"name": "系统信息"}}

    def test_list_files_keyword(self):
        engine = AIEngine()
        tool = engine._try_keyword_tool("列出文件")
        assert tool["name"] == "file_list"

    def test_no_match(self):
        engine = AIEngine()
        assert engine._try_keyword_tool("今天天气怎么样？") is None


class TestBuildMessages:
    def test_includes_system_prompt(self):
        engine = AIEngine()
        engine._append_history("user", "hi")
        msgs = engine._build_messages()
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "hi"}
