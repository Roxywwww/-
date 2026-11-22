"""按人工加载事件汇总本轮标定；只读原始数据，分析文件另存。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, stdev


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def valid(row):
    try:
        return (row['record_type'] == 'weight' and row['line_complete'] == '1'
                and row['temp_state'] == 'ok' and float(row['temp_age_s']) <= 2
                and -8388608 < int(row['raw']) < 8388607)
    except (KeyError, TypeError, ValueError):
        return False


def summarize(session, output, current_k=178.20, skip_seconds=10, window_seconds=30):
    session, output = Path(session).resolve(), Path(output).resolve()
    if output == session or session in output.parents:
        raise ValueError('分析输出必须放在原始会话目录之外')
    rows = read_csv(session/'records.csv')
    metadata = json.loads((session/'session.json').read_text(encoding='utf-8'))
    events = read_csv(session/'events.csv')
    complete = [r for r in rows if valid(r)]
    last_elapsed = max((float(r['elapsed_s']) for r in complete), default=0)
    markers = [e for e in events if e['event_type'] in ('load', 'unload', 'reset', 'tare')]
    # 人工确认可能晚于动作。以宽阈值持续进入新载荷区定位过渡，
    # 只用于段边界，不按小误差筛选数据，也不改动原始事件时刻。
    effective = []
    for index, event in enumerate(markers):
        marked = float(event['elapsed_s'])
        detected = marked
        if index and event['event_type'] in ('load', 'unload'):
            previous = markers[index-1]
            previous_mass = float(previous.get('reference_mass_g') or 0)
            mass = float(event.get('reference_mass_g') or 0)
            if previous['event_type'] in ('load', 'unload') and abs(mass-previous_mass)>10:
                low = max(float(previous['elapsed_s'])+5, marked-120)
                run=[]
                for row in complete:
                    tick=float(row['elapsed_s'])
                    if not low <= tick <= marked+10:
                        continue
                    try:
                        in_band=abs(float(row['g'])-mass) <= max(5, mass*0.05)
                    except (KeyError, ValueError):
                        in_band=False
                    if in_band:
                        run.append(tick)
                        if len(run)>=10:
                            detected=run[0]
                            break
                    else:
                        run=[]
        effective.append(detected)
    stages = []
    for index, event in enumerate(markers):
        if event['event_type'] not in ('load', 'unload'):
            continue
        start = effective[index]
        # 进入新载荷区前也可能已有搬动或部分受力，闭合段尾再留3秒保护带。
        end = effective[index+1]-3 if index+1 < len(markers) else last_elapsed
        low = max(start+skip_seconds, end-window_seconds)
        selected = [r for r in complete if low <= float(r['elapsed_s']) < end]
        zero_breaks = [r for r in rows if r.get('record_type') == 'tare'
                       and start <= float(r['elapsed_s']) < end]
        # 去皮或复位会改变段内基准；不跨这类记录给出标定结果。
        enough = len(selected) >= 60 and not zero_breaks
        item = {'stage_id': event['event_id'], 'event_type': event['event_type'],
                'mass_g': float(event['reference_mass_g'] or 0),
                'marked_local': event['marked_local'],
                'marked_elapsed_s': float(event['elapsed_s']),
                'transition_elapsed_s': start,
                'window_start_s': low, 'window_end_s': end,
                'rows': len(selected), 'usable': enough,
                'reason': ('段内有去皮/复位输出' if zero_breaks else
                           '有效样本不足60条' if not enough else ''),
                'note': event['note']}
        if selected:
            item.update(raw_mean=mean(int(r['raw']) for r in selected),
                        raw_sd=stdev(int(r['raw']) for r in selected) if len(selected)>1 else 0,
                        time_center_s=mean(float(r['elapsed_s']) for r in selected),
                        g_avg_mean=mean(float(r['g_avg']) for r in selected if r.get('g_avg')),
                        temp_mean_c=mean(float(r['latest_temp_c']) for r in selected),
                        temp_min_c=min(float(r['latest_temp_c']) for r in selected),
                        temp_max_c=max(float(r['latest_temp_c']) for r in selected),
                        seq_first=selected[0]['seq'], seq_last=selected[-1]['seq'])
        stages.append(item)

    comparisons=[]
    for index, stage in enumerate(stages):
        if stage['event_type'] != 'load' or not stage['usable']:
            continue
        before = stages[index-1] if index else None
        after = stages[index+1] if index+1 < len(stages) else None
        if not before or before['event_type'] != 'unload' or not before['usable']:
            continue
        zero = before['raw_mean']
        method = '加载前近邻空载'
        if after and after['event_type'] == 'unload' and after['usable']:
            fraction = ((stage['time_center_s']-before['time_center_s']) /
                        (after['time_center_s']-before['time_center_s']))
            zero += fraction * (after['raw_mean']-before['raw_mean'])
            method = '前后空载均值按时间线性插值'
        delta = stage['raw_mean']-zero
        comparisons.append({'stage_id': stage['stage_id'], 'mass_g': stage['mass_g'],
                            'temp_mean_c': stage['temp_mean_c'],
                            'rows': stage['rows'], 'zero_method': method,
                            'delta_raw': delta, 'local_counts_per_g': delta/stage['mass_g'],
                            'mass_current_k_g': delta/current_k,
                            'error_current_k_g': delta/current_k-stage['mass_g']})
    # 100g留作独立载荷核验；200g与500g两种载荷齐全后才估计新系数。
    fitting = [x for x in comparisons if x['mass_g'] in (200, 500)]
    k = (sum(x['mass_g']*x['delta_raw'] for x in fitting) /
         sum(x['mass_g']**2 for x in fitting)
         if {x['mass_g'] for x in fitting} == {200, 500} else None)
    frozen_file=output/'calibration_frozen_200_500.json'
    if frozen_file.exists():
        frozen=json.loads(frozen_file.read_text(encoding='utf-8'))
        if frozen['session_id']!=session.name:
            raise ValueError('冻结标定与本会话不一致')
        k=frozen['candidate_counts_per_g']
        comparisons=[dict(x) for x in frozen['comparisons'] if x['mass_g'] in (200,500)] + [x for x in comparisons if x['mass_g'] not in (200,500)]
    if k is not None:
        for item in comparisons:
            item['mass_candidate_k_g'] = item['delta_raw']/k
            item['error_candidate_k_g'] = item['delta_raw']/k-item['mass_g']
    result = {'session_id': session.name, 'source': str(session),
              'source_status': metadata.get('status'),
              'current_counts_per_g': current_k, 'candidate_counts_per_g': k,
              'frozen_calibration': str(frozen_file) if frozen_file.exists() else None,
              'rule': f'动作后跳过{skip_seconds}秒，下一次换载前留3秒保护带，段尾最多{window_seconds}秒；至少60条有效重量，温度有效且年龄不超过2秒',
              'transition_rule': '在确认前最多120秒内寻找宽载荷区间内连续10条读数定位换载，原事件时刻保留；统计窗口不按小误差筛选',
              'film_mass_correction_g': None,
              'film_note': '去膜前后按装配分组；不从历史去皮示值统一减去估计膜重',
              'stages': stages, 'comparisons': comparisons}
    output.mkdir(parents=True, exist_ok=True)
    (output/'calibration_summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for filename, data in [('稳定窗口汇总.csv', stages), ('加载增量与标定复核.csv', comparisons)]:
        fields = list(dict.fromkeys(key for row in data for key in row))
        with (output/filename).open('w', encoding='utf-8-sig', newline='') as file:
            writer=csv.DictWriter(file, fields)
            writer.writeheader()
            writer.writerows(data)
    print(json.dumps({'stages': len(stages), 'comparisons': comparisons,
                      'candidate_counts_per_g': k}, ensure_ascii=True))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--current-k', type=float, default=178.20)
    arguments=parser.parse_args()
    summarize(arguments.session, arguments.output, arguments.current_k)
