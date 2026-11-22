"""离线复核连续温度实验：近邻空载配对、分钟均值及描述性温度拟合。"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, stdev

from summarize_calibration import valid


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def window(rows, low, high, label, k):
    picked=[r for r in rows if low <= float(r['elapsed_s']) < high]
    if len(picked)<60:
        return None
    masses=[int(r['net'])/k for r in picked]
    filtered=[float(r['g_avg']) for r in picked]
    return dict(label=label,rows=len(picked),seq_first=picked[0]['seq'],seq_last=picked[-1]['seq'],
                start=picked[0]['received_local'],end=picked[-1]['received_local'],
                center_s=mean(float(r['elapsed_s']) for r in picked),
                raw_mean=mean(int(r['raw']) for r in picked),
                net_mass_mean_g=mean(masses),net_mass_sd_g=stdev(masses),
                g_avg_mean_g=mean(filtered),g_avg_sd_g=stdev(filtered),
                temp_mean_c=mean(float(r['latest_temp_c']) for r in picked),
                temp_min_c=min(float(r['latest_temp_c']) for r in picked),
                temp_max_c=max(float(r['latest_temp_c']) for r in picked))


def load_session(folder,k):
    records=read_csv(folder/'records.csv')
    metadata=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if metadata.get('status')=='running':
        raise ValueError('此分析只处理已结束的会话，不停止正在运行的采集。')
    weights=[r for r in records if valid(r) and r.get('net')]
    events=read_csv(folder/'events.csv')
    bases={int(r['raw'])-int(r['net']) for r in weights}
    if (len(bases)!=1 or any(r['record_type']=='tare' for r in records)
            or any(e['event_type'] in ('tare','reset') for e in events)):
        raise ValueError('会话有去皮、复位或零点基准变化，需先分段，不能跨基准配对。')
    bad=[e for e in events if e['event_type']=='load' and float(e['reference_mass_g'])>500]
    markers=[dict(e) for e in events if e['event_type'] in ('load','unload') and e not in bad]
    for i,e in enumerate(markers):
        marked=float(e['elapsed_s'])
        transition=marked
        if i:
            low=max(float(markers[i-1]['elapsed_s'])+5,marked-120)
            mass=float(e['reference_mass_g'] or 0)
            consecutive=[]
            for row in weights:
                tick=float(row['elapsed_s'])
                if not low<=tick<=marked+10:continue
                if abs(float(row['g'])-mass)<=max(5,mass*.05):
                    consecutive.append(tick)
                    if len(consecutive)>=10:
                        transition=consecutive[0];break
                else:
                    consecutive=[]
        e['transition_s']=transition
    last=float(weights[-1]['elapsed_s'])
    stages=[]
    for i,e in enumerate(markers):
        low=e['transition_s']+10
        high=markers[i+1]['transition_s']-3 if i+1<len(markers) else last
        stages.append(dict(event_id=e['event_id'],kind=e['event_type'],
                           mass_g=float(e['reference_mass_g'] or 0),
                           low=low,high=high,marked_local=e['marked_local'],
                           transition_s=e['transition_s']))
    pairs=[]
    for i,s in enumerate(stages):
        if s['kind']!='load' or not 0<i<len(stages)-1:continue
        previous,following=stages[i-1],stages[i+1]
        if previous['kind']!='unload' or following['kind']!='unload':continue
        for seconds in (30,60):
            before=window(weights,max(previous['low'],previous['high']-seconds),previous['high'],'加载前近邻空载',k)
            loaded=window(weights,max(s['low'],s['high']-seconds),s['high'],'带载末段',k)
            after=window(weights,following['low'],min(following['high'],following['low']+seconds),'卸载后近邻空载',k)
            if not all((before,loaded,after)):continue
            f=(loaded['center_s']-before['center_s'])/(after['center_s']-before['center_s'])
            if not 0<=f<=1:raise ValueError('空载窗口未包围带载窗口')
            zero=before['raw_mean']+f*(after['raw_mean']-before['raw_mean'])
            pairs.append(dict(session=folder.name,event_id=s['event_id'],mass_g=s['mass_g'],
                              requested_window_s=seconds,before=before,loaded=loaded,after=after,
                              zero_raw_interpolated=zero,
                              increment_g=(loaded['raw_mean']-zero)/k,
                              increment_before_only_g=(loaded['raw_mean']-before['raw_mean'])/k,
                              increment_after_only_g=(loaded['raw_mean']-after['raw_mean'])/k,
                              error_g=(loaded['raw_mean']-zero)/k-s['mass_g'],
                              return_shift_g=(after['raw_mean']-before['raw_mean'])/k))
    minutes=[]
    for s in stages:
        if s['kind']!='unload':continue
        for minute in range(math.ceil(s['low']/60),math.floor(s['high']/60)):
            item=window(weights,minute*60,(minute+1)*60,'空载整分钟',k)
            if item and item['rows']>=200:
                item['minute']=minute
                item['event_id']=s['event_id']
                minutes.append(item)
    gaps=[float(b['elapsed_s'])-float(a['elapsed_s']) for a,b in zip(records,records[1:])]
    return dict(folder=folder,metadata=metadata,weights=weights,records=records,stages=stages,
                pairs=pairs,minutes=minutes,bad_events=bad,
                tare_bases=sorted({int(r['raw'])-int(r['net']) for r in weights}),
                max_receive_gap_s=max(gaps))


def fit_line(x,y):
    xm,ym=mean(x),mean(y)
    denominator=sum((v-xm)**2 for v in x)
    if not denominator:return None
    slope=sum((a-xm)*(b-ym) for a,b in zip(x,y))/denominator
    intercept=ym-slope*xm
    residuals=[b-(intercept+slope*a) for a,b in zip(x,y)]
    total=sum((b-ym)**2 for b in y)
    return dict(n=len(x),slope=slope,intercept=intercept,
                r_squared=1-sum(e*e for e in residuals)/total if total else None,
                residual_rmse_g=math.sqrt(mean(e*e for e in residuals)),
                note='本轮分钟均值的描述性拟合；不是独立补偿验证，也不证明温度单独导致变化')


def write_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,keys);writer.writeheader();writer.writerows(rows)


def analyze(source,output,reference=None,k=178.20,plot=False):
    source,output=source.resolve(),output.resolve()
    for folder in (source,reference):
        if folder and (folder.resolve()==output or folder.resolve() in output.parents):
            raise ValueError('分析输出不能位于原始数据目录内')
    sources=[load_session(source,k)]
    if reference:sources.insert(0,load_session(reference.resolve(),k))
    current=sources[-1]
    output.mkdir(parents=True,exist_ok=True)
    mins=current['minutes']
    x=[m['temp_mean_c'] for m in mins]
    y=[m['net_mass_mean_g'] for m in mins]
    zero_fit=fit_line(x,y)
    time_fit=fit_line([m['center_s']/3600 for m in mins],y)
    pairs=[p for s in sources for p in s['pairs']]
    short=[]
    for p in pairs:
        short.append(dict(session=p['session'],event_id=p['event_id'],mass_g=p['mass_g'],
                          window_s=p['requested_window_s'],
                          temp_c=p['loaded']['temp_mean_c'],display_mean_g=p['loaded']['g_avg_mean_g'],
                          before_empty_g=p['before']['net_mass_mean_g'],
                          after_empty_g=p['after']['net_mass_mean_g'],increment_g=p['increment_g'],
                          error_g=p['error_g'],return_shift_g=p['return_shift_g'],
                          before_only_g=p['increment_before_only_g'],after_only_g=p['increment_after_only_g']))
    stats=current['metadata'].get('summary')
    first_empty=current['stages'][0]
    last_empty=current['stages'][-1]
    initial=window(current['weights'],first_empty['low'],min(first_empty['high'],first_empty['low']+60),'开始空载60秒',k)
    final=window(current['weights'],max(last_empty['low'],last_empty['high']-60),last_empty['high'],'结束空载60秒',k)
    hashes=[dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest())
            for s in sources for f in (s['folder']/'records.csv',s['folder']/'events.csv',s['folder']/'session.json')]
    result=dict(source=source.name,created_local=datetime.now().astimezone().isoformat(),
                common_counts_per_g=k,summary=stats,tare_bases=current['tare_bases'],
                analysis_eligible_weight_rows=len(current['weights']),
                max_receive_gap_s=current['max_receive_gap_s'],
                flagged_events=current['bad_events'],
                flagged_rule='超过500g的载荷标记单独列为异常输入，不用于配对；原记录不改动',
                window_rule='宽阈值连续10点定位换载；动作后跳过10秒，下一换载前留3秒；带载末30/60秒，紧邻加载前末30/60秒及卸载后首30/60秒；原始计数空载插值后除以178.20',
                initial_empty=initial,final_empty=final,
                empty_endpoint_change_g=final['net_mass_mean_g']-initial['net_mass_mean_g'],
                minute_zero_temp_fit=zero_fit,minute_zero_time_fit=time_fit,
                same_temperature_example=[m for m in mins if m['minute'] in (40,70)],
                minute_temp_range_c=[min(x),max(x)],minute_zero_range_g=[min(y),max(y)],
                paired_loads=pairs,source_hashes=hashes,
                interpretation='同轮温度、时间、加载历史共同变化；没有独立补偿验证，不将此描述性拟合写入固件。近邻空载插值是离线比较口径，不是已部署的温度补偿算法。')
    (output/'连续降温分析.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(output/'载荷近邻空载对照.csv',short)
    write_csv(output/'空载分钟均值.csv',mins)
    if plot:make_plots(current,short,output)
    print(json.dumps({key:result[key] for key in ('summary','tare_bases','initial_empty','final_empty',
                     'empty_endpoint_change_g','minute_zero_temp_fit','minute_zero_time_fit','minute_zero_range_g')},ensure_ascii=True))
    print(json.dumps(short,ensure_ascii=True))
    return result


def make_plots(session,pairs,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10})
    fig,axes=plt.subplots(3,1,figsize=(11,9),constrained_layout=True)
    weights=session['weights']
    axes[0].plot([float(r['elapsed_s'])/60 for r in weights[::5]],
                 [float(r['latest_temp_c']) for r in weights[::5]],color='#166a9d',lw=1)
    axes[0].set(ylabel='梁温（℃）',title='11月21日连续通电记录：温度、空载变化与200 g加载对照')
    for s in session['stages']:
        a,b=s['low'],s['high']
        if s['kind']=='unload':
            data=[r for r in weights if a<=float(r['elapsed_s'])<b]
            axes[1].plot([float(r['elapsed_s'])/60 for r in data[::5]],
                         [float(r['g_avg']) for r in data[::5]],color='#85b4cf',lw=.6)
        else:
            for ax in axes[:2]:ax.axvspan(a/60,b/60,color='#d59536',alpha=.2)
    mins=session['minutes']
    for number,s in enumerate(stage for stage in session['stages'] if stage['kind']=='unload'):
        part=[m for m in mins if m['event_id']==s['event_id']]
        axes[1].plot([m['center_s']/60 for m in part],[m['net_mass_mean_g'] for m in part],
                     color='#153f57',lw=1.2,
                     label='空载整分钟均值（原始net÷178.20）' if number==0 else None)
    axes[1].axhline(0,color='gray',lw=.7,ls='--')
    axes[1].set(ylabel='空载示值（g）',xlabel='接续采集经过时间（分钟）')
    axes[1].legend(loc='best')
    for ax in axes[:2]:
        ax.grid(alpha=.2)
        ax.set_xlim(0,120)
    selected=[p for p in pairs if p['mass_g']==200 and p['window_s']==60]
    axes[2].scatter([p['temp_c'] for p in selected],[p['increment_g'] for p in selected],
                    color='#166a9d',s=45)
    for p in selected:
        axes[2].annotate(f"{p['increment_g']:.3f} g",(p['temp_c'],p['increment_g']),xytext=(6,7),textcoords='offset points')
    axes[2].axhline(200,color='gray',ls='--',lw=1,label='标称200 g')
    axes[2].set(xlabel='带载窗口平均梁温（℃）',ylabel='加载增量（g）',
                title='同轮200 g对照（含较暖参考段，60秒近邻空载窗口）')
    axes[2].ticklabel_format(axis='y',style='plain',useOffset=False)
    axes[2].margins(x=.15,y=.3)
    axes[2].grid(alpha=.2);axes[2].legend(loc='best')
    fig.savefig(output/'连续降温与200g对照.png',dpi=180)
    fig.savefig(output/'连续降温与200g对照.pdf')
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--plot',action='store_true')
    args=parser.parse_args()
    analyze(args.source,args.output,args.reference,plot=args.plot)
