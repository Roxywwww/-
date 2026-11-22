"""人工构造的线性零点漂移，验证近邻空载配对不会使用远期空载。"""
import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import analyze_temperature_run as analysis


class ContinuousAnalysisTests(unittest.TestCase):
    def fixture(self,folder):
        folder.mkdir()
        rows=[]
        for t in range(1201):
            mass=200 if 150<=t<250 else 0
            zero=t if t<=400 else 400+10*(t-400)
            raw=33022+zero+round(mass*178.2)
            rows.append(dict(seq=t+1,elapsed_s=t,record_type='weight',line_complete=1,
                             raw=raw,net=raw-33022,g=(raw-33022)/178.2,
                             g_avg=(raw-33022)/178.2,latest_temp_c=20+t*.001,
                             temp_state='ok',temp_age_s=0,
                             received_local=f'TEST_ONLY_t={t}'))
        with (folder/'records.csv').open('w',encoding='utf-8',newline='') as file:
            writer=csv.DictWriter(file,list(rows[0]));writer.writeheader();writer.writerows(rows)
        events=[dict(event_id=i,event_type=kind,reference_mass_g=mass,elapsed_s=t,
                     marked_local=f'TEST_ONLY_t={t}')
                for i,kind,mass,t in [(1,'unload',0,0),(2,'load',200,150),(3,'unload',0,250)]]
        with (folder/'events.csv').open('w',encoding='utf-8',newline='') as file:
            writer=csv.DictWriter(file,list(events[0]));writer.writeheader();writer.writerows(events)
        (folder/'session.json').write_text(json.dumps({'status':'stopped','summary':{}}),encoding='utf-8')

    def test_local_zero_recovers_known_mass_despite_far_later_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'TEST_ONLY';self.fixture(source)
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            result=analysis.load_session(source,178.2)
            pair=next(p for p in result['pairs'] if p['requested_window_s']==60)
            self.assertAlmostEqual(pair['increment_g'],200,places=10)
            self.assertLess(pair['after']['center_s'],330)
            self.assertEqual(hashes,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()})

    def test_running_source_is_not_stopped_or_analyzed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'TEST_ONLY';self.fixture(source)
            (source/'session.json').write_text('{"status":"running"}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'已结束'):
                analysis.load_session(source,178.2)


if __name__=='__main__':
    unittest.main()
