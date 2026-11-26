"""Temperature-only regrouping of the frozen 20 kg minute audit.

No mass-dependent deletion. Show all-bin averages and earliest-window views
side by side with the full result. This is a post-hoc exploratory analysis.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import statistics

from analyze_all_temperature import ROOT, fit_line, plotting_setup, write_csv

INPUT = ROOT/'实验数据/分析结果/全部温度串口分析_2026-11-25'
OUTPUT = ROOT/'实验数据/分析结果/20kg_不同温区探索分析_2026-11-25'
WIDTHS = (.25, .5)
LABELS = {'2026-11-12_13-56-43_455079': '11月12日冰杯空载降温',
          '2026-11-21_15-11-23_513038': '11月21日自然空载降温'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zones(rows, width):
    """Half-open Celsius bins anchored at zero; selection never reads weight."""
    grouped = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r['center_s'], r['start'])):
        key = math.floor(row['paired_temp_c_mean']/width)
        grouped[key].append(row)
    result = []
    for key, members in sorted(grouped.items()):
        ts = [r['paired_temp_c_mean'] for r in members]
        ys = [r['net_mass_g_mean'] for r in members]
        result.append(dict(bin_width_c=width, bin_low_c=key*width,
                           bin_high_c=(key+1)*width, minutes=len(members),
                           temperature_mean_c=statistics.mean(ts),
                           empty_mean_g=statistics.mean(ys),
                           minute_mean_sd_g=statistics.stdev(ys) if len(ys)>1 else None,
                           minute_mean_min_g=min(ys), minute_mean_max_g=max(ys),
                           minute_mean_range_g=max(ys)-min(ys),
                           first=members[0], members=members))
    return result


def line_for(rows, x='paired_temp_c_mean', y='net_mass_g_mean'):
    return fit_line([r[x] for r in rows], [r[y] for r in rows])


def prepare(inputs):
    with (inputs/'空载分钟统计.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for index, row in enumerate(rows, start=2):
        row['source_csv_row'] = index
        for key in ('center_s', 'paired_temp_c_mean', 'net_mass_g_mean'):
            row[key] = float(row[key])
    groups = defaultdict(list)
    audit = []
    for row in rows:
        if not row['special_condition']:
            groups[(row['session'], row['epoch'])].append(row)
    eligible = {}
    for key, members in groups.items():
        temps = [r['paired_temp_c_mean'] for r in members]
        if len(members) >= 5 and max(temps)-min(temps) >= .5:
            eligible[key] = members
    for row in rows:
        row = dict(row)
        row['scope_reason'] = ('原有特殊条件段，不纳入正常零点拟合' if row['special_condition'] else
                               '纳入不同温区探索' if (row['session'], row['epoch']) in eligible else
                               '分钟箱不足5个或窗口均温跨度不足0.5℃，保留于全量报告')
        audit.append(row)
    return eligible, audit


def compute(groups):
    fits, summaries, firsts, repeats, details = [], [], [], [], []
    for (sid, epoch), members in sorted(groups.items()):
        details.append(dict(session=sid, epoch=epoch, full=members, zones={}))
        fit = line_for(members)
        fits.append(dict(session=sid, epoch=epoch, method='全部空载分钟', bin_width_c=None,
                         points=len(members), **fit))
        for width in WIDTHS:
            bins = zones(members, width)
            details[-1]['zones'][str(width)] = bins
            for b in bins:
                record = dict(session=sid, epoch=epoch, **{k:v for k,v in b.items() if k not in ('first','members')})
                summaries.append(record)
                if width == WIDTHS[0]:
                    firsts.append(dict(b['first'], bin_low_c=b['bin_low_c'], bin_high_c=b['bin_high_c'],
                                       selection_reason='该温区按时间最早的合格分钟窗口'))
                    repeats.extend(dict(r, bin_low_c=b['bin_low_c'], bin_high_c=b['bin_high_c'],
                                        selection_reason='相同温区后续窗口，不重复计入首次窗口视图；仍用于温区均值及全量分析')
                                   for r in b['members'][1:])
            average_fit = line_for(bins, 'temperature_mean_c', 'empty_mean_g')
            first_fit = line_for([b['first'] for b in bins])
            for name, model in [('温区均值', average_fit), ('每温区首次窗口', first_fit)]:
                fits.append(dict(session=sid, epoch=epoch, method=name, bin_width_c=width,
                                 points=len(bins), **(model or {})))
    return fits, summaries, firsts, repeats, details


def plots(output, details, loads, plt):
    blue, orange, gray = '#2166A5', '#D97829', '#9EAAB5'
    for mode, filename, title in [
        ('means', '01_不同温区均值与范围.png', '20 kg梁：不同温区的空载变化'),
        ('first', '02_每温区首次窗口对照.png', '20 kg梁：重复温区只计首次窗口的探索结果')]:
        fig, axes = plt.subplots(1, len(details), figsize=(12, 5.6), squeeze=False)
        for ax, group in zip(axes[0], details):
            full = group['full']; bins = group['zones']['0.25']
            ax.scatter([r['paired_temp_c_mean'] for r in full], [r['net_mass_g_mean'] for r in full],
                       color=gray, alpha=.45, s=18, label='全部空载分钟均值')
            if mode == 'means':
                x = [b['temperature_mean_c'] for b in bins]
                y = [b['empty_mean_g'] for b in bins]
                ax.errorbar(x,y, yerr=[[b['empty_mean_g']-b['minute_mean_min_g'] for b in bins],
                                      [b['minute_mean_max_g']-b['empty_mean_g'] for b in bins]],
                            fmt='o', color=blue, capsize=3, ms=5, label='0.25℃温区均值及分钟均值范围')
            else:
                x=[b['first']['paired_temp_c_mean'] for b in bins]
                y=[b['first']['net_mass_g_mean'] for b in bins]
                ax.scatter(x,y, color=blue, s=38, label='每温区最早合格窗口')
            model = fit_line(x,y)
            if model:
                ends=[min(x),max(x)]
                ax.plot(ends,[model['intercept']+model['slope']*v for v in ends], color=orange,
                        label=f"探索拟合：斜率 {model['slope']:+.3f} g/℃；R²={model['r_squared']:.3f}")
            ax.set_title(LABELS.get(group['session'], group['session']),fontsize=13)
            ax.set_xlabel('窗口平均探头温度（℃）');ax.set_ylabel('空载偏移（g，按当时系数换算）')
            ax.legend(fontsize=8,loc='best');ax.grid(alpha=.2)
        fig.suptitle(title,fontsize=16,x=.07,ha='left')
        fig.text(.07,.025,'0.25℃为探索分箱宽度；分会话、分基准处理。灰点始终保留，不按零点大小或拟合残差删除。',fontsize=9)
        fig.tight_layout(rect=(0,.07,1,.91));fig.savefig(output/filename,dpi=165);plt.close(fig)
    chosen=[r for r in loads if r['category']=='同轮加载对照' and r['reference_mass_g']==200]
    chosen.sort(key=lambda r:r['temperature_c'])
    fig,ax=plt.subplots(figsize=(9,5))
    x=[r['temperature_c'] for r in chosen];y=[r['increment_g'] for r in chosen]
    ax.plot(x,y,'o-',color=blue,label='相邻空载扣基线后的200 g加载增量')
    ax.axhline(200,color=gray,linestyle='--',label='标称200 g')
    for i,(a,b) in enumerate(zip(x,y)):
        align='left' if i==0 else 'right' if i==len(x)-1 else 'center'
        ax.annotate(f'{a:.2f}℃ / {b:.3f} g',(a,b),xytext=(0,12),textcoords='offset points',ha=align)
    ax.set_ylim(199.75,200.08);ax.set_xlabel('带载窗口平均探头温度（℃）');ax.set_ylabel('加载增量（g）')
    ax.set_title('不同温度下的200 g响应：同轮供电、相同60秒上限口径',fontsize=13)
    ax.legend(fontsize=9);ax.grid(alpha=.2)
    fig.text(.11,.025,'每温区仅一次加载；连线仅方便阅读。离线扣基线不是已运行的温补，也没有重复测量置信区间。',fontsize=8.5)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(output/'03_不同温度200g响应.png',dpi=165);plt.close(fig)


def report(output, result):
    fits=result['fits']; bins=result['zones']
    lines=['# 20 kg梁不同温区探索分析','',
           '2026年11月25日。按操作者要求另看不同温度之间的变化，重复温区不在首次窗口视图中反复计入。原始资料和全量分析均保留。', '',
           '## 这次怎样处理重复温度','',
           '没有按“零点差得大”删除点。主口径把窗口均温按0.25℃分箱，每会话、每去皮基准分别计算；同一温区用全部分钟窗口的均值表示，并保留最小—最大范围。另做每温区只取时间最早窗口的对照，不依据重量挑点。0.5℃作为分箱敏感性检查，两种宽度全部报告。', '',
           '这是一项事后探索，不是采集前预设的正式验收方案。分箱锚点为0℃，温区左闭右开；窗口均温处于相同区间不代表物理温度完全相同。每个分钟均值在温区内权重相同，每个温区在回归中权重相同。', '',
           '沿用全量分析的异常与换载保护、温度配对、基准分段和分钟覆盖规则；仅对至少5个有效分钟箱且均温跨度至少0.5℃的会话段做温区拟合。只有11月12日冰杯空载降温、11月21日自然降温两段符合这一条件。其余会话继续保留在全量报告及筛选台账，未因结果不好判为无效。', '',
           '## 计算结果','',
           '| 记录 | 处理方式 | 分箱宽度/℃ | 点数 | 表观斜率/(g/℃) | R² |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for r in fits:
        width='—' if r['bin_width_c'] is None else str(r['bin_width_c'])
        lines.append(f"| {LABELS.get(r['session'],r['session'])} | {r['method']} | {width} | {r['points']} | {r.get('slope',float('nan')):+.4f} | {r.get('r_squared',float('nan')):.4f} |")
    lines += ['',
        '11月12日的温度相关趋势在温区汇总后仍存在：0.25℃温区均值斜率约−0.536 g/℃、R²约0.843；0.5℃温区均值的R²约0.910。此差异体现分箱和平滑的影响，不能把较高R²当作补偿精度提高。', '',
        '11月21日自然降温的温度关系仍较弱：0.25℃温区均值R²约0.169；只取每温区首次窗口时R²约0.0006。首次窗口口径改为0.5℃后斜率还会反号，说明估计对窗口选择敏感。仅减少重复温区并没有得到稳定通用的温度关系。', '',
        '两轮不能合并成一条统一的零点曲线：原始装配、日期、换算系数和基准不同。这里分别展示各轮温区变化，不统一平移到相同零点，也不扣估计膜重。', '',
        '## 不同温度的载荷响应','',
        '11月21日同轮200 g，在25.053、23.790、22.429℃的加载增量分别约199.906、199.861、199.838 g。暖端到冷端变化约−0.067 g，小于目前窗口选择与读数波动的影响；各温区只有一次加载，不据此确定灵敏度温度系数。图中为相邻空载插值扣基线，非固件已实现的温度补偿。', '',
        '## 能形成的结论','',
        '当前20 kg数据能够给出单轮空载温度相关曲线、温区汇总表、表观斜率和不同温区载荷偏差。冰杯降温这轮的趋势较清楚，可作为预实验结果；自然降温没有得到同样稳定的关系。尚不能据本次分箱结果宣称已完成温度补偿效果验证，也没有得到可直接用于1 kg梁的参数。', '',
        '本次没有新增补偿前后改善值。全量分析中的跨日500 g补偿迁移MAE 0.659→1.803 g继续保留，其验证数据未随本次首次窗口选择而删减。', '',
        '## 文件与可复核性','',
        '`温区汇总.csv`保留各区均值、分钟均值标准差、范围和窗口数；`每温区首次窗口.csv`与`未重复计入的窗口.csv`逐条对应全量分钟CSV行号。后续重复窗口仍参与温区均值和全量分析。`拟合对照.csv`列出全部处理口径，`窗口筛选台账.csv`说明所有分钟窗口的用途。结果JSON保存规则、来源SHA256和载荷对照。', '',
        '每温区只留一窗的主要作用是检查重复停留时间带来的权重影响，不会证明后来回到同温区时读数应当相同。温区误差棒是已有分钟均值的最小—最大范围，不是重复实验置信区间。', '',
        '后续1 kg梁重新标定后，单独记录标定系数、固件和装配，再做室温稳定性、重复加载以及不同温区实验。20 kg代码已另行归档，历史数据和软件版本不覆盖。']
    text='\n'.join(lines)+'\n';(output/'分析说明.md').write_text(text,encoding='utf-8')
    table=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [LABELS.get(r['session'],r['session']),r['method'],r['bin_width_c'] or '全量',r['points'],f"{r['slope']:+.4f}",f"{r['r_squared']:.4f}"])+'</tr>' for r in fits)
    imgs=''.join(f'<section><h2>{title}</h2><img src="{name}" alt="{title}"></section>' for name,title in [
        ('01_不同温区均值与范围.png','温区汇总：每温区一个均值，保留范围'),
        ('02_每温区首次窗口对照.png','重复温区不反复计入：按最早时间选窗口'),
        ('03_不同温度200g响应.png','不同温度下的200 g加载响应')])
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>20 kg不同温区探索分析</title>
<style>body{{font:16px/1.8 'Microsoft YaHei',sans-serif;background:#f4f6f8;color:#20313e;margin:0}}main{{max-width:1100px;margin:auto;padding:28px 20px}}section{{background:white;border:1px solid #dce3e9;border-radius:8px;padding:24px;margin:22px 0}}h1{{font-size:29px}}h2{{font-size:21px}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid #dce3e9;text-align:left}}a{{color:#2166a5}}</style><main>
<h1>20 kg梁：不同温区探索分析</h1><p>2026年11月25日 · 两份符合温差条件的空载记录 · 事后探索</p>
<section><h2>结果</h2><p>冰杯降温那轮仍有明显相关走势；自然降温那轮减少重复温区后，关系依然较弱。不能靠这一处理得到通用温补参数。</p><p>主图按0.25℃温区取均值，保留区内范围；另取每温区最早窗口做对照。筛选只看温度和时间，不按零点大小挑点。原始及全量分析保留。</p></section>
{imgs}<section><h2>全部口径对照</h2><div style="overflow:auto"><table><tr><th>记录</th><th>方法</th><th>宽度/℃</th><th>点数</th><th>斜率/(g/℃)</th><th>R²</th></tr>{table}</table></div><p>分箱均值与首次窗口均为同批历史数据的不同表示，点数减少或R²升高不等于独立补偿验证。</p></section>
<section><h2>说明与明细</h2><p>温度和时间共同变化；图中范围不是重复实验的置信区间。未修改论文或固件，1 kg梁需另行标定和采集。</p>
<p><a href="分析说明.md">完整分析说明</a> · <a href="温区汇总.csv">温区统计</a> · <a href="拟合对照.csv">拟合对照</a> · <a href="每温区首次窗口.csv">保留窗口</a> · <a href="未重复计入的窗口.csv">重复窗口清单</a> · <a href="窗口筛选台账.csv">全部窗口用途</a> · <a href="结果.json">规则和来源</a></p></section></main></html>'''
    (output/'分析报告.html').write_text(document,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plot-deps',type=Path);args=parser.parse_args()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    original=json.loads((INPUT/'分析结果.json').read_text(encoding='utf-8'))
    assert all(sha(ROOT/k)==v['sha256'] for k,v in original['source_files'].items()),'Original source snapshot changed'
    groups,audit=prepare(INPUT)
    fits,summaries,firsts,repeats,details=compute(groups)
    assert len(firsts)+len(repeats)==sum(len(g) for g in groups.values())
    result=dict(date='2026-11-25',sensor_capacity_kg=20,
                rule='按温度分箱；全区间均值保留范围；首次窗口仅按时间选择。事后探索，无重量阈值。',
                widths_c=WIDTHS,primary_width_c=.25,bin_anchor_c=0,
                input_files={p.relative_to(ROOT).as_posix():sha(p) for p in [INPUT/'空载分钟统计.csv',INPUT/'分析结果.json']},
                original_source_files=original['source_files'],fits=fits,zones=summaries,
                primary_selected_minutes=len(firsts),primary_repeat_minutes=len(repeats),
                loaded_comparison=original['paired_loads'],
                historical_compensation=original['historical_compensation'])
    for filename,rows in [('温区汇总.csv',summaries),('拟合对照.csv',fits),('每温区首次窗口.csv',firsts),
                          ('未重复计入的窗口.csv',repeats),('窗口筛选台账.csv',audit)]:
        write_csv(OUTPUT/filename,rows)
    (OUTPUT/'结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    plots(OUTPUT,details,original['paired_loads'],plotting_setup(args.plot_deps))
    report(OUTPUT,result)
    assert all(sha(ROOT/k)==v['sha256'] for k,v in original['source_files'].items())
    print(json.dumps(dict(sessions=len(groups),retained_minutes=len(firsts),not_repeated_minutes=len(repeats),
                          original_files_unchanged=len(original['source_files']),output=str(OUTPUT)),ensure_ascii=False))


if __name__=='__main__':
    main()
