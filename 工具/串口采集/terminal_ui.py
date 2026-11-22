"""Windows终端固定面板；只用标准库，不读写串口。"""
from __future__ import annotations

import os
import shutil
import sys
import time
import unicodedata


def columns(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
               for c in text)


def clipped(text, width, tail=False):
    # 外部消息不能把控制字符当作终端命令执行。
    text = ''.join(c if c.isprintable() else ' ' for c in str(text))
    if columns(text) <= width:
        return text
    result = ''
    for char in (reversed(text) if tail else text):
        if columns(result) + columns(char) > max(0, width - 1):
            break
        result = char + result if tail else result + char
    return '…' + result if tail else result + '…'


def enable_windows_vt():
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = kernel.GetStdHandle(-11 & 0xffffffff)
    mode = wintypes.DWORD()
    if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    if not kernel.SetConsoleMode(handle, mode.value | 0x0004):
        return None
    return lambda: kernel.SetConsoleMode(handle, mode.value)


class TerminalPanel:
    def __init__(self, enabled=True, stream=None):
        self.stream = stream or sys.stdout
        self.enabled = bool(enabled and os.name == 'nt'
                            and sys.stdin.isatty() and self.stream.isatty())
        self.restore_mode = enable_windows_vt() if self.enabled else None
        self.enabled = self.enabled and self.restore_mode is not None
        self.active = False
        self.text = ''
        self.skip_extended = False
        self.skip_lf = False
        self.notice = '请先输入 0 确认空载，或输入实际标称载荷。'
        self.dirty = True
        self.last_drawn = 0.0

    def start(self):
        if self.enabled:
            # 独立屏幕，正常结束回到原终端，不反复追加状态输出。
            self.stream.write('\x1b[?1049h\x1b[2J\x1b[H')
            self.stream.flush()
            self.active = True

    def close(self):
        if self.active:
            self.stream.write('\x1b[?25h\x1b[?1049l')
            self.stream.flush()
            self.active = False
        if self.restore_mode:
            self.restore_mode()
            self.restore_mode = None

    def notify(self, message):
        self.notice = message
        self.dirty = True
        if not self.active:
            print(message, file=self.stream)

    def feed_key(self, char):
        """按键只编辑输入框；串口线程不参与输入。"""
        if char == '\x03':
            raise KeyboardInterrupt
        if self.skip_extended:
            self.skip_extended = False
            return None
        if char in ('\x00', '\xe0'):
            self.skip_extended = True
            return None
        if char == '\n' and self.skip_lf:
            self.skip_lf = False
            return None
        self.skip_lf = char == '\r'
        self.dirty = True
        if char in ('\r', '\n'):
            command, self.text = self.text, ''
            return command
        if char in ('\b', '\x7f'):
            self.text = self.text[:-1]
        elif char == '\x15':
            self.text = ''  # Ctrl+U 清空输入
        elif char.isprintable() and len(self.text) < 240:
            self.text += char
        return None

    def poll(self):
        if not self.active:
            return []
        import msvcrt
        commands = []
        # 限制单次键盘处理，粘贴长文本也不能长时间抢占采集。
        for _ in range(256):
            if not msvcrt.kbhit():
                break
            command = self.feed_key(msvcrt.getwch())
            if command is not None:
                commands.append(command)
        return commands

    def render(self, log, warnings=(), force=False, interval=1.0,
               temp_stale_seconds=5.0, weight_stale_seconds=3.0):
        if not self.active:
            return
        now = time.monotonic()
        if not force and not self.dirty and now - self.last_drawn < interval:
            return
        state = ('空载' if log.manual_load_state == 'unloaded' else
                 f'标称载荷 {log.reference_mass_g} g' if log.manual_load_state == 'loaded'
                 else '载荷未标记')
        seconds = int(now - log.started)
        elapsed = f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
        weight_age = None if log.last_weight_tick is None else now - log.last_weight_tick
        weight = '--' if log.latest_weight is None else log.latest_weight + ' g'
        if weight_age is not None and weight_age >= weight_stale_seconds:
            weight += f'（旧值，{weight_age:.0f}秒前）'
        temp = '--'
        if log.temp is not None:
            temp = log.temp[0] + ' ℃'
            age = log.temp_age_s()
            if log.temp_state != 'ok' or age > temp_stale_seconds:
                temp += f'（旧值，{age:.0f}秒前）'
        status = '需检查：' + '；'.join(warnings) if warnings else '接收正常，持续保存'
        if not log.seq and not warnings:
            status = '等待串口数据，采集器已启动'
        lines = [
            f'电子秤采集正在进行 —— {state}',
            f"{log.metadata['port']}  |  {elapsed}  |  已记录 {log.seq} 行",
            f'重量：{weight}    梁温：{temp}',
            f'状态：{status}',
            f'保存：{log.path}',
            f'最近提示：{self.notice}',
            '500 / 上500：标记总载荷    下 / 0：卸载（空载）',
            's：稳定段  n 文字：备注  t/r：记录去皮/复位  h：帮助  q：结束',
        ]
        width, height = shutil.get_terminal_size((90, 24))
        width = max(8, width - 1)
        # 窗口缩小时保留状态、提示、菜单和输入，避免自动换行刷屏。
        if height < 11:
            lines = [lines[0], lines[3], lines[5], lines[6], lines[7]]
        lines = lines[:max(0, height - 2)]
        lines = [clipped(line, width) for line in lines]
        prompt = '输入 > '
        lines.append(prompt + clipped(self.text, max(1, width - columns(prompt)), tail=True))
        self.stream.write('\x1b[?25l\x1b[H' +
                          '\r\n'.join('\x1b[2K' + line for line in lines) +
                          '\x1b[J\x1b[?25h')
        self.stream.flush()
        self.last_drawn = now
        self.dirty = False
