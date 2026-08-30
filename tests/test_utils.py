"""公共工具模块测试"""
import json
from pathlib import Path

from src.utils import dir_size, format_size, load_json, save_json


class TestFormatSize:
    def test_basic_units(self):
        assert format_size(0) == "0.0 B"
        assert format_size(512) == "512.0 B"
        assert format_size(1536) == "1.5 KB"

    def test_negative_clamped(self):
        assert format_size(-5) == "0.0 B"

    def test_large_values(self):
        assert "MB" in format_size(1024 * 1024)
        assert "GB" in format_size(1024 * 1024 * 1024)


class TestJsonHelpers:
    def test_load_missing_file(self, tmp_path: Path):
        assert load_json(tmp_path / "nope.json", "fallback") == "fallback"

    def test_load_invalid(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert load_json(bad, {"x": 1}) == {"x": 1}

    def test_load_valid(self, tmp_path: Path):
        f = tmp_path / "good.json"
        f.write_text(json.dumps({"a": 1}), encoding="utf-8")
        assert load_json(f) == {"a": 1}

    def test_save_and_reload(self, tmp_path: Path):
        f = tmp_path / "out.json"
        assert save_json(f, {"k": [1, 2]})
        assert load_json(f) == {"k": [1, 2]}

    def test_save_creates_parents(self, tmp_path: Path):
        f = tmp_path / "a" / "b" / "c.json"
        assert save_json(f, {})
        assert f.exists()


class TestDirSize:
    def test_empty_dir(self, tmp_path: Path):
        assert dir_size(tmp_path) == 0

    def test_counts_files(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.bin").write_bytes(b"y" * 250)
        assert dir_size(tmp_path) == 350

    def test_missing_dir(self, tmp_path: Path):
        assert dir_size(tmp_path / "missing") == 0
