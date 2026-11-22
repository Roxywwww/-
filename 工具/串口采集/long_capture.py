"""独立终端长时采集，采集期间阻止Windows自动空闲睡眠，退出后恢复。"""
import ctypes
import os
import sys

from collect_serial import main


def run(argv=None):
    release = None
    if os.name == 'nt':
        execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        execution_state.argtypes = [ctypes.c_uint]
        execution_state.restype = ctypes.c_uint
        if execution_state(0x80000001):  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            release = lambda: execution_state(0x80000000)
            print('长时记录已启用：采集期间阻止自动空闲睡眠，结束后恢复。')
        else:
            print('未能启用临时防休眠，请自行保持电脑唤醒。')
    print('不要关闭采集窗口、手动休眠或合盖；显示器可以自行熄屏。')
    try:
        return main(argv)
    finally:
        if release is not None:
            release()


if __name__ == '__main__':
    exit_code=run(sys.argv[1:])
    try:
        input('\n采集已结束，按回车关闭此窗口。')
    except (EOFError, KeyboardInterrupt):
        pass
    raise SystemExit(exit_code)
