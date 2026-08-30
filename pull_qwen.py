#!/usr/bin/env python3
"""
从 Ollama 拉取中文小模型（独立脚本）
用法: python pull_qwen.py [模型名]
"""
import json
import sys
import time
from typing import NoReturn

import requests

OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:0.5b"


def main() -> NoReturn:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"正在拉取 {model_name}（约 300MB，阿里千问，中文效果最佳）...")
    print()

    start = time.time()
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=600,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"连接 Ollama 失败: {e}")
        sys.exit(1)

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = data.get("status", "")
        if "downloading" in status:
            total = data.get("total", 0)
            completed = data.get("completed", 0)
            if total:
                pct = completed / total * 100
                bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
                print(f"\r  [{bar}] {pct:.0f}%", end="")
            else:
                print(f"\r  {status}", end="")
        elif status == "success":
            elapsed = time.time() - start
            print(f"\n  完成！耗时 {elapsed:.0f}s")
            break
        else:
            print(f"\r  {status}")

    resp.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
