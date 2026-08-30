#!/usr/bin/env python3
"""
智能桌面助手 - 入口文件 (AI Desktop Assistant)
"""
import atexit
import os
import sys
from pathlib import Path

# 确保能导入 src 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))


def cleanup():
    """退出时清理资源"""
    try:
        from src.ai_engine import cleanup_all_sessions
        cleanup_all_sessions()
    except Exception:
        pass


atexit.register(cleanup)

# Windows 控制台事件处理（仅 Windows；非 Windows 上跳过，避免崩溃）
if os.name == "nt":
    import ctypes

    CTRL_C_EVENT = 0
    CTRL_CLOSE_EVENT = 2

    def _console_handler(ctrl_type):
        """处理 Windows 控制台事件（点 X / Ctrl+C / 关机等）"""
        if ctrl_type == CTRL_CLOSE_EVENT:
            # 点 X → 快速清理（Windows 只给 5 秒）
            cleanup()
        return 0  # 已处理

    def _register_console_handler():
        """注册控制台事件处理器（捕获点 X 关窗口）"""
        try:
            handler_callback = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(_console_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(handler_callback, 1)
        except Exception:
            pass

    _register_console_handler()


def main():
    """程序入口"""
    # `python main.py web` 启动网页版界面
    if len(sys.argv) > 1 and sys.argv[1] in ("web", "--web", "serve"):
        try:
            from src.web_server import run_web_server
            run_web_server()
            return
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"\n[ERROR] 网页版启动失败: {e}")
            return
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
