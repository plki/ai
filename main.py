#!/usr/bin/env python3
"""
智能桌面助手 - 入口文件
AI Desktop Assistant
"""
import sys
import os
import atexit
import ctypes

# 确保能导入 src 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cleanup():
    """退出时清理资源"""
    try:
        from src.ai_engine import _cleanup_all_sessions
        _cleanup_all_sessions()
    except Exception:
        pass


atexit.register(cleanup)

# Windows 控制台事件常量
CTRL_C_EVENT = 0
CTRL_CLOSE_EVENT = 2


def _console_handler(ctrl_type):
    """处理 Windows 控制台事件（点 X / Ctrl+C / 关机等）"""
    if ctrl_type == CTRL_CLOSE_EVENT:
        # 点 X → 快速清理（Windows 只给 5 秒）
        cleanup()
    return 0  # 已处理


# 注册控制台事件处理器（捕获点 X 关窗口）
_handler_callback = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(_console_handler)
ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_callback, 1)


def main():
    """程序入口"""
    try:
        from src.cli import run_cli
        run_cli()
    except KeyboardInterrupt:
        pass  # run_cli 内已处理
    except EOFError:
        pass  # run_cli 内已处理
    except SystemExit:
        pass  # sys.exit() 调用
    except Exception as e:
        print(f"\n[ERROR] 程序异常退出: {e}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
