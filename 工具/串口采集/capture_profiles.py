"""Explicit sensor launchers with fixed, CWD-independent data destinations."""
from __future__ import annotations

from pathlib import Path
import sys
import start_capture

HERE = Path(__file__).resolve().parent
PROFILES = {
    '1kg': {'capacity': '1', 'coefficient': '736.8698', 'firmware': 'scale1kg_20261126'},
    '20kg': {'capacity': '20', 'coefficient': '178.20', 'firmware': ''},
}
RESERVED_META = {'capture_profile', 'sensor_capacity_kg', 'expected_counts_per_g',
                 'expected_firmware_id', 'profile_selection_source'}


def data_directory(profile, here=None):
    if profile not in PROFILES:
        raise ValueError('请选择1kg或20kg版本')
    folder = Path(here or HERE).resolve()
    for parent in folder.parents:
        if ((parent/'AGENTS.md').is_file()
                and (parent/'工具/串口采集').resolve() == folder):
            if profile == '1kg':
                return parent/'实验数据/1kg称重梁/原始数据/串口采集'
            return parent/'实验数据/原始数据/串口采集'
    return folder/'采集数据'/profile


def configured_arguments(profile, args, here=None):
    config = PROFILES[profile]
    for i, value in enumerate(args):
        if value == '--output' or value.startswith('--output='):
            raise ValueError('分量程入口固定保存目录，不接受--output；可把整套采集工具复制到希望保存的位置。')
        if value == '--meta' or value.startswith('--meta='):
            metadata = args[i+1] if value == '--meta' and i+1 < len(args) else value.partition('=')[2]
            if metadata.partition('=')[0].strip() in RESERVED_META:
                raise ValueError('采集版本、量程和期望系数由入口固定，不能通过--meta覆盖。')
    fixed = ['--output', str(data_directory(profile, here)),
             '--meta', 'capture_profile='+profile,
             '--meta', 'sensor_capacity_kg='+config['capacity'],
             '--meta', 'expected_counts_per_g='+config['coefficient'],
             '--meta', 'profile_selection_source=用户选择入口，不代表自动识别实际传感器']
    if config['firmware']:
        fixed += ['--meta', 'expected_firmware_id='+config['firmware']]
    if not any(arg == '--label' or arg.startswith('--label=') for arg in args):
        fixed += ['--label', profile+'串口采集']
    return fixed + list(args)


def run(profile, argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if profile not in PROFILES:
        raise ValueError('Unknown capture profile')
    print(f'采集版本：{profile}版（由入口选择）', flush=True)
    print(f'保存根目录：{data_directory(profile)}', flush=True)
    print('每次自动新建日期时间文件夹；采集器不改重量、不发送串口指令。', flush=True)
    if '--show-path' in args:
        if args != ['--show-path']:
            print('--show-path只能单独使用，不会启动采集。', file=sys.stderr)
            return 2
        return 0
    try:
        forwarded = configured_arguments(profile, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return start_capture.main(['long', *forwarded])


def choose(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ['--list']:
        return start_capture.main(['long', '--list'])
    print('请选择本次实际接入的称重梁：\n  1. 1kg版（当前736.8698计数/g）\n  2. 20kg版（历史178.20计数/g）')
    try:
        choice = input('输入1或2；q取消：').strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 2
    profile = {'1': '1kg', '1kg': '1kg', '2': '20kg', '20kg': '20kg'}.get(choice)
    if profile is None:
        print('已取消，未打开串口，也未创建采集目录。')
        return 2
    return run(profile, args)
