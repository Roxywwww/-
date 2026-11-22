"""用统一窗口与固定换算系数比较两轮载荷响应，不覆盖原始会话。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from summarize_calibration import summarize


def compare(first, second, output, current_k=178.20):
    output=Path(output).resolve()
    # 此处使用单独的统一窗口结果，不读取原标定目录中的冻结系数。
    days=[summarize(first, output/'昨日统一窗口', current_k),
          summarize(second, output/'今日统一窗口', current_k)]
    groups=[]
    for day in days:
        grouped=defaultdict(list)
        for point in day['comparisons']:
            grouped[point['mass_g']].append(point)
        groups.append(grouped)
    comparisons=[]
    for mass in sorted(set(groups[0]) & set(groups[1])):
        left,right=groups[0][mass],groups[1][mass]
        t1,t2=mean(x['temp_mean_c'] for x in left),mean(x['temp_mean_c'] for x in right)
        m1,m2=mean(x['mass_current_k_g'] for x in left),mean(x['mass_current_k_g'] for x in right)
        delta=t2-t1
        comparisons.append({
            '标称载荷_g':mass, '首日梁温_℃':t1, '次日梁温_℃':t2,
            '首日加载增量_g':m1, '次日加载增量_g':m2,
            '首日偏差_g':m1-mass, '次日偏差_g':m2-mass,
            '次日减首日_g':m2-m1,
            '温差_℃':delta,
            '跨日表观变化率_g每℃':(m2-m1)/delta if abs(delta)>0.01 else None,
            '首日局部计数每克':mean(x['local_counts_per_g'] for x in left),
            '次日局部计数每克':mean(x['local_counts_per_g'] for x in right),
            '首日取数方法':' / '.join(sorted({x['zero_method'] for x in left})),
            '次日取数方法':' / '.join(sorted({x['zero_method'] for x in right})),
        })
    zeros=[]
    for day in days:
        for stage in day['stages']:
            if stage['event_type']=='unload' and stage['usable']:
                zeros.append({'会话':day['session_id'],'段号':stage['stage_id'],
                              '梁温_℃':stage['temp_mean_c'],'空载raw均值':stage['raw_mean'],
                              '空载滤波均值_g':stage['g_avg_mean'],
                              '有效条数':stage['rows']})
    report={
        'sessions':[day['session_id'] for day in days],
        'source_status':[day['source_status'] for day in days],
        'common_counts_per_g':current_k,
        'interpretation':'两轮同装配在不同温度条件下的跨日观察；操作者报告期间重新开机。表观变化率包含日期和载荷历史差异，不直接作为已验证的纯温度系数。',
        'zero_interpretation':'原始空载计数和各轮去皮基准分别保存，不把两日空载net或屏幕读数之差直接当成温漂。',
        'comparison_rule':days[0]['rule'],
        'comparisons':comparisons,
        'zeros':zeros,
    }
    (output/'两日温度载荷对照.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for filename, rows in [('两日同载荷对照.csv',comparisons),('两日空载窗口.csv',zeros)]:
        with (output/filename).open('w',encoding='utf-8-sig',newline='') as file:
            fields=list(rows[0]) if rows else ['状态']
            writer=csv.DictWriter(file,fields)
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({'pair_count':len(comparisons),'comparisons':comparisons},ensure_ascii=True))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first',type=Path)
    parser.add_argument('second',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--current-k',type=float,default=178.20)
    args=parser.parse_args()
    compare(args.first,args.second,args.output,args.current_k)
