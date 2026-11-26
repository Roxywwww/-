"""Read-only audit and scientific plots of every original temperature serial run.

Run with the bundled Python runtime. Matplotlib may be supplied with --plot-deps.
Raw sources are hashed before/after and are never rewritten. Outputs are derived
CSV/JSON tables, PNG figures and a local HTML report, not an edited manuscript.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics
import sys
from collections import Counter, defaultdict

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / '实验数据/原始数据'
PAIR_AGE = 2.0
OLD_K, NEW_K = 177.6184, 178.20
CHANGE_K = datetime(2026, 11, 13, 14, 34, 42, 987000, tzinfo=TZ)
ASSEMBLY_CHANGE = datetime(2026, 11, 20, 13, 28, 1, 531000, tzinfo=TZ)

# These are annotations of existing records, not inferred experimental results.
# Times for manually reconstructed actions are tied to the cited stage records.
CONTEXT = {
 '2026-10-18_DS18B20': ('温度驱动初测', 0, '功能验证', '2026-10-18_DS18B20单总线温度读取开发与验证记录.md'),
 '2026-11-12_13-11-49_098586': ('断线重连检查', None, '连接检查', ''),
 '2026-11-12_13-13-10_084101': ('室温空载10分钟', 0, '室温空载', '2026-11-12_桌面空载连接检查与稳定性测试记录.md'),
 '2026-11-12_13-23-34_053313': ('室温空载接续', 0, '室温空载', '2026-11-12_桌面空载连接检查与稳定性测试记录.md'),
 '2026-11-12_13-31-07_051218': ('确认开始前试录', 0, '试录', '2026-11-12_空载冰杯预实验_常温起录.md'),
 '2026-11-12_13-38-07_988301': ('放冰前室温空载', 0, '室温空载', '2026-11-12_空载冰杯预实验_确认开始.md'),
 '2026-11-12_13-56-43_455079': ('冰杯空载降温', 0, '降温预实验', '2026-11-12_空载冰杯预实验_确认开始.md'),
 '2026-11-12_15-54-05_320998': ('缺口后低温抽检', 0, '功能验证', '2026-11-12_空载冰杯预实验_确认开始.md'),
 '2026-11-12_15-54-43_101987': ('移杯后部分回温', 0, '机械扰动回温', '2026-11-12_空载冰杯预实验_确认开始.md'),
 '2026-11-13_13-35-29_690685': ('500g降温与回温', 500, '混合载荷预实验', '2026-11-13_500g双冰袋降温记录.md'),
 '2026-11-13_14-24-25_963270': ('去皮固件空载检查', 0, '功能验证', '2026-11-13_开机去皮与零点显示优化验证.md'),
 '2026-11-13_14-27-10_136669': ('标定与100g验证', 0, '混合载荷标定', '2026-11-13_新版桌面标定复核.md'),
 '2026-11-16_15-19-37_540060': ('IIR短时空载验证', 0, '功能验证', '2026-11-16_IIR滤波离线对照与采集接口.md'),
 '2026-11-16_15-22-34_441048': ('吹风加热与200g', 0, '加热动态预实验', '2026-11-16_升温实验与室温基线.md'),
 '2026-11-20_13-25-14_773133': ('约21℃载荷复核', None, '载荷对照', '2026-11-20_去膜后标定与资料整理.md'),
 '2026-11-21_14-55-40_499922': ('约25℃载荷复核', None, '载荷对照', '2026-11-21_约25度同序载荷对照.md'),
 '2026-11-21_15-11-23_513038': ('近两小时自然降温', 0, '连续降温对照', '2026-11-21_约25度同序载荷对照.md'),
 '2026-11-21_17-44-25_738006': ('下载连接检查1', 0, '下载连接检查', '2026-11-21_约25度同序载荷对照.md'),
 '2026-11-21_17-47-03_059749': ('下载连接检查2', 0, '下载连接检查', '2026-11-21_约25度同序载荷对照.md'),
 '2026-11-24_14-21-58_420975': ('未另确认的静置观察', None, '未确认载荷', '2026-11-24_室内静置零点观察.md'),
 '2026-11-24_18-20-26_028147': ('手动去皮后空载', 0, '室温空载', '2026-11-24_开机后手动去皮静置观察.md'),
}

MANUAL_MARKERS = {
 '2026-11-13_13-35-29_690685': [
  ('13:56:38.701', 0), ('14:03:00', None), ('14:05:32', 0),
  ('14:06:02.408', 500), ('14:08:50.064', 0),
  # Later loads are only bounded where the stage record confirms empty again.
  ('14:15:05', None), ('14:20:00', 0)],
 '2026-11-13_14-27-10_136669': [
  ('14:27:43.150', 200), ('14:29:00', 0), ('14:29:36', None),
  ('14:30:06.673', 0), ('14:31:07.211', 500), ('14:31:56.515', 0),
  ('14:32:09.824', 200), ('14:33:17', 100), ('14:34:35', None),
  ('14:34:42.987', 0), ('14:35:10.286', 500), ('14:36:56.673', 0),
  ('14:38:32.987', 100), ('14:39:23.222', 0)],
 '2026-11-24_18-20-26_028147': [('18:21:26', 100), ('18:21:34', 0)],
}


def dt(value):
    result = datetime.fromisoformat(str(value))
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def write_csv(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        if keys:
            writer = csv.DictWriter(file, keys)
            writer.writeheader()
            writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit_line(x, y):
    if len(x) < 3 or len(x) != len(y):
        return None
    xm, ym = statistics.mean(x), statistics.mean(y)
    denominator = sum((a-xm)**2 for a in x)
    total = sum((b-ym)**2 for b in y)
    if denominator <= 1e-12 or total <= 1e-12:
        return None
    slope = sum((a-xm)*(b-ym) for a, b in zip(x, y)) / denominator
    intercept = ym-slope*xm
    sse = sum((b-intercept-slope*a)**2 for a, b in zip(x, y))
    return dict(n=len(x), slope=slope, intercept=intercept,
                r_squared=1-sse/total, residual_rmse=math.sqrt(sse/len(x)))


def stats(rows):
    result = {'n': len(rows)}
    if not rows:
        return result
    result.update(start=rows[0]['datetime'].isoformat(), end=rows[-1]['datetime'].isoformat(),
                  coverage_s=rows[-1]['elapsed_s']-rows[0]['elapsed_s'])
    for key in ('raw', 'net', 'g_avg', 'g_iir', 'net_mass_g', 'paired_temp_c'):
        values = [row[key] for row in rows if row.get(key) is not None]
        if values:
            result.update({key+'_mean': statistics.mean(values),
                           key+'_sd': statistics.stdev(values) if len(values)>1 else 0.0,
                           key+'_min': min(values), key+'_max': max(values)})
    result['center_s'] = statistics.mean(row['elapsed_s'] for row in rows)
    return result


def discover():
    specs = []
    for folder in sorted((RAW/'串口采集').iterdir()):
        if folder.is_dir() and (folder/'records.csv').exists():
            metadata = json.loads((folder/'session.json').read_text(encoding='utf-8-sig'))
            specs.append(dict(id=folder.name, folder=folder, csv=folder/'records.csv',
                              metadata=metadata, legacy=False))
    # Scan every loose raw CSV/TXT. Only CSVs with actual temperature tokens are
    # independent additional data, not serial.txt/received.bin copies of runs.
    flat_inventory = []
    for path in sorted(RAW.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        has_temp = bool(re.search(r'temp_c\s*=', text))
        flat_inventory.append(dict(file=path.relative_to(ROOT).as_posix(),
                                   has_temperature=has_temp, sha256=digest(path),
                                   bytes=path.stat().st_size))
        if has_temp and path.suffix.lower() == '.csv':
            sid = '2026-10-18_DS18B20' if path.name.startswith('2026-10-18') else path.stem
            specs.append(dict(id=sid, folder=path.parent, csv=path,
                              metadata={'label': '温度驱动初测', 'status': 'legacy_csv'}, legacy=True))
    return sorted(specs, key=lambda item: item['id']), flat_inventory


def parse_session(spec):
    inputs = read_csv(spec['csv'])
    metadata = spec['metadata']
    context = CONTEXT.get(spec['id'], (metadata.get('label') or spec['id'], None, '未分类', ''))
    events = read_csv(spec['folder']/'events.csv') if not spec['legacy'] and (spec['folder']/'events.csv').exists() else []
    rows = []
    for index, item in enumerate(inputs, 2):
        text = item.get('line', item.get('original_line', ''))
        fields = dict(re.findall(r'([a-z_]+)=([^\s]+)', text))
        fields.update({key: value for key, value in item.items() if value not in ('', None)})
        try:
            timestamp = dt(item['received_local'])
        except (KeyError, ValueError):
            continue
        kind = item.get('record_type')
        if not kind:
            kind = ('temperature_error' if 'temp_error' in fields else
                    'temperature' if 'temp_c' in fields else
                    'weight' if 'raw' in fields else
                    'tare' if 'tare_offset' in fields or 'tare_button_offset' in fields else 'message')
        row = dict(session=spec['id'], source_row=index, seq=item.get('seq') or index-1,
                   datetime=timestamp, kind=kind, original_line=text,
                   complete=item.get('line_complete', '1') == '1',
                   recorded_elapsed_s=number(item.get('elapsed_s')))
        for key in ('raw', 'net', 'g', 'g_avg', 'g_iir', 'temp_c'):
            row[key] = number(fields.get(key))
        row['reported_temp_state'] = item.get('temp_state', '')
        row['reported_temp_age_s'] = number(item.get('temp_age_s'))
        rows.append(row)
    if not rows:
        spec.update(context=context, rows=[], weights=[], temps=[], events=events,
                    minutes=[], fits=[], gaps=[], epochs=[], phases=[], t0=None)
        return spec
    t0 = dt(metadata['started_local']) if metadata.get('started_local') else rows[0]['datetime']
    last_temp = None
    last_base = None
    pending_break = False
    epoch = 0
    weights, temps, epochs, gaps = [], [], [], []
    previous = None
    for row in rows:
        row['elapsed_s'] = (row['recorded_elapsed_s'] if row['recorded_elapsed_s'] is not None
                            else (row['datetime']-t0).total_seconds())
        row['coeff_counts_per_g'] = NEW_K if row['datetime'] >= CHANGE_K else OLD_K
        row['assembly'] = '去膜后20kg装配' if row['datetime'] >= ASSEMBLY_CHANGE else '历史20kg装配'
        row['paired_temp_c'] = None
        row['temp_age_s'] = None
        row['paired_temp_source_row'] = None
        row['paired_temp_received_local'] = None
        if previous and row['elapsed_s']-previous['elapsed_s'] > 2:
            gaps.append(dict(session=spec['id'], start=previous['datetime'].isoformat(),
                             end=row['datetime'].isoformat(), seconds=row['elapsed_s']-previous['elapsed_s']))
        previous = row
        if row['kind'] == 'temperature_error':
            last_temp = None
        if 'USART1 OK' in row['original_line'] or row['kind'] == 'tare':
            pending_break = True
            if 'USART1 OK' in row['original_line']:
                last_temp = None
        if row['kind'] == 'temperature' and row['complete'] and row['temp_c'] is not None:
            row['temp_physical_range_ok'] = -55 <= row['temp_c'] <= 125
            row['temp_85_flag'] = row['temp_c'] == 85.0
            if row['temp_physical_range_ok'] and not row['temp_85_flag']:
                temps.append(row)
                last_temp = row
            else:
                last_temp = None
        if row['raw'] is None:
            continue
        row['valid_weight'] = (row['complete'] and row['kind'] == 'weight' and
                               -8388608 < row['raw'] < 8388607 and row['net'] is not None)
        if not row['valid_weight']:
            continue
        base = int(row['raw']-row['net'])
        if last_base is None or base != last_base or pending_break:
            if last_base is not None:
                epoch += 1
            epochs.append(dict(session=spec['id'], epoch=epoch, time=row['datetime'].isoformat(),
                               tare_base=base, reason='首个基准' if last_base is None else
                               '去皮/启动/基准变化', previous_base=last_base))
        row['epoch'] = epoch
        row['tare_base'] = base
        last_base, pending_break = base, False
        if last_temp:
            age = (row['datetime']-last_temp['datetime']).total_seconds()
            row['temp_age_s'] = age
            if 0 <= age <= PAIR_AGE:
                row['paired_temp_c'] = last_temp['temp_c']
                row['paired_temp_source_row'] = last_temp['source_row']
                row['paired_temp_received_local'] = last_temp['datetime'].isoformat()
        # Respect explicit recorder fault states even if a preceding cached
        # temperature token could otherwise be found within the age threshold.
        if row['reported_temp_state'] and row['reported_temp_state'] != 'ok':
            row['paired_temp_c'] = None
        row['net_mass_g'] = row['net']/row['coeff_counts_per_g']
        weights.append(row)
    spec.update(context=context, rows=rows, weights=weights, temps=temps, events=events,
                gaps=gaps, epochs=epochs, t0=t0)
    annotate_phases(spec)
    return spec


def annotate_phases(session):
    weights = session['weights']
    if not weights:
        session.update(phases=[], minutes=[], fits=[])
        return
    sid, t0 = session['id'], session['t0']
    end = weights[-1]['elapsed_s']
    markers = [dict(time=0.0, mass=session['context'][1], origin='阶段记录/会话标签', marked=None)]
    bad_markers = []
    previous_marked = 0.0
    for event in session['events']:
        if event.get('event_type') not in ('load', 'unload'):
            continue
        mass = 0.0 if event['event_type'] == 'unload' else number(event.get('reference_mass_g'))
        if mass is None or not 0 <= mass <= 500:
            bad_markers.append(event)
            continue
        marked = (dt(event['marked_local'])-t0).total_seconds()
        detected = marked
        # Locate only a declared action with a broad mass band and 10 samples.
        # This does not identify unknown loads or select for small weight error.
        if mass != markers[-1]['mass'] and markers[-1]['mass'] is not None:
            candidates = []
            for row in weights:
                if not max(previous_marked+5, marked-120) <= row['elapsed_s'] <= marked+10:
                    continue
                if row['g'] is not None and abs(row['g']-mass) <= max(5, mass*.05):
                    candidates.append(row['elapsed_s'])
                    if len(candidates) == 10:
                        detected = candidates[0]
                        break
                else:
                    candidates = []
        markers.append(dict(time=detected, mass=mass, origin='载荷事件与宽阈值定位', marked=marked))
        previous_marked = marked
    for clock, mass in MANUAL_MARKERS.get(sid, []):
        timestamp = dt(t0.date().isoformat()+'T'+clock)
        markers.append(dict(time=(timestamp-t0).total_seconds(), mass=mass,
                            origin='阶段记录确认/原始跃变', marked=None))
    markers.sort(key=lambda item: item['time'])
    phases = []
    for index, marker in enumerate(markers):
        high = markers[index+1]['time'] if index+1 < len(markers) else end+.001
        if high <= marker['time']:
            continue
        phases.append(dict(session=sid, phase=len(phases), low=marker['time'], high=high,
                           mass=marker['mass'], origin=marker['origin'],
                           marked_s=marker['marked']))
    for row in weights:
        phase = next((p for p in reversed(phases) if p['low'] <= row['elapsed_s'] < p['high']), None)
        row['phase'] = phase['phase'] if phase else -1
        row['reference_mass_g'] = phase['mass'] if phase else None
        row['transition'] = (phase is None or row['elapsed_s'] < phase['low']+10 or
                             row['elapsed_s'] > phase['high']-3)
        row['unexpected_load'] = (row['reference_mass_g'] is not None and
                                  abs(row['net_mass_g']-row['reference_mass_g']) > 20)
        row['special_condition'] = ''
        if sid == '2026-11-13_13-35-29_690685' and row['datetime'].time().isoformat() >= '14:03:00':
            row['special_condition'] = '取杯/探头脱落重贴后'
        elif sid == '2026-11-12_15-54-43_101987':
            row['special_condition'] = '移杯晃袋后的回温'
        elif sid == '2026-11-16_15-22-34_441048' and row['elapsed_s'] >= 300:
            row['special_condition'] = '吹风加热及停吹回落'
        elif sid == '2026-11-24_14-21-58_420975' and row['elapsed_s'] >= end-15:
            row['special_condition'] = '拔线前末尾变化，操作关联待判'
        row['confirmed_empty'] = (row['reference_mass_g'] == 0 and not row['transition'] and
                                   not row['unexpected_load'] and row['paired_temp_c'] is not None)
    minutes = []
    groups = defaultdict(list)
    for row in weights:
        if row['confirmed_empty']:
            groups[(row['epoch'], row['phase'], int(row['elapsed_s']//60))].append(row)
    for (epoch, phase, minute), group in sorted(groups.items()):
        if len(group) >= 180 and group[-1]['elapsed_s']-group[0]['elapsed_s'] >= 45:
            item = dict(session=sid, epoch=epoch, phase=phase, minute=minute, **stats(group))
            item['special_condition'] = ';'.join(sorted({r['special_condition'] for r in group if r['special_condition']}))
            item['assembly'] = group[0]['assembly']
            minutes.append(item)
    fits = []
    for epoch in sorted({m['epoch'] for m in minutes}):
        group = [m for m in minutes if m['epoch'] == epoch and not m['special_condition']]
        if len(group) < 5:
            continue
        temperatures = [m['paired_temp_c_mean'] for m in group]
        masses = [m['net_mass_g_mean'] for m in group]
        span = max(temperatures)-min(temperatures)
        model = fit_line(temperatures, masses) if span >= .5 else None
        time_model = fit_line([m['center_s']/3600 for m in group], masses)
        fits.append(dict(session=sid, epoch=epoch, minute_count=len(group), temp_span_c=span,
                         temperature_model=model, time_model=time_model,
                         fit_status='仅描述性拟合' if model else '温差不足0.5℃，不估算温漂斜率'))
    session.update(phases=phases, minutes=minutes, fits=fits, bad_markers=bad_markers)


def session_summary(session):
    rows, weights, temps = session['rows'], session['weights'], session['temps']
    kinds = Counter(r['kind'] for r in rows)
    tvalues = [r['temp_c'] for r in temps]
    empty = [r for r in weights if r.get('confirmed_empty') and not r['special_condition']]
    paired = [r for r in weights if r['paired_temp_c'] is not None]
    return dict(session=session['id'], purpose=session['context'][0], category=session['context'][2],
                source=session['csv'].relative_to(ROOT).as_posix(),
                original_status=session['metadata'].get('status', ''),
                first_time=rows[0]['datetime'].isoformat() if rows else '',
                last_time=rows[-1]['datetime'].isoformat() if rows else '',
                duration_s=rows[-1]['elapsed_s'] if rows else 0,
                source_record_count=len(rows), valid_weights=len(weights),
                valid_temperatures=len(temps), paired_weights=len(paired),
                confirmed_empty_weights=len(empty), temperature_errors=kinds['temperature_error'],
                weight_errors=sum(kinds[k] for k in ('weight_invalid', 'weight_saturated', 'weight_tare_invalid')),
                device_errors=kinds['device_error'], partial_rows=kinds['partial'],
                temp_min_c=min(tvalues) if tvalues else None,
                temp_max_c=max(tvalues) if tvalues else None,
                temp_span_c=max(tvalues)-min(tvalues) if tvalues else None,
                tare_events=kinds['tare'], tare_base_count=len({r['tare_base'] for r in weights}),
                gaps_over_2s=len(session['gaps']),
                max_gap_s=max((g['seconds'] for g in session['gaps']), default=0),
                unexpected_load_rows=sum(r.get('unexpected_load', False) for r in weights),
                note=session['metadata'].get('note', ''),
                stage_reference=session['context'][3],
                **({'empty_mean_g': statistics.mean(r['g_avg'] for r in empty if r['g_avg'] is not None),
                    'empty_sd_g': statistics.stdev(r['g_avg'] for r in empty if r['g_avg'] is not None) if len(empty)>1 else 0}
                   if empty else {}))


def historical_compensation(sessions):
    lookup = {s['id']: s for s in sessions}
    train = lookup['2026-11-12_13-56-43_455079']
    test = lookup['2026-11-13_13-35-29_690685']
    groups = defaultdict(list)
    for row in train['weights']:
        if row['paired_temp_c'] is not None:
            groups[int(row['elapsed_s']//60)].append(row)
    windows = [group for group in groups.values() if len(group) >= 180]
    x = [statistics.mean(r['paired_temp_c'] for r in g) for g in windows]
    y = [statistics.mean(r['raw']/OLD_K for r in g) for g in windows]
    model = fit_line(x, y)
    reference = [r for r in test['weights'] if dt('2026-11-13T13:36:30') <= r['datetime'] < dt('2026-11-13T13:37:30') and r['paired_temp_c'] is not None]
    t0 = statistics.mean(r['paired_temp_c'] for r in reference)
    selected = [r for r in test['weights'] if dt('2026-11-13T13:43:00') <= r['datetime'] < dt('2026-11-13T13:56:35') and r['paired_temp_c'] is not None and 21.37 <= r['paired_temp_c'] <= 26.18]
    points = []
    for row in selected:
        before = row['net']/OLD_K-500
        after = before-model['slope']*(row['paired_temp_c']-t0)
        points.append(dict(time=row['datetime'].isoformat(), temp_c=row['paired_temp_c'],
                           before_error_g=before, after_error_g=after))
    result = dict(training_session=train['id'], test_session=test['id'], reference_temp_c=t0,
                  training_minute_windows=len(windows), model=model, validation_rows=len(points),
                  warning='跨日500g迁移预实验；完整保留改善或恶化结果，不启用固件补偿')
    for label in ('before', 'after'):
        errors = [p[label+'_error_g'] for p in points]
        result[label] = dict(mae_g=statistics.mean(abs(v) for v in errors),
                             rmse_g=math.sqrt(statistics.mean(v*v for v in errors)),
                             max_abs_error_g=max(abs(v) for v in errors))
    return result, points


def paired_loads(sessions):
    """Recompute already-documented windows from their original records."""
    lookup = {s['id']: s for s in sessions}
    pairs = []
    from analyze_temperature_run import load_session
    # Reuse the existing, independently recorded near-neighbour window protocol.
    for sid in ('2026-11-21_14-55-40_499922', '2026-11-21_15-11-23_513038'):
        source = lookup[sid]
        data = load_session(source['folder'], NEW_K)
        for pair in data['pairs']:
            if pair['requested_window_s'] != 60:
                continue
            pairs.append(dict(session=sid, reference_mass_g=pair['mass_g'],
                              temperature_c=pair['loaded']['temp_mean_c'],
                              increment_g=pair['increment_g'], error_g=pair['error_g'],
                              method='紧邻空载、带载末段、卸载后首段，60秒上限窗口',
                              category='同轮加载对照', role='描述载荷响应，非温补验证'))
    # Recompute the explicitly saved final 30-second stage windows. Original
    # frozen comparison snapshots are retained separately, never overwritten.
    files = [ROOT/'实验数据/分析结果/2026-11-20_去膜后标定/calibration_summary.json',
             ROOT/'实验数据/分析结果/2026-11-21_约25度对照/今日统一窗口/calibration_summary.json']
    for path in files:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        source = lookup[data['session_id']]
        windows = {}
        for stage in data['stages']:
            selected = [r for r in source['weights'] if stage['window_start_s'] <= r['elapsed_s'] < stage['window_end_s'] and r['paired_temp_c'] is not None]
            if stage.get('usable') and selected:
                windows[stage['stage_id']] = dict(stage=stage, stats=stats(selected))
        stages = data['stages']
        for index, stage in enumerate(stages):
            if stage['event_type'] != 'load' or stage['stage_id'] not in windows or index == 0 or index+1 >= len(stages):
                continue
            previous, following = stages[index-1], stages[index+1]
            if previous['stage_id'] not in windows or following['stage_id'] not in windows:
                continue
            b, l, a = [windows[p['stage_id']]['stats'] for p in (previous, stage, following)]
            fraction = (l['center_s']-b['center_s'])/(a['center_s']-b['center_s'])
            zero = b['raw_mean']+fraction*(a['raw_mean']-b['raw_mean'])
            increment = (l['raw_mean']-zero)/NEW_K
            pairs.append(dict(session=data['session_id'], reference_mass_g=stage['mass_g'],
                              temperature_c=l['paired_temp_c_mean'], increment_g=increment,
                              error_g=increment-stage['mass_g'], method='既有固定段尾窗口，前后空载时间插值，30秒上限',
                              category='室温载荷复核', role='标称砝码响应；跨日差异不直接归因温度'))
    return pairs


def source_manifest(specs, flat):
    entries = {}
    for spec in specs:
        files = [spec['csv']] if spec['legacy'] else list(spec['folder'].iterdir())
        for path in files:
            if path.is_file():
                entries[path.relative_to(ROOT).as_posix()] = dict(bytes=path.stat().st_size, sha256=digest(path))
    for item in flat:
        entries[item['file']] = dict(bytes=item['bytes'], sha256=item['sha256'])
    return entries


def export_tables(output, sessions, summary, comp, comp_points, loads, manifest, flat):
    write_csv(output/'会话总览.csv', summary)
    write_csv(output/'空载分钟统计.csv', [dict(**m) for s in sessions for m in s['minutes']])
    weight_rows, temp_rows, event_rows = [], [], []
    for session in sessions:
        for row in session['weights']:
            weight_rows.append({key: row.get(key) for key in (
                'session', 'source_row', 'seq', 'elapsed_s', 'raw', 'net', 'g', 'g_avg', 'g_iir',
                'paired_temp_c', 'temp_age_s', 'tare_base', 'epoch', 'phase', 'reference_mass_g',
                'coeff_counts_per_g', 'net_mass_g', 'assembly', 'transition', 'confirmed_empty',
                'unexpected_load', 'special_condition', 'paired_temp_source_row',
                'paired_temp_received_local')} | {'received_local': row['datetime'].isoformat(),
                                                 'valid_temperature_pair': row['paired_temp_c'] is not None})
        for row in session['temps']:
            temp_rows.append(dict(session=session['id'], source_row=row['source_row'],
                                  received_local=row['datetime'].isoformat(), elapsed_s=row['elapsed_s'], temp_c=row['temp_c']))
        for event in session['events']:
            event_rows.append(dict(event, session=session['id'], record_origin='原始事件'))
        for row in session['rows']:
            if row['kind'] in ('temperature_error', 'device_error', 'tare', 'partial', 'weight_saturated', 'weight_invalid') or 'USART1 OK' in row['original_line']:
                event_rows.append(dict(session=session['id'], source='原始串口',
                                       marked_local=row['datetime'].isoformat(), event_type=row['kind'], note=row['original_line']))
    write_csv(output/'配温重量明细.csv', weight_rows)
    write_csv(output/'有效温度明细.csv', temp_rows)
    write_csv(output/'事件与异常.csv', event_rows)
    write_csv(output/'加载响应对照.csv', loads)
    write_csv(output/'历史补偿迁移逐点对照.csv', comp_points)
    write_csv(output/'无温度散文件清单.csv', [p for p in flat if not p['has_temperature']])
    results = dict(analysis_date='2026-11-25', sources_scanned=len(sessions),
                   temperature_sources=sum(bool(s['temps']) for s in sessions),
                   total_valid_temperatures=sum(len(s['temps']) for s in sessions),
                   total_valid_weights=sum(len(s['weights']) for s in sessions if s['temps']),
                   total_paired_weights=sum(r['paired_temp_c'] is not None for s in sessions if s['temps'] for r in s['weights']),
                   total_temperature_errors=sum(p['temperature_errors'] for p in summary if p['valid_temperatures']),
                   first_temperature=min(r['datetime'] for s in sessions for r in s['temps']).isoformat(),
                   last_temperature=max(r['datetime'] for s in sessions for r in s['temps']).isoformat(),
                   temperature_min_c=min(r['temp_c'] for s in sessions for r in s['temps']),
                   temperature_max_c=max(r['temp_c'] for s in sessions for r in s['temps']),
                   captured_minutes=sum(p['duration_s'] for p in summary if p['valid_temperatures'])/60,
                   sessions=summary, zero_fits=[f for s in sessions for f in s['fits']],
                   tare_segments=[e for s in sessions for e in s['epochs']],
                   gaps=[g for s in sessions for g in s['gaps']],
                   paired_loads=loads, historical_compensation=comp,
                   parameters=dict(temp_age_limit_s=PAIR_AGE, minute_min_samples=180,
                                   minute_min_coverage_s=45, descriptive_fit_min_temp_span_c=.5,
                                   transition_skip_s=10, transition_end_guard_s=3,
                                   old_counts_per_g=OLD_K, new_counts_per_g=NEW_K),
                   source_files=manifest)
    lookup = {s['id']: s for s in sessions}
    same = lookup['2026-11-21_15-11-23_513038']
    compare_windows = []
    for a, b in [(2400, 2460), (4200, 4260)]:
        compare_windows.append(stats([r for r in same['weights'] if a <= r['elapsed_s'] < b
                                      and r['confirmed_empty']]))
    results['same_temperature_example'] = dict(session=same['id'], windows=compare_windows,
        temperature_difference_c=compare_windows[1]['paired_temp_c_mean']-compare_windows[0]['paired_temp_c_mean'],
        empty_mean_difference_g=compare_windows[1]['net_mass_g_mean']-compare_windows[0]['net_mass_g_mean'])
    room = lookup['2026-11-12_13-13-10_084101']
    valid_room = [r for r in room['weights'] if r['paired_temp_c'] is not None]
    start, end = room['weights'][0]['datetime'], room['weights'][-1]['datetime']
    first = stats([r for r in valid_room if r['datetime'] < start+timedelta(seconds=60)])
    last = stats([r for r in valid_room if r['datetime'] >= end-timedelta(seconds=60)])
    results['room_temperature_example'] = dict(session=room['id'], first=first, last=last,
        raw_mean_difference_g=(last['raw_mean']-first['raw_mean'])/OLD_K)
    (output/'分析结果.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return results


def plotting_setup(deps):
    if deps:
        sys.path.insert(0, str(deps))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for path in (Path('C:/Windows/Fonts/msyh.ttc'), Path('C:/Windows/Fonts/msyhbd.ttc')):
        if path.exists():
            font_manager.fontManager.addfont(str(path))
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Microsoft YaHei', 'DejaVu Sans'],
                         'axes.unicode_minus': False, 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.alpha': .20,
                         'pdf.fonttype': 42,
                         'figure.facecolor': 'white', 'savefig.facecolor': 'white'})
    return plt


def broken_xy(rows, value, time_scale=60):
    x, y, previous = [], [], None
    for row in rows:
        if previous and (row['elapsed_s']-previous['elapsed_s'] > 2 or
                         ('epoch' in row and row.get('epoch') != previous.get('epoch'))):
            x.append(float('nan')); y.append(float('nan'))
        x.append(row['elapsed_s']/time_scale)
        y.append(row.get(value, float('nan')))
        previous = row
    return x, y


def make_plots(output, sessions, results, comp_points, plt):
    from matplotlib.backends.backend_pdf import PdfPages
    figures = output/'图表'
    detail = figures/'各会话'
    detail.mkdir(parents=True, exist_ok=True)
    included = [s for s in sessions if s['temps']]
    lookup = {s['id']: s for s in sessions}
    blue, orange, gray = '#2166A5', '#C85A17', '#81909C'
    pdf = PdfPages(output/'全部图表.pdf')
    pdf.infodict().update(Title='全部温度串口数据图表', Author='电子秤毕设实验记录')

    def save_figure(fig, filename, dpi):
        fig.savefig(filename, dpi=dpi)
        pdf.savefig(fig)

    fig, ax = plt.subplots(figsize=(12.8, 12.6))
    for index, s in enumerate(included):
        vals = [r['temp_c'] for r in s['temps']]
        y = len(included)-index-1
        ax.plot([min(vals), max(vals)], [y, y], color=blue, lw=4, solid_capstyle='round')
        ax.scatter([vals[0], vals[-1]], [y, y], s=[34, 20], c=[orange, blue], zorder=3)
        ax.text(max(vals)+.13, y, f'{min(vals):.2f}～{max(vals):.2f}℃', va='center', fontsize=9)
    ax.set_yticks(range(len(included)))
    ax.set_yticklabels([s['t0'].strftime('%m-%d %H:%M')+'  '+s['context'][0] for s in reversed(included)], fontsize=9)
    ax.set_xlim(results['temperature_min_c']-.8, results['temperature_max_c']+3.4)
    ax.set_xlabel('有效温度读数（℃）')
    ax.set_title('全部温度串口记录的覆盖范围', fontsize=17, loc='left', pad=22)
    fig.text(.025, .025, '线段为各会话实际最小～最大值；橙点为起始温度，蓝点为末温。范围包含动态加热过程，不代表恒温点。', fontsize=10)
    fig.subplots_adjust(left=.40, right=.97, bottom=.07, top=.94)
    save_figure(fig, figures/'01_温度覆盖总览.png', dpi=160)
    plt.close(fig)

    selected = ['2026-11-12_13-13-10_084101', '2026-11-12_13-56-43_455079', '2026-11-21_15-11-23_513038']
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.0), sharex='col')
    for col, sid in enumerate(selected):
        s = lookup[sid]
        axes[0, col].plot(*broken_xy(s['temps'], 'temp_c'), color=blue, lw=1.5)
        axes[0, col].set_title(s['context'][0]+'\n'+s['t0'].strftime('%Y-%m-%d %H:%M'), fontsize=12)
        axes[0, col].set_ylabel('探头温度（℃）')
        empty = [r for r in s['weights'] if r.get('confirmed_empty') and not r['special_condition']]
        axes[1, col].scatter([r['elapsed_s']/60 for r in empty], [r['g_avg'] for r in empty], color=gray, s=2, alpha=.20, rasterized=True)
        groups = defaultdict(list)
        for minute in s['minutes']:
            if not minute['special_condition']:
                groups[(minute['epoch'], minute['phase'])].append(minute)
        for group in groups.values():
            axes[1, col].plot([m['center_s']/60 for m in group], [m['g_avg_mean'] for m in group], color=orange, lw=2, marker='o', ms=3)
        axes[1, col].set_ylabel('空载示值（g）')
        axes[1, col].set_xlabel('本次记录经过时间（分钟）')
        axes[1, col].axhline(0, color='black', lw=.7, alpha=.5)
    fig.suptitle('温度变化与空载零点变化，分别观察', fontsize=17, x=.06, ha='left')
    fig.text(.06, .02, '灰点：板上5点平均输出；橙线：60秒分箱均值。加载段及过渡留空，各会话保持自己的零点基准。', fontsize=10)
    fig.tight_layout(rect=(0, .05, 1, .94))
    save_figure(fig, figures/'02_重点温度与零点走势.png', dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5))
    for ax, sid in zip(axes, selected):
        s = lookup[sid]
        mins = [m for m in s['minutes'] if not m['special_condition']]
        x = [m['paired_temp_c_mean'] for m in mins]
        y = [m['net_mass_g_mean'] for m in mins]
        points = ax.scatter(x, y, c=[m['center_s']/60 for m in mins], cmap='viridis', s=30)
        model = fit_line(x, y) if x and max(x)-min(x) >= .5 else None
        if model:
            lo, hi = min(x), max(x)
            ax.plot([lo, hi], [model['intercept']+model['slope']*lo, model['intercept']+model['slope']*hi], color=orange, lw=1.6)
            text = f'表观斜率 {model["slope"]:+.3f} g/℃\nR² = {model["r_squared"]:.3f}'
        else:
            text = '温差不足0.5℃\n不估算温漂斜率'
        ax.text(.04, .96, text, transform=ax.transAxes, va='top', fontsize=10,
                bbox=dict(facecolor='white', edgecolor='none', alpha=.90))
        ax.set_title(s['context'][0], fontsize=12)
        ax.set_xlabel('分钟平均探头温度（℃）')
        ax.set_ylabel('分钟空载均值（g）')
        fig.colorbar(points, ax=ax, label='经过时间（分钟）', shrink=.7)
    fig.suptitle('相同温度下，零点是否能够重复', fontsize=17, x=.06, ha='left')
    fig.text(.06, .02, '每个点是一段60秒分箱均值；颜色表示时间。拟合只描述本轮相关性，不作跨会话统一回归。', fontsize=10)
    fig.tight_layout(rect=(0, .07, 1, .91))
    save_figure(fig, figures/'03_温度与空载散点.png', dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.8))
    markers = {100: 'o', 200: '^', 500: 's'}
    colors = {'2026-11-20': '#2166A5', '2026-11-21': '#C85A17'}
    labels_seen = set()
    for p in results['paired_loads']:
        ax = axes[0] if p['category'] == '室温载荷复核' else axes[1]
        if ax is axes[1] and p['reference_mass_g'] != 200:
            continue
        label = p['session'][:10]+' '+str(int(p['reference_mass_g']))+' g'
        legend_key = (p['category'], label)
        ax.scatter(p['temperature_c'], p['error_g'], marker=markers[int(p['reference_mass_g'])],
                   color=colors[p['session'][:10]], s=80, alpha=.85,
                   label=label if legend_key not in labels_seen else None)
        labels_seen.add(legend_key)
    for ax in axes:
        ax.axhline(0, color='black', lw=1)
        ax.set_xlabel('带载窗口平均探头温度（℃）')
        ax.set_ylabel('加载增量 − 标称质量（g）')
    axes[0].set_title('两日室温复核，30秒段尾窗口', fontsize=12)
    axes[1].set_title('11月21日同轮200 g，60秒近邻窗口', fontsize=12)
    axes[0].legend(ncol=2, loc='upper right', fontsize=8)
    fig.suptitle('不同温度条件下的砝码加载响应', fontsize=16, x=.07, ha='left')
    fig.text(.07, .02, '原始计数扣前后空载基线后换算。不同窗口方法分图展示，不能把两种窗口的点当作独立重复实验。', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .92))
    save_figure(fig, figures/'04_不同温度加载响应.png', dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6))
    stride = max(1, len(comp_points)//700)
    points = comp_points[::stride]
    for key, color, label in [('before_error_g', blue, '固定标定'), ('after_error_g', orange, '迁移空载温度系数后')]:
        axes[0].scatter([p['temp_c'] for p in points], [p[key] for p in points], s=6, alpha=.35, color=color, label=label)
    axes[0].axhline(0, color='black', lw=.8)
    axes[0].set_xlabel('探头温度（℃）'); axes[0].set_ylabel('相对标称500 g的偏差（g）')
    axes[0].legend(fontsize=9)
    metrics = ['mae_g', 'rmse_g', 'max_abs_error_g']
    labels = ['平均绝对偏差', '均方根偏差', '最大绝对偏差']
    comp = results['historical_compensation']
    for index, phase in enumerate(['before', 'after']):
        bars = axes[1].bar([i+(index-.5)*.35 for i in range(3)], [comp[phase][m] for m in metrics], width=.35,
                           color=[blue, orange][index], label=['固定标定', '系数迁移后'][index])
        axes[1].bar_label(bars, fmt='%.2f', padding=3, fontsize=9)
    axes[1].set_xticks(range(3), labels); axes[1].set_ylabel('偏差（g）'); axes[1].legend(fontsize=9)
    axes[1].set_ylim(0, max(comp['after'][m] for m in metrics)*1.25)
    fig.suptitle('历史空载系数迁移到次日500 g：本次试算没有改善', fontsize=15, x=.07, ha='left')
    fig.text(.07, .02, '同一批有效测试行逐点对比；训练为11月12日空载降温，测试为11月13日带载降温。不是已启用的补偿。', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .92))
    save_figure(fig, figures/'05_历史温补试算复核.png', dpi=170)
    plt.close(fig)

    # Every included run gets its own full trajectory, including errors/loads.
    for session in included:
        fig, axes = plt.subplots(3, 1, figsize=(11.5, 8.3), sharex=True)
        axes[0].plot(*broken_xy(session['temps'], 'temp_c'), color=blue, lw=1.3)
        axes[1].plot(*broken_xy(session['weights'], 'raw'), color=gray, lw=.7)
        shown = [r for r in session['weights'] if r['g_avg'] is not None]
        axes[2].plot(*broken_xy(shown, 'g_avg'), color=orange, lw=.9)
        special_groups = defaultdict(list)
        for row in session['weights']:
            if row['special_condition']:
                special_groups[row['special_condition']].append(row)
        for axis, label in zip(axes, ['探头温度（℃）', '原始计数 raw', '板上滤波示值（g）']):
            axis.set_ylabel(label)
            for epoch in session['epochs'][1:]:
                x = (dt(epoch['time'])-session['t0']).total_seconds()/60
                axis.axvline(x, color='#B03A48', ls='--', lw=1, alpha=.7)
            for gap in session['gaps']:
                a, b = [(dt(gap[k])-session['t0']).total_seconds()/60 for k in ('start', 'end')]
                axis.axvspan(a, b, color='#B6BEC4', alpha=.3)
            for group in special_groups.values():
                axis.axvspan(group[0]['elapsed_s']/60, group[-1]['elapsed_s']/60,
                             color='#E5AB46', alpha=.10)
        for phase in session['phases']:
            if phase['mass'] is not None and phase['mass'] > 0:
                axes[2].axvspan(phase['low']/60, phase['high']/60, color=blue, alpha=.06)
        axes[2].set_xlabel('本次记录经过时间（分钟）')
        fig.suptitle(session['context'][0]+'\n'+session['id'], fontsize=14, x=.09, ha='left')
        footer = '虚线：去皮/启动/基准变化；灰区：接收间断；浅蓝：已知带载；浅橙：探头重贴/加热动态等条件变化。'
        fig.text(.09, .025, footer, fontsize=8.0)
        fig.tight_layout(rect=(0, .06, 1, .92))
        save_figure(fig, detail/(session['id']+'.png'), dpi=135)
        plt.close(fig)
    pdf.close()
    return figures


def make_report(output, sessions, results):
    """Write the compact reader view; tables/JSON retain all detailed measures."""
    included = [s for s in sessions if s['temps']]
    summary_lookup = {r['session']: r for r in results['sessions']}
    comp = results['historical_compensation']
    room = results['room_temperature_example']
    same = results['same_temperature_example']
    fit_by_id = {f['session']: f for f in results['zero_fits'] if f['temperature_model']}
    lines = ['# 全部温度串口数据分析', '',
             f'分析日期：2026年11月25日。有效温度记录覆盖{results["first_temperature"][:10]}至{results["last_temperature"][:10]}。', '',
             f'共核查{results["sources_scanned"]}个会话/早期记录，其中{results["temperature_sources"]}份含有效温度。累计保存时长约{results["captured_minutes"]:.1f}分钟，非连续实验；有效温度{results["total_valid_temperatures"]:,}条，含温度会话中的有效重量{results["total_valid_weights"]:,}条，其中{results["total_paired_weights"]:,}条能与此前2秒内的有效温度配对。实际温度范围{results["temperature_min_c"]:.2f}～{results["temperature_max_c"]:.2f}℃，上限包含吹风瞬态。', '',
             '## 主要发现', '',
             '1. 温度和称重链路已积累多轮真实记录；10月18日是最早的温度驱动验证。连接检查、试录、加热、降温、标定和静置观察全部列入总览，按用途解释。',
             '2. 一次冰杯空载降温出现明显的温度相关变化，但室温小温差也有零点变化；相近温度下的读数不能总是重复。当前数据不支持将全部零漂归于温度。',
             '3. 同温区加载前后空载配对后的砝码响应可以比较；跨日加载偏差还包含日期、受力历史和装配等差异，不能据此直接确定灵敏度温度系数。',
             f'4. 历史空载系数在次日500 g记录上的迁移复算：MAE {comp["before"]["mae_g"]:.3f}→{comp["after"]["mae_g"]:.3f} g，RMSE {comp["before"]["rmse_g"]:.3f}→{comp["after"]["rmse_g"]:.3f} g，最大绝对偏差 {comp["before"]["max_abs_error_g"]:.3f}→{comp["after"]["max_abs_error_g"]:.3f} g。本次迁移未改善，暂不据此启用补偿。',
             '5. 新1 kg梁尚未获得有效采集数据。本次全体结果属于历史20 kg梁及相应装配，不能填为新梁性能。', '',
             '## 统计方法', '',
             '原始CSV、TXT、字节文件和元数据均只读，保存SHA256以便复核。同一会话内以此前有效温度向前配对重量，温度错误、超龄、饱和和不完整行不纳入定量配温统计。断档不插值，去皮/启动/基准变化拆段。', '',
             '零点分析使用有标签、事件或阶段记录支持的空载区间，换载后留10秒、换载前留3秒保护。未知载荷保留在完整曲线中。已确认100 g短时放取、探头脱落重贴、移杯晃袋和拔线附近分别标记。不会按偏差小来挑选稳定样本。', '',
             '每段按60秒分箱，至少180条有效配温重量且有效覆盖至少45秒才列入分钟统计。温度拟合只针对同会话同零点段，至少5个有效分钟箱，温差至少0.5℃；这是本次分析的估计条件，不是任务书验收线。R²是分钟均值的描述性拟合，不是补偿验证，也不把数千相邻样本当作独立重复实验。', '',
             '质量趋势使用当时标定系数：旧版177.6184计数/g，11月13日14:34:42.987后为178.20计数/g。图中“板上滤波示值”保留原串口值。历史补偿复算固定旧版系数，验证行不变。未扣除估计膜重，装配分组保留。', '',
             '## 相近温度下的窗口对照', '',
             f'11月12日室温静置：前60秒均温{room["first"]["paired_temp_c_mean"]:.3f}℃，后60秒{room["last"]["paired_temp_c_mean"]:.3f}℃；对应空载均值{room["first"]["g_avg_mean"]:+.3f}→{room["last"]["g_avg_mean"]:+.3f} g，原始计数变化折合{room["raw_mean_difference_g"]:+.3f} g。探头温度变化很小，零点仍变化。', '',
             f'11月21日同温对照：15:51～15:52均温{same["windows"][0]["paired_temp_c_mean"]:.3f}℃、空载均值{same["windows"][0]["net_mass_g_mean"]:+.3f} g；16:21～16:22均温{same["windows"][1]["paired_temp_c_mean"]:.3f}℃、空载均值{same["windows"][1]["net_mass_g_mean"]:+.3f} g。两窗均温差{same["temperature_difference_c"]:+.4f}℃，空载均值相差{same["empty_mean_difference_g"]:+.3f} g。仅凭这个探头温度不能确定唯一零点，也不能据此排除热滞后或其他未测温度的影响。', '',
             '## 空载分钟均值的描述性关系', '',
             '| 会话 | 分钟箱数 | 窗口均温跨度/℃ | 表观斜率/(g/℃) | 温度拟合R² | 时间拟合R² |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for f in results['zero_fits']:
        model, tm = f['temperature_model'], f['time_model']
        lines.append(f'| {f["session"]}，基准段{f["epoch"]} | {f["minute_count"]} | {f["temp_span_c"]:.3f} | '+
                     (f'{model["slope"]:+.4f} | {model["r_squared"]:.3f}' if model else '不估计 | 不估计')+
                     f' | {tm["r_squared"]:.3f} |' if tm else '')
    lines += ['', '温差不足时不使用很大的“每度斜率”作结论。时间拟合仅作为另一种描述，不表示时间本身是物理原因。', '',
              '## 图表', '',
              '1. 图01：所有会话温度范围。', '2. 图02：室温、冰杯降温、自然降温三类过程与空载走势。',
              '3. 图03：温度与空载分钟均值散点，颜色表示经过时间。', '4. 图04：约21～25℃下不同砝码加载响应。',
              '5. 图05：历史温补迁移前后偏差。', '6. 各会话目录：每份含有效温度的记录均有温度、原始计数、滤波重量三条完整走势。', '',
              '## 各会话清单', '', '| 会话 | 用途 | 时长/分钟 | 温度范围/℃ | 有效配温重量 | 原状态 |', '| --- | --- | ---: | --- | ---: | --- |']
    for s in sessions:
        r = summary_lookup[s['id']]
        trange = f'{r["temp_min_c"]:.2f}～{r["temp_max_c"]:.2f}' if r['temp_min_c'] is not None else '无有效温度'
        lines.append(f'| {s["id"]} | {r["purpose"]} | {r["duration_s"]/60:.2f} | {trange} | {r["paired_weights"]} | {r["original_status"]} |')
    lines += ['', '“running”是历史元数据未正常收尾的原状态；当前按实际已有文件快照分析，不表示仍在采集。缺口与异常均保留，未修写原始状态。', '',
              '## 数据位置', '', '会话总览、空载分钟统计、配温重量明细、有效温度明细、事件与异常、加载响应及历史补偿逐点结果位于同目录CSV；重量明细保留未配温的行，以valid_temperature_pair字段区分。全部参数、来源哈希和统计在分析结果JSON中。', '',
              '30秒加载对照按既有JSON保存的最终取样边界重新计算，没有调用早期冻结的比较数值；11月20日500 g约499.577 g，与原冻结窗口499.621 g属于不同窗口，不覆盖原结果。图04把30秒段尾与60秒近邻两种方法分开，不能把它们当成两次独立重复。', '',
              '## 后续实验', '', '新1 kg梁接线确认后单独标定并归档。优先复核室温长时稳定性和重复加载，再在不同温区重复空载、带载、卸载序列。允许分次开机，但基准和原始计数分别保存；用未参与拟合的新一轮数据检查补偿效果。']
    report = '\n'.join(lines)+'\n'
    (output/'分析报告.md').write_text(report, encoding='utf-8')

    def esc(value):
        return html.escape(str(value))
    cards = []
    for s in included:
        r = summary_lookup[s['id']]
        cards.append(f'<details class="session"><summary><strong>{esc(s["context"][0])}</strong>　{esc(s["id"])}　{r["duration_s"]/60:.1f}分钟　{r["temp_min_c"]:.2f}～{r["temp_max_c"]:.2f}℃</summary>'
                     f'<p>{esc(r["note"])}</p><p>有效重量 {r["valid_weights"]:,}，有效温度 {r["valid_temperatures"]:,}，配温重量 {r["paired_weights"]:,}；原始状态 {esc(r["original_status"])}。</p>'
                     f'<img loading="lazy" src="图表/各会话/{esc(s["id"])}.png" alt="{esc(s["context"][0])}完整走势">'
                     f'<p><a href="../../../{esc(r["source"])}">查看原始记录CSV</a></p></details>')
    figure_items = [
        ('01_温度覆盖总览.png', '温度覆盖总览', '包含所有实际温度读数，连接检查和动态加热也计入覆盖；不能把范围端点当成稳定温点。'),
        ('02_重点温度与零点走势.png', '温度与零点的时间走势', '温差很小也会出现空载变化；降温时有相关走势，但自然降温中的零点不是单调变化。'),
        ('03_温度与空载散点.png', '温度与空载均值', '同一温度处的竖向分散，以及颜色对应的时间差，有助于判断温度单变量解释是否充分。'),
        ('04_不同温度加载响应.png', '不同温度下的加载增量', '扣除近邻空载用于检查加载响应；不把这种离线扣基线直接称为温度补偿。'),
        ('05_历史温补试算复核.png', '温度补偿迁移复算', '这次跨日系数迁移使偏差增大，保留全部验证行和计算结果。'),
    ]
    figure_html = ''.join(f'<section><h2>{title}</h2><p>{caption}</p><a href="图表/{name}"><img src="图表/{name}" alt="{title}"></a></section>' for name, title, caption in figure_items)
    statistics_html = ''.join(f'<tr><td>{esc(f["session"])}</td><td>{f["minute_count"]}</td><td>{f["temp_span_c"]:.3f}</td><td>{f["temperature_model"]["slope"]:+.4f}</td><td>{f["temperature_model"]["r_squared"]:.3f}</td></tr>' for f in results['zero_fits'] if f['temperature_model'])
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>全部温度串口数据分析</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;color:#20313e;background:#f4f6f8;margin:0;line-height:1.75}}main{{max-width:1160px;margin:auto;padding:32px 22px}}h1{{font-size:30px;margin:0}}h2{{font-size:22px;margin:0 0 12px}}section,details{{background:white;padding:24px;margin:22px 0;border:1px solid #dde3e8;border-radius:8px}}img{{display:block;max-width:100%;height:auto;margin:auto}}p{{margin:8px 0 16px}}.lead{{font-size:18px}}.facts{{display:flex;flex-wrap:wrap;gap:28px;margin:20px 0}}.facts strong{{font-size:27px;display:block;color:#2166a5}}small{{color:#5f6d78}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;border-bottom:1px solid #dce3e9;padding:9px}}th{{background:#edf2f6}}summary{{cursor:pointer}}a{{color:#155d96}}.downloads{{display:flex;gap:18px;flex-wrap:wrap}}@media print{{body{{background:white}}section,details{{break-inside:avoid}}}}
</style><main><h1>全部温度串口数据分析</h1><small>2026年11月25日 · 历史20 kg称重梁 · 原始数据只读</small>
<p class="lead">已有记录能够展示温度、空载漂移和载荷响应；当前还没有验证出可跨轮稳定改善的温度补偿。</p>
<div class="facts"><div><strong>{results['temperature_sources']}</strong>份含有效温度的记录</div><div><strong>{results['total_valid_temperatures']:,}</strong>条有效温度</div><div><strong>{results['total_paired_weights']:,}</strong>条有效配温重量</div><div><strong>{results['captured_minutes']:.1f}分钟</strong>累计记录时长，非连续</div></div>
<section><h2>先看这三个结果</h2><ul><li>室温小温差也存在零点变化；一次冰杯降温有明显相关性，但不能解释其他轮次的全部变化。</li><li>11月21日两个窗口温度约 {same['windows'][0]['paired_temp_c_mean']:.2f}℃和 {same['windows'][1]['paired_temp_c_mean']:.2f}℃，空载均值仍相差 {same['empty_mean_difference_g']:.2f} g。按近邻空载扣基线后，可以另看砝码加载响应。</li><li>历史500 g迁移验证的平均绝对偏差由 {comp['before']['mae_g']:.2f} g 增至 {comp['after']['mae_g']:.2f} g，不能据此宣称补偿有效。</li></ul><p>温度读数从 {results['first_temperature'][:10]} 开始。共核查 {results['sources_scanned']} 个会话/早期记录，包含无有效温度的故障记录。新1 kg梁尚无实测数据。</p></section>
{figure_html}
<section><h2>分钟均值的温度相关性</h2><p>同一会话、同零点段分别计算；只对至少5个分钟箱、均温跨度至少0.5℃的区间列出表观斜率。没有跨日合并拟合。</p><div style="overflow:auto"><table><tr><th>会话</th><th>分钟箱</th><th>均温跨度/℃</th><th>表观斜率/(g/℃)</th><th>R²</th></tr>{statistics_html}</table></div></section>
<section><h2>每份记录的完整曲线</h2><p>点击展开。温度、原始计数和滤波重量全部保留；虚线标记基准变化，间断留空，载荷与异常按记录解释。</p><input id="filter" placeholder="输入日期或用途筛选" style="padding:9px;width:90%;font:inherit" oninput="document.querySelectorAll('.session').forEach(e=>e.hidden=!e.textContent.includes(this.value))"></section>
{''.join(cards)}
<section><h2>统计口径与原始资料</h2><p>温度与重量是交错输出，用此前有效温度向前配对，年龄上限2秒；不使用未来温度，也不跨错误状态补值。断档不插值，去皮/启动拆段，未知载荷不假定为空载。每分钟统计至少180条有效配温重量、覆盖45秒。重复相邻采样不是独立实验重复。</p><p>不同固件的换算系数分别记录，图中板上滤波值保持原样。装配分组保留，不统一扣除估计膜重。两段旧元数据的“running”状态保持原样，本次按文件快照分析。</p><div class="downloads"><a href="全部图表.pdf">全部图表PDF</a><a href="会话总览.csv">会话总览</a><a href="空载分钟统计.csv">分钟统计</a><a href="加载响应对照.csv">加载对照</a><a href="事件与异常.csv">事件与异常</a><a href="分析报告.md">文字报告</a><a href="分析结果.json">计算和来源哈希</a></div></section></main></html>'''
    (output/'分析报告.html').write_text(document, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'实验数据/分析结果/全部温度串口分析_2026-11-25')
    parser.add_argument('--plot-deps', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if RAW == output or RAW in output.parents:
        raise ValueError('Output must be outside original data')
    output.mkdir(parents=True, exist_ok=True)
    specs, flat = discover()
    manifest = source_manifest(specs, flat)
    sessions = [parse_session(s) for s in specs]
    summary = [session_summary(s) for s in sessions]
    comp, points = historical_compensation(sessions)
    loads = paired_loads(sessions)
    results = export_tables(output, sessions, summary, comp, points, loads, manifest, flat)
    plt = plotting_setup(args.plot_deps)
    make_plots(output, sessions, results, points, plt)
    make_report(output, sessions, results)
    changed = [name for name, entry in manifest.items() if digest(ROOT/name) != entry['sha256']]
    if changed:
        raise RuntimeError('Source changed during analysis: '+str(changed))
    validation = dict(raw_files_unchanged=len(manifest),
                      finite_fit_values=all(math.isfinite(f['temperature_model']['slope']) for f in results['zero_fits'] if f['temperature_model']),
                      historical_validation_rows=len(points),
                      plot_count=len(list((output/'图表').rglob('*.png'))))
    (output/'核对结果.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: results[key] for key in ('sources_scanned', 'temperature_sources', 'total_valid_temperatures', 'total_paired_weights', 'temperature_min_c', 'temperature_max_c', 'captured_minutes')}, ensure_ascii=False))
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == '__main__':
    main()
