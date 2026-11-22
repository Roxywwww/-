"""双击入口：用启动本文件的 Python 检查依赖，缺少时安装，然后运行采集。"""
from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def dependency_ready():
    try:
        serial = importlib.import_module('serial')
        importlib.import_module('serial.tools.list_ports')
        return (hasattr(serial, 'Serial')
                and importlib.metadata.version('pyserial') == '3.5')
    except (ImportError, importlib.metadata.PackageNotFoundError):
        return False


def ensure_dependencies():
    if dependency_ready():
        print('依赖检查通过：pySerial 3.5。', flush=True)
        return True
    print('正在为当前 Python 安装串口库；首次使用请保持联网。', flush=True)
    user_args = [] if sys.prefix != sys.base_prefix else ['--user']
    if subprocess.run([sys.executable, '-m', 'pip', '--version'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        if subprocess.run([sys.executable, '-m', 'ensurepip', '--upgrade',
                           *user_args]).returncode:
            print('无法准备 pip，请修复 Python 安装后重试。', flush=True)
            return False
    result = subprocess.run([
        sys.executable, '-m', 'pip', 'install', *user_args,
        '--disable-pip-version-check', '--no-input', '--timeout', '20',
        '--retries', '1', '-r', str(HERE / 'requirements.txt')])
    if result.returncode:
        print('依赖安装失败，采集尚未开始。请检查上方网络或权限提示后重试。', flush=True)
        return False
    # 安装后的新进程重新读取包及用户 site 目录，避免使用缓存的错误 serial 模块。
    check = subprocess.run([sys.executable, '-c',
        'import serial; from serial.tools import list_ports; '
        'from importlib.metadata import version; '
        'assert hasattr(serial, "Serial") and version("pyserial") == "3.5"'])
    if check.returncode:
        print('串口库检查仍未通过，采集尚未开始。请检查是否存在同名 serial.py。', flush=True)
        return False
    return True


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    mode = args.pop(0) if args and args[0] in ('normal', 'long') else 'normal'
    if sys.version_info < (3, 10):
        print('需要 Python 3.10 或更新版本。')
        return 2
    if not ensure_dependencies():
        return 2
    target = HERE / ('long_capture.py' if mode == 'long' else 'collect_serial.py')
    return subprocess.run([sys.executable, '-u', str(target), *args]).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
