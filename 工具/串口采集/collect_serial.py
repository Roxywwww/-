"""电子秤串口只读采集：原始字节、时间戳 TXT、事件 CSV 与会话说明。"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / '实验数据' / '原始数据' / '串口采集'
FIELDS = ['seq', 'received_local', 'elapsed_s', 'record_type', 'line_complete',
          'raw', 'net', 'g', 'g_avg', 'temp_c', 'temp_error', 'tare_offset',
          'tare_button_offset', 'display_unit', 'latest_temp_c',
          'latest_temp_received_local', 'latest_temp_seq', 'temp_age_s',
          'temp_state', 'original_line', 'g_iir']
EVENT_FIELDS = ['event_id', 'session_id', 'marked_local', 'elapsed_s',
                'latest_seq', 'event_type', 'reference_mass_g', 'note',
                'source']
KV = re.compile(r'(?:^|\s)([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)')
RAW_MIN = -8388608
RAW_MAX = 8388607
TIMESTAMP_NOTE = '动作由人在电脑输入，电脑标记时刻通常晚于真实动作；分析以原始数据和备注共同判读'

EVENT_ALIASES = {
    'base': 'baseline', 'baseline': 'baseline', '开始基线': 'baseline',
    'cold': 'cold_add', 'cold_add': 'cold_add', '加入冷源': 'cold_add',
    'remove': 'cold_remove', 'cold_remove': 'cold_remove', '移除冷源': 'cold_remove',
    'open': 'cover_open', 'cover_open': 'cover_open', '开盖': 'cover_open',
    'close': 'cover_close', 'cover_close': 'cover_close', '关盖': 'cover_close',
    'load': 'load', '放载荷': 'load',
    'unload': 'unload', '卸载': 'unload',
    'stable': 'stable_start', 'stable_start': 'stable_start', '稳定段开始': 'stable_start',
    'tare': 'tare', '去皮': 'tare',
    'reset': 'reset', '复位': 'reset',
    'touch': 'accidental_touch', 'accidental_touch': 'accidental_touch', '意外碰触': 'accidental_touch',
    'fault': 'abnormal', 'abnormal': 'abnormal', '异常': 'abnormal',
    'note': 'note', '备注': 'note',
}

EVENT_HELP = """可输入的事件命令（输入后可继续采集）：
  c base [备注]            开始基线
  c cold [备注]            加入冷源
  c remove [备注]          移除冷源
  c open/close [备注]      开盖/关盖
  c load 500 [备注]        放置已知标称载荷，单位g
  c unload [备注]          卸载
  c stable [备注]          稳定观察段开始
  c tare/reset [备注]      去皮/复位
  c touch/fault [备注]     意外碰触/异常
  c note [文字]            其他备注
输入 h 再看帮助。中文事件名也可使用，例如“c 加入冷源”。"""


def stamp():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def human_duration(seconds):
    seconds = max(0.0, float(seconds))
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}小时{minutes}分{secs}秒'
    if minutes:
        return f'{minutes}分{secs}秒'
    return f'{seconds:.1f}秒'


def parse_mass(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(value) or value <= 0:
        return ''
    return f'{value:g}'


def parse_event_command(text):
    """把控制台输入转换为可写入 events.csv 的字段。"""
    original = text.strip()
    if not original:
        raise ValueError('事件不能为空')
    if original.lower() in ('h', 'help', '?'):
        return 'help'
    if original.lower().startswith('c '):
        original = original[2:].strip()
    parts = original.split()
    if not parts:
        raise ValueError('事件不能为空')
    token = parts[0].lower()
    event_type = EVENT_ALIASES.get(token) or EVENT_ALIASES.get(parts[0])
    if event_type is None:
        raise ValueError(f'未知事件类别：{parts[0]}')
    rest = parts[1:]
    mass = ''
    if event_type == 'load' and rest:
        mass = parse_mass(rest[0])
        if not mass:
            raise ValueError('load 后的第一个参数应为大于0的标称载荷，例如 c load 500 中心')
        rest = rest[1:]
    return {
        'event_type': event_type,
        'reference_mass_g': mass,
        'note': ' '.join(rest),
    }


def parse_metadata(values):
    result = {}
    reserved = {
        'port', 'baud', 'label', 'note', 'serial_format', 'port_details',
        'duration_limit_s', 'pyserial_version', 'started_local', 'status',
        'timestamp_meaning', 'temperature_alignment', 'decoding',
        'script_sha256', 'records', 'received_bytes', 'updated_local',
        'elapsed_s', 'stopped_local', 'stop_reason', 'session_id',
        'experiment', 'settings', 'summary', 'files',
    }
    for item in values or []:
        if '=' not in item:
            raise argparse.ArgumentTypeError('--meta 必须写成 KEY=VALUE')
        key, value = item.split('=', 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', key):
            raise argparse.ArgumentTypeError(f'--meta 键名不合法：{key!r}')
        if key in reserved:
            raise argparse.ArgumentTypeError(f'--meta 不能覆盖保留字段：{key}')
        if key in result:
            raise argparse.ArgumentTypeError(f'--meta 键重复：{key}')
        result[key] = value
    return result


def start_event_reader():
    """后台读stdin，让串口轮询不受input()阻塞。"""
    events = queue.Queue()

    def worker():
        while True:
            try:
                events.put(input())
            except EOFError:
                events.put(None)
                return

    threading.Thread(target=worker, name='serial-event-reader', daemon=True).start()
    return events


class LineBuffer:
    """串口超时产生的半行先缓存；断开时明确标为不完整，不补造换行。"""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        while True:
            end = self.buffer.find(b'\n')
            if 0 <= end < 8192:
                data = bytes(self.buffer[:end + 1])
                del self.buffer[:end + 1]
                yield data, True
            elif len(self.buffer) >= 8192:
                data = bytes(self.buffer[:8192])
                del self.buffer[:8192]
                yield data, False
            else:
                return

    def finish(self):
        if self.buffer:
            data = bytes(self.buffer)
            self.buffer.clear()
            return data
        return None


class SessionLog:
    def __init__(self, parent, metadata, encoding='utf-8'):
        parent = Path(parent)
        parent.mkdir(parents=True, exist_ok=True)
        self.path = parent / datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S_%f')
        self.path.mkdir()  # 每次独立目录，绝不覆盖旧数据。
        self.encoding = encoding
        self.started = time.monotonic()
        self.seq = 0
        self.byte_count = 0
        self.temp = None
        self.temp_state = 'unknown'
        self.last_line = ''
        self.last_line_tick = None
        self.metadata_write_error = ''
        self.metadata_write_failure_count = 0
        self.metadata_warning_active = False
        self.temp_min = None
        self.temp_max = None
        self.temp_error_started = None
        self.event_count = 0
        self.markers = []
        self.stats = {
            'weight_valid': 0,
            'weight_invalid': 0,
            'temperature_valid': 0,
            'temperature_error': 0,
            'device_error': 0,
            'partial': 0,
            'tare': 0,
            'unit': 0,
            'message': 0,
            'temperature_error_episodes': 0,
            'temperature_error_seconds': 0.0,
            'receive_interval_count': 0,
            'receive_interval_sum_s': 0.0,
            'receive_interval_max_s': 0.0,
        }
        experiment_defaults = {
            'experiment_type': '',
            'assembly_version': '',
            'firmware_version': '',
            'firmware_file': '',
            'firmware_sha256': '',
            'module_ids': '',
            'sensor_ids': '',
            'power_supply': '',
            'probe_position': '',
            'reference_mass': '',
            'thermal_source': '',
            'user_metadata': {},
        }
        experiment_defaults.update(metadata.get('experiment') or {})
        self.metadata = dict(metadata, session_id=self.path.name,
                             experiment=experiment_defaults,
                             started_local=stamp(), status='running',
                             timestamp_meaning='电脑收到整行或不完整片段时的本地时间，含时区；不是ADC采样时刻',
                             temperature_alignment='latest_temp为此前最近有效温度；并非同步采样，年龄与状态单独记录',
                             event_timestamp_meaning=TIMESTAMP_NOTE,
                             decoding=encoding,
                             script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.binary = (self.path / 'received.bin').open('xb')
        self.txt = (self.path / 'serial.txt').open('x', encoding='utf-8', buffering=1)
        self.csvfile = (self.path / 'records.csv').open('x', encoding='utf-8-sig', newline='', buffering=1)
        self.writer = csv.DictWriter(self.csvfile, fieldnames=FIELDS)
        self.writer.writeheader()
        self.eventsfile = (self.path / 'events.csv').open(
            'x', encoding='utf-8-sig', newline='', buffering=1)
        self.event_writer = csv.DictWriter(self.eventsfile, fieldnames=EVENT_FIELDS)
        self.event_writer.writeheader()
        self.event('采集开始；程序不发送串口指令。')
        self.checkpoint()

    def event(self, message):
        self.txt.write(f'[{stamp()}] [采集器] {message}\n')

    def chunk(self, data):
        self.binary.write(data)
        self.byte_count += len(data)

    def record_event(self, event_type, reference_mass_g='', note='', source='console'):
        now = time.monotonic()
        self.event_count += 1
        row = {
            'event_id': self.event_count,
            'session_id': self.path.name,
            'marked_local': stamp(),
            'elapsed_s': f'{now - self.started:.6f}',
            'latest_seq': self.seq,
            'event_type': event_type,
            'reference_mass_g': reference_mass_g,
            'note': note,
            'source': source,
        }
        self.event_writer.writerow(row)
        self.markers.append(dict(row))
        detail = f'事件 {event_type}'
        if reference_mass_g:
            detail += f'，标称载荷={reference_mass_g}g'
        if note:
            detail += f'，备注={note}'
        self.event(f'{detail}；电脑标记时刻，不作为硬件同步时刻。')
        return row

    def _finish_temperature_error(self, now):
        if self.temp_error_started is not None:
            self.stats['temperature_error_seconds'] += max(
                0.0, now - self.temp_error_started)
            self.temp_error_started = None

    def _temperature_ok(self, value_text, received, now):
        value = float(value_text)
        if not math.isfinite(value) or not -55 <= value <= 125:
            raise ValueError('invalid temperature')
        self._finish_temperature_error(now)
        self.temp = (value_text, received, self.seq, now)
        self.temp_state = 'ok'
        if self.temp_min is None or value < self.temp_min:
            self.temp_min = value
        if self.temp_max is None or value > self.temp_max:
            self.temp_max = value
        self.stats['temperature_valid'] += 1

    def _temperature_error(self, now):
        if self.temp_error_started is None:
            self.temp_error_started = now
            self.stats['temperature_error_episodes'] += 1
        self.temp_state = 'error'
        self.stats['temperature_error'] += 1

    def temp_age_s(self):
        if self.temp is None:
            return None
        return max(0.0, time.monotonic() - self.temp[3])

    def health_warnings(self, stale_seconds):
        if self.stats['weight_valid'] == 0:
            return []
        age = self.temp_age_s()
        if self.temp is None:
            reason = '从未收到有效温度'
            if self.stats['temperature_error']:
                reason += f'，已出现{self.stats["temperature_error"]}行温度错误'
            return [f'称重有数据，但{reason}；不能把这类重量视为已带有效温度。']
        if self.temp_state != 'ok':
            return [f'最近一次温度结果异常；旧温度已{age:.1f}秒，不能当作当前梁温。']
        if age > stale_seconds:
            return [f'最近温度已{age:.1f}秒未更新，超过{stale_seconds:g}秒阈值；请检查测温链路。']
        return []

    def health_warning_key(self, stale_seconds):
        if self.stats['weight_valid'] == 0:
            return None
        if self.temp is None:
            return 'missing_temperature'
        if self.temp_state != 'ok':
            return 'temperature_error'
        if self.temp_age_s() > stale_seconds:
            return 'stale_temperature'
        return None

    def line(self, data, complete=True):
        now = time.monotonic()
        received = stamp()
        # 只去串口行结束符；解码异常可在received.bin中复核原始字节。
        payload = data[:-1] if complete and data.endswith(b'\n') else data
        if complete and payload.endswith(b'\r'):
            payload = payload[:-1]
        text = payload.decode(self.encoding, errors='backslashreplace')
        pairs = dict(KV.findall(text)) if complete else {}
        self.seq += 1
        kind = 'message'
        if not complete:
            kind = 'partial'
            self.stats['partial'] += 1
        elif 'temp_error' in pairs:
            self._temperature_error(now)
            kind = 'temperature_error'
        elif 'temp_c' in pairs:
            try:
                self._temperature_ok(pairs['temp_c'], received, now)
                kind = 'temperature'
            except ValueError:
                self._temperature_error(now)
                self.temp_state = 'invalid'
                kind = 'temperature_error'
        elif 'raw' in pairs:
            try:
                raw_value = int(pairs['raw'])
            except (TypeError, ValueError):
                raw_value = None
            if pairs.get('tare') == 'invalid':
                kind = 'weight_tare_invalid'
                self.stats['weight_invalid'] += 1
            elif raw_value is not None and raw_value in (RAW_MIN, RAW_MAX):
                kind = 'weight_saturated'
                self.stats['weight_invalid'] += 1
            elif raw_value is None:
                kind = 'weight_invalid'
                self.stats['weight_invalid'] += 1
            else:
                kind = 'weight'
                self.stats['weight_valid'] += 1
        elif 'tare_offset' in pairs or 'tare_button_offset' in pairs:
            kind = 'tare'
            self.stats['tare'] += 1
        elif 'display_unit' in pairs:
            kind = 'unit'
            self.stats['unit'] += 1
        elif 'timeout' in text.lower():
            kind = 'device_error'
            self.stats['device_error'] += 1
        else:
            self.stats['message'] += 1
        row = {k: pairs[k] for k in FIELDS if k in pairs}
        row.update(seq=self.seq, received_local=received,
                   elapsed_s=f'{now - self.started:.6f}', record_type=kind,
                   line_complete=int(complete), temp_state=self.temp_state,
                   original_line=text)
        if self.temp is not None:
            value, ts, seq, tick = self.temp
            row.update(latest_temp_c=value, latest_temp_received_local=ts,
                       latest_temp_seq=seq, temp_age_s=f'{now - tick:.6f}')
        self.writer.writerow(row)
        suffix = '' if complete else ' [不完整片段]'
        # 控制字符转义只用于阅读版；CSV保留解码文本，BIN保留实际字节。
        display = ''.join(c if c.isprintable() else repr(c)[1:-1] for c in text)
        self.txt.write(f'[{received}] #{self.seq}{suffix} {display}\n')
        self.last_line = display[:160]
        if self.last_line_tick is not None:
            interval = max(0.0, now - self.last_line_tick)
            self.stats['receive_interval_count'] += 1
            self.stats['receive_interval_sum_s'] += interval
            self.stats['receive_interval_max_s'] = max(
                self.stats['receive_interval_max_s'], interval)
        self.last_line_tick = now

    def snapshot(self):
        age = self.temp_age_s()
        mean_interval = None
        if self.stats['receive_interval_count']:
            mean_interval = (
                self.stats['receive_interval_sum_s'] /
                self.stats['receive_interval_count'])
        return {
            'elapsed_s': time.monotonic() - self.started,
            'records': self.seq,
            'bytes': self.byte_count,
            'temperature': self.temp[0] if self.temp is not None else '',
            'temperature_age_s': age,
            'temperature_state': self.temp_state,
            'mean_receive_interval_s': mean_interval,
            'temperature_error': self.stats['temperature_error'],
            'device_error': self.stats['device_error'],
            'weight_valid': self.stats['weight_valid'],
            'weight_invalid': self.stats['weight_invalid'],
            'last_line': self.last_line,
        }

    def status_text(self):
        state = self.snapshot()
        if state['temperature']:
            temp = (f"{state['temperature']}℃（{state['temperature_age_s']:.1f}秒前，"
                    f"{state['temperature_state']}）")
        else:
            temp = f"暂无有效温度（{state['temperature_state']}）"
        interval = state['mean_receive_interval_s']
        interval_text = f'{interval:.3f}秒' if interval is not None else '尚无可计算间隔'
        return (
            f"已保存{human_duration(state['elapsed_s'])} / {state['records']}条 / "
            f"{state['bytes']}字节；有效重量{state['weight_valid']}行、"
            f"无效重量{state['weight_invalid']}行；最近温度{temp}；"
            f"温度错误{state['temperature_error']}行；设备错误{state['device_error']}行；"
            f"平均行间隔{interval_text}\n保存目录：{self.path}")

    def checkpoint(self, durable=False):
        for f in (self.binary, self.txt, self.csvfile, self.eventsfile):
            f.flush()
            if durable:
                os.fsync(f.fileno())
        self.metadata.update(records=self.seq, received_bytes=self.byte_count,
                             updated_local=stamp(),
                             elapsed_s=round(time.monotonic() - self.started, 6),
                             event_count=self.event_count,
                             counters=dict(self.stats),
                             current_temperature_state=self.temp_state,
                             metadata_write_failure_count=self.metadata_write_failure_count,
                             metadata_write_last_error=self.metadata_write_error)
        pending = self.path / 'session.pending'
        try:
            pending.write_text(
                json.dumps(self.metadata, ensure_ascii=False, indent=2),
                encoding='utf-8')
            pending.replace(self.path / 'session.json')
        except OSError as exc:
            # 元数据快照失败不能丢掉仍在正常接收的原始数据。
            # session.pending保留最新JSON，下一次刷新或正常结束时会重新尝试。
            self.metadata_write_failure_count += 1
            self.metadata_write_error = str(exc)
            if not self.metadata_warning_active:
                message = (
                    f'会话元数据暂无法写入，原始串口数据继续采集：{exc}')
                self.event(message)
                print(f'\n警告：{message}')
                self.metadata_warning_active = True
            return False
        if self.metadata_warning_active:
            self.event('会话元数据写入已恢复。')
            self.metadata_warning_active = False
        self.metadata_write_error = ''
        return True

    def build_summary(self):
        duration = time.monotonic() - self.started
        mean_interval = None
        if self.stats['receive_interval_count']:
            mean_interval = (
                self.stats['receive_interval_sum_s'] /
                self.stats['receive_interval_count'])
        interruption_events = sum(
            marker['event_type'] == 'data_gap' for marker in self.markers)
        reset_events = sum(
            marker['event_type'] == 'reset' for marker in self.markers)
        return {
            'session_id': self.path.name,
            'started_local': self.metadata.get('started_local'),
            'stopped_local': stamp(),
            'duration_s': round(duration, 6),
            'records': self.seq,
            'received_bytes': self.byte_count,
            'weight_valid_rows': self.stats['weight_valid'],
            'weight_invalid_rows': self.stats['weight_invalid'],
            'temperature_valid_rows': self.stats['temperature_valid'],
            'temperature_min_c': self.temp_min,
            'temperature_max_c': self.temp_max,
            'temperature_error_rows': self.stats['temperature_error'],
            'temperature_error_episodes': self.stats['temperature_error_episodes'],
            'temperature_error_seconds': round(
                self.stats['temperature_error_seconds'], 6),
            'device_error_rows': self.stats['device_error'],
            'partial_rows': self.stats['partial'],
            'tare_rows': self.stats['tare'],
            'unit_rows': self.stats['unit'],
            'mean_receive_interval_s': (
                None if mean_interval is None else round(mean_interval, 6)),
            'max_receive_interval_s': round(
                self.stats['receive_interval_max_s'], 6),
            'data_gap_events': interruption_events,
            'reset_markers': reset_events,
            'event_count': self.event_count,
            'latest_temperature_c': (
                self.temp[0] if self.temp is not None else None),
            'latest_temperature_state': self.temp_state,
            'effective_temperature_window_note': (
                '最小值/最大值来自本次有效temp_c行，不代表温度已稳定，'
                '也不把错误段计入。'),
            'timestamp_note': TIMESTAMP_NOTE,
            'files': [
                'serial.txt', 'records.csv', 'received.bin', 'events.csv',
                'session.json', 'summary.json', 'summary.md',
            ],
            'next_analysis': (
                '先检查summary.json、events.csv和serial.txt，再按事件区间'
                '划分records.csv；不得把异常段或旧温度当成当前有效样本。'),
        }

    def summary_markdown(self, summary):
        temp_range = '无有效温度'
        if summary['temperature_min_c'] is not None:
            temp_range = (
                f"{summary['temperature_min_c']:.2f}～"
                f"{summary['temperature_max_c']:.2f}℃")
        mean_interval = summary['mean_receive_interval_s']
        interval_text = '无' if mean_interval is None else f'{mean_interval:.3f}秒'
        return '\n'.join([
            f"# 采集结束摘要：{summary['session_id']}",
            '',
            f"- 结束状态：{self.metadata.get('status', '')}",
            f"- 结束原因：{self.metadata.get('stop_reason', '')}",
            f"- 起止：{summary['started_local']} 至 {summary['stopped_local']}",
            f"- 总时长：{human_duration(summary['duration_s'])}",
            f"- 记录数/原始字节：{summary['records']} / {summary['received_bytes']}",
            f"- 有效/无效重量行：{summary['weight_valid_rows']} / {summary['weight_invalid_rows']}",
            f"- 有效温度行：{summary['temperature_valid_rows']}",
            f"- 有效温度最小值～最大值：{temp_range}",
            f"- 温度错误：{summary['temperature_error_rows']}行，"
            f"{summary['temperature_error_episodes']}段，"
            f"{summary['temperature_error_seconds']:.3f}秒",
            f"- 设备错误/残片：{summary['device_error_rows']} / {summary['partial_rows']}行",
            f"- 数据中断标记：{summary['data_gap_events']}次",
            f"- 平均/最大行接收间隔：{interval_text} / "
            f"{summary['max_receive_interval_s']:.3f}秒",
            f"- 事件标记：{summary['event_count']}条",
            '',
            '## 使用边界',
            '',
            summary['effective_temperature_window_note'],
            '',
            TIMESTAMP_NOTE + '。',
            '',
            '## 下一步',
            '',
            summary['next_analysis'],
            '',
        ])

    def close(self, status, reason):
        self.metadata.update(status=status, stopped_local=stamp(), stop_reason=reason)
        self.event(f'采集结束：{reason}；共{self.seq}条，{self.byte_count}字节。')
        try:
            self._finish_temperature_error(time.monotonic())
            self.metadata.update(status=status, stopped_local=stamp(), stop_reason=reason)
            summary = self.build_summary()
            self.metadata['summary'] = summary
            (self.path / 'summary.json').write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            (self.path / 'summary.md').write_text(
                self.summary_markdown(summary), encoding='utf-8')
            self.checkpoint(durable=True)
            self.summary_data = summary
        finally:
            for f in (self.binary, self.txt, self.csvfile, self.eventsfile):
                f.close()


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('必须是大于0的有限数值')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', help='例如 COM3；省略则列出端口供选择')
    p.add_argument('--list', action='store_true', help='只列出端口，不打开')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    p.add_argument('--encoding', default='utf-8', choices=['utf-8', 'gbk', 'ascii'])
    duration = p.add_mutually_exclusive_group()
    duration.add_argument('--hours', type=positive, help='采集指定小时后停止')
    duration.add_argument('--seconds', type=positive, help='采集指定秒数后停止')
    p.add_argument('--label', default='', help='如空载、500g或升温试验')
    p.add_argument('--note', default='', help='供电、接线及试验条件备注')
    p.add_argument('--experiment-type', default='', help='实验类型；未填则保存为空')
    p.add_argument('--assembly-version', default='', help='实际板版号/装配版本；未填则保存为空')
    p.add_argument('--firmware-version', default='', help='实际固件版本；未填则保存为空')
    p.add_argument('--firmware-file', type=Path, help='可选：记录该固件文件路径与SHA-256')
    p.add_argument('--module-id', default='', help='HX711等模块的实物编号；未填则保存为空')
    p.add_argument('--sensor-id', default='', help='温度传感器实物编号；未填则保存为空')
    p.add_argument('--probe-position', default='', help='探头固定位置；未填则保存为空')
    p.add_argument('--power-supply', default='', help='实测供电条件；未填则保存为空')
    p.add_argument('--reference-mass', default='', help='参考载荷及依据；未填则保存为空')
    p.add_argument('--thermal-source', default='', help='冷热源及布置；未填则保存为空')
    p.add_argument('--meta', action='append', default=[], metavar='KEY=VALUE',
                   help='附加场次信息，可重复；不能覆盖保留字段')
    p.add_argument('--temp-stale-seconds', type=positive, default=5.0,
                   help='温度年龄提示阈值，默认5秒')
    p.add_argument('--data-stale-seconds', type=positive, default=30.0,
                   help='无新串口数据提示阈值，默认30秒')
    p.add_argument('--status-seconds', type=positive, default=5.0,
                   help='状态刷新间隔，默认5秒')
    p.add_argument('--no-events', action='store_true',
                   help='禁用控制台事件输入；文件记录仍照常运行')
    args = p.parse_args(argv)
    if args.baud <= 0:
        p.error('波特率必须大于0')
    try:
        user_metadata = parse_metadata(args.meta)
    except argparse.ArgumentTypeError as exc:
        p.error(str(exc))
    firmware_file = ''
    firmware_sha256 = ''
    if args.firmware_file is not None:
        try:
            firmware_file = str(args.firmware_file.resolve())
            firmware_sha256 = hashlib.sha256(args.firmware_file.read_bytes()).hexdigest()
        except OSError as exc:
            p.error(f'无法读取 --firmware-file：{exc}')
    experiment = {
        'experiment_type': args.experiment_type,
        'assembly_version': args.assembly_version,
        'firmware_version': args.firmware_version,
        'firmware_file': firmware_file,
        'firmware_sha256': firmware_sha256,
        'module_ids': args.module_id,
        'sensor_ids': args.sensor_id,
        'power_supply': args.power_supply,
        'probe_position': args.probe_position,
        'reference_mass': args.reference_mass,
        'thermal_source': args.thermal_source,
        'user_metadata': user_metadata,
    }
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print('缺少pyserial，请先运行：python -m pip install pyserial==3.5', file=sys.stderr)
        return 2
    ports = sorted(list_ports.comports())
    if args.list or not args.port:
        print('可用串口：')
        for n, port in enumerate(ports, 1):
            print(f'  {n}. {port.device}  {port.description}')
        if args.list:
            return 0
        if not ports:
            print('未找到串口，请插入USB转串口模块并检查驱动。')
            return 2
        try:
            selection = int(input('输入要采集的序号（不会自动选端口）：').strip())
            if not 1 <= selection <= len(ports):
                raise ValueError()
            args.port = ports[selection - 1].device
        except (ValueError, EOFError, KeyboardInterrupt):
            print('\n已取消，未打开串口。')
            return 2
    # 正式采集仅允许实际端口，防止把loop://等测试数据混入实验。
    if '://' in args.port:
        p.error('请选择实际串口，例如COM3')
    device = None
    log = None
    buffer = LineBuffer()
    status, reason, code = 'completed', '到达设定时长', 0
    limit = args.seconds or (args.hours * 3600 if args.hours else None)
    try:
        device = serial.Serial(port=None, baudrate=args.baud, bytesize=8, parity='N',
                               stopbits=1, timeout=0.5, xonxoff=False, rtscts=False, dsrdtr=False)
        device.dtr = False
        device.rts = False
        device.port = args.port
        device.open()
        details = next(({'description': x.description, 'hwid': x.hwid,
                         'serial_number': x.serial_number} for x in ports
                        if x.device.lower() == args.port.lower()), {})
        log = SessionLog(args.output, dict(port=args.port, baud=args.baud, serial_format='8N1',
                         label=args.label, note=args.note, port_details=details,
                         duration_limit_s=limit, pyserial_version=serial.__version__,
                         experiment=experiment,
                         settings={
                             'temperature_stale_seconds': args.temp_stale_seconds,
                             'data_stale_seconds': args.data_stale_seconds,
                             'status_seconds': args.status_seconds,
                             'console_events_enabled': (
                                 not args.no_events and sys.stdin.isatty()),
                         }))
        print(f'正在采集 {args.port}，{args.baud} 8N1。\n保存位置：{log.path}\n按Ctrl+C停止；请保持电脑不休眠。')
        event_queue = None
        if not args.no_events and sys.stdin.isatty():
            print(EVENT_HELP)
            event_queue = start_event_reader()
        else:
            print('控制台事件输入不可用或已禁用；串口采集仍正常进行。')
        active_health_warning = None

        def consume_events():
            nonlocal active_health_warning
            if event_queue is None:
                return
            while True:
                try:
                    line = event_queue.get_nowait()
                except queue.Empty:
                    return
                if line is None:
                    return
                if not line.strip():
                    continue
                try:
                    parsed = parse_event_command(line)
                except ValueError as exc:
                    print(f'事件未记录：{exc}。输入 h 查看格式。')
                    continue
                if parsed == 'help':
                    print(EVENT_HELP)
                    continue
                marker = log.record_event(parsed['event_type'],
                                          parsed['reference_mass_g'],
                                          parsed['note'], source='console')
                print(f"已标记 {marker['event_type']}；事件号{marker['event_id']}，"
                      f"当时最近串口seq={marker['latest_seq']}。")

        deadline = time.monotonic() + limit if limit else None
        saved, shown, last_received = time.monotonic(), time.monotonic(), time.monotonic()
        warned = False
        gap_started = None
        while deadline is None or time.monotonic() < deadline:
            consume_events()
            # 先等待1字节，再读当前已到达的字节，避免固定大块读取造成长延迟。
            chunk = device.read(1)
            if chunk:
                if warned:
                    note = (f'无数据提示结束后收到数据；'
                            f'中断约{time.monotonic() - gap_started:.3f}秒')
                    log.record_event('data_resumed', note=note, source='capture')
                log.chunk(chunk)
                for data, complete in buffer.feed(chunk):
                    log.line(data, complete)
                # 每一次成功read立即保存；下一次read断线也不丢前一个字节。
                available = min(device.in_waiting, 4095)
                if available:
                    chunk = device.read(available)
                    log.chunk(chunk)
                    for data, complete in buffer.feed(chunk):
                        log.line(data, complete)
                last_received = time.monotonic()
                warned = False
                gap_started = None
                consume_events()
            now = time.monotonic()
            if now - last_received >= args.data_stale_seconds and not warned:
                message = (
                    f'连续{args.data_stale_seconds:g}秒未收到数据，'
                    '请检查接线、供电和端口；仍在等待。')
                log.event(message)
                log.record_event(
                    'data_gap',
                    note=f'连续{args.data_stale_seconds:g}秒未收到任何字节',
                    source='capture')
                print(message)
                warned = True
                gap_started = last_received
            if now - saved >= 1:
                log.checkpoint(durable=True)
                saved = now
            if now - shown >= args.status_seconds:
                print(log.status_text())
                warnings = log.health_warnings(args.temp_stale_seconds)
                warning_key = log.health_warning_key(args.temp_stale_seconds)
                if warning_key and warning_key != active_health_warning:
                    for warning in warnings:
                        print(f'健康提示：{warning}')
                    log.record_event(
                        'temperature_stale', note='；'.join(warnings),
                        source='capture')
                    active_health_warning = warning_key
                elif not warning_key and active_health_warning is not None:
                    log.record_event(
                        'temperature_resumed',
                        note='称重已有有效且新鲜的温度配对', source='capture')
                    active_health_warning = None
                shown = now
    except KeyboardInterrupt:
        status, reason = 'stopped', '用户按Ctrl+C停止'
    except (serial.SerialException, OSError) as exc:
        status, reason, code = 'error', f'串口或文件异常：{exc}', 1
        print(f'{reason}\n若端口被占用，请关闭串口助手的端口后重试；已有文件会保留。', file=sys.stderr)
    finally:
        try:
            if log is not None:
                tail = buffer.finish()
                if tail is not None:
                    log.line(tail, complete=False)
                log.close(status, reason)
                summary = log.summary_data
                temp_range = '无有效温度'
                if summary['temperature_min_c'] is not None:
                    temp_range = (
                        f"{summary['temperature_min_c']:.2f}～"
                        f"{summary['temperature_max_c']:.2f}℃")
                print(
                    f'\n采集结束，文件保存在：{log.path}\n'
                    f"总时长{human_duration(summary['duration_s'])}；"
                    f"有效重量{summary['weight_valid_rows']}行，"
                    f"有效温度{summary['temperature_valid_rows']}行（{temp_range}）；"
                    f"温度错误{summary['temperature_error_rows']}行；"
                    f"数据中断标记{summary['data_gap_events']}次。\n"
                    f"结束摘要：{log.path / 'summary.md'}\n"
                    f"结构化摘要：{log.path / 'summary.json'}\n"
                    f"事件标记：{log.path / 'events.csv'}")
        finally:
            if device is not None:
                device.close()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
