"""标定复算使用合成输入与临时目录，不写入实验记录。"""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

from summarize_calibration import summarize


class CalibrationTests(unittest.TestCase):
    def test_delayed_markers_and_interpolated_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            session=Path(tmp)/'SIMULATED'
            session.mkdir()
            events=[(1,'unload',0), (55,'load',200), (110,'unload',0),
                    (165,'load',500), (220,'unload',0),
                    (275,'load',100), (330,'unload',0)]
            with (session/'events.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,['event_id','elapsed_s','event_type',
                                           'reference_mass_g','marked_local','note'])
                writer.writeheader()
                for number,(tick,kind,mass) in enumerate(events,1):
                    writer.writerow(dict(event_id=number,elapsed_s=tick,event_type=kind,
                                         reference_mass_g=mass,marked_local='TEST ONLY',note=''))
            data=[]
            for seq in range(1800):
                t=seq/5
                mass=200 if 45<=t<100 else 500 if 155<=t<210 else 100 if 265<=t<320 else 0
                raw=30000+0.2*t+180*mass
                data.append(dict(seq=seq,elapsed_s=t,record_type='weight',line_complete=1,
                                 temp_state='ok',temp_age_s=0.2,latest_temp_c=20,
                                 raw=round(raw),g=(raw-30000)/178.2,
                                 g_avg=(raw-30000)/178.2))
            with (session/'records.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,list(data[0]))
                writer.writeheader()
                writer.writerows(data)
            (session/'session.json').write_text(json.dumps({'status':'completed'}))
            before=(session/'records.csv').read_bytes()
            with redirect_stdout(io.StringIO()):
                result=summarize(session,Path(tmp)/'analysis')
            self.assertEqual((session/'records.csv').read_bytes(),before)
            self.assertEqual(result['stages'][1]['transition_elapsed_s'],45)
            self.assertAlmostEqual(result['candidate_counts_per_g'],180,places=3)
            point=next(x for x in result['comparisons'] if x['mass_g']==100)
            self.assertLess(abs(point['error_candidate_k_g']),0.01)
            self.assertEqual(point['zero_method'],'前后空载均值按时间线性插值')
            # 冻结后即使后续复算的拟合输入不同，也不能偷改验证使用的系数。
            frozen=Path(tmp)/'analysis/calibration_frozen_200_500.json'
            frozen.write_text(json.dumps(result),encoding='utf-8')
            for row in data:
                if 45<=float(row['elapsed_s'])<100:
                    row['raw']+=1000
            with (session/'records.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,list(data[0]))
                writer.writeheader()
                writer.writerows(data)
            with redirect_stdout(io.StringIO()):
                locked=summarize(session,Path(tmp)/'analysis')
            self.assertEqual(locked['candidate_counts_per_g'],result['candidate_counts_per_g'])
            self.assertEqual(locked['comparisons'][:2],result['comparisons'][:2])
            with self.assertRaises(ValueError):
                summarize(session,session/'analysis')


if __name__=='__main__':
    unittest.main()
