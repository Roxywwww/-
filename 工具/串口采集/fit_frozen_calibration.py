"""Fit 200/500 g from time-frozen raw windows; reserve other masses for checks."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def compare_windows(windows):
    comparisons=[]
    for i,w in enumerate(windows):
        mass=float(w['mass_g'])
        if mass<=0 or i==0 or i+1==len(windows):
            continue
        before,after=windows[i-1],windows[i+1]
        if float(before['mass_g'])!=0 or float(after['mass_g'])!=0:
            continue
        t0,t1,t2=[r['time_center_s'] for r in (before,w,after)]
        if not t0<t1<t2:raise ValueError('Window centers must be chronological')
        if len({r['session_id'] for r in (before,w,after)})!=1:
            raise ValueError('Cannot interpolate across sessions')
        fraction=(t1-t0)/(t2-t0)
        zero=before['raw_mean']+fraction*(after['raw_mean']-before['raw_mean'])
        delta=w['raw_mean']-zero
        comparisons.append(dict(tag=w['tag'],mass_g=mass,role=w['role'],
                                average_temperature_c=w['average_temperature_c'],
                                before_tag=before['tag'],after_tag=after['tag'],
                                baseline_raw_interpolated=zero,delta_raw=delta,
                                local_counts_per_g=delta/mass,raw_sd_counts=w['raw_sd']))
    return comparisons


def fit_coefficient(comparisons):
    fitted=[r for r in comparisons if r['mass_g'] in (200.,500.) and r['role']=='标定']
    if sorted(r['mass_g'] for r in fitted)!=[200.,500.]:
        raise ValueError('Exactly one completed 200 g and 500 g calibration pair required')
    k=sum(r['mass_g']*r['delta_raw'] for r in fitted)/sum(r['mass_g']**2 for r in fitted)
    if k<=0:raise ValueError('Non-positive response; inspect polarity before firmware change')
    return k,fitted


def add_mass_results(comparisons,k):
    return [dict(r,mass_fitted_k_g=r['delta_raw']/k,error_fitted_k_g=r['delta_raw']/k-r['mass_g'],
                 raw_sd_g=r['raw_sd_counts']/k) for r in comparisons]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('windows',type=Path);p.add_argument('--freeze',action='store_true')
    args=p.parse_args();path=args.windows.resolve();out=path.parent
    data=json.loads(path.read_text(encoding='utf-8'))
    comparisons=compare_windows(data['windows'])
    frozen_path=out/'calibration_frozen_200_500.json'
    if args.freeze:
        if frozen_path.exists():raise ValueError('Frozen calibration already exists; will not overwrite')
        if any(r['mass_g']>0 and r['mass_g'] not in (200.,500.) for r in data['windows']):
            raise ValueError('Freeze must occur before collecting independent validation loads')
        k,fitted=fit_coefficient(comparisons)
        scaled=round(k*10000)
        frozen=dict(session_id=data['session_id'],sensor_capacity_kg=data['sensor_capacity_kg'],
                    candidate_counts_per_g=k,firmware_counts_per_g_x10000=scaled,
                    firmware_counts_per_g=scaled/10000.,calibration_comparisons=fitted,
                    rule='200/500 g前后空载按时间插值，原始计数增量对标称质量过原点最小二乘；20/50/100 g不参与',
                    frozen_windows=data['windows'],source_windows_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        frozen_path.write_text(json.dumps(frozen,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    frozen=json.loads(frozen_path.read_text(encoding='utf-8'))
    if frozen['session_id']!=data['session_id']:raise ValueError('Calibration belongs to a different session')
    results=add_mass_results(comparisons,frozen['firmware_counts_per_g'])
    result=dict(session_id=data['session_id'],sensor_capacity_kg=data['sensor_capacity_kg'],
                counts_per_g=frozen['firmware_counts_per_g'],
                coefficient_frozen_before_validation=True,comparisons=results,
                zero_return_counts=[dict(before=data['windows'][i-2]['tag'],after=w['tag'],
                                         delta_raw=w['raw_mean']-data['windows'][i-2]['raw_mean'],
                                         delta_g=(w['raw_mean']-data['windows'][i-2]['raw_mean'])/frozen['firmware_counts_per_g'])
                                    for i,w in enumerate(data['windows']) if i>=2 and w['mass_g']==0 and data['windows'][i-2]['mass_g']==0],
                warning='相邻空载扣基线的离线加载增量，不等于固定开机零点下的在线显示准确度；质量以标称砝码为参考')
    (out/'冻结系数下的标定与核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name, rows in [('加载增量与独立核验.csv',results),('空载回零变化.csv',result['zero_return_counts'])]:
        with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
            if rows:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
