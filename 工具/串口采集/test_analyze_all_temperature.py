"""Synthetic unit cases live only in a temporary folder, never experiment data."""
import csv
from pathlib import Path
import tempfile
import unittest

from analyze_all_temperature import fit_line, parse_session


class TemperatureAuditTests(unittest.TestCase):
    def session(self, lines, status='completed'):
        temporary = tempfile.TemporaryDirectory(prefix='scale_audit_test_')
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        path = folder/'records.csv'
        with path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, ['received_local', 'elapsed_s', 'line', 'record_type', 'line_complete'])
            writer.writeheader()
            for seconds, text, kind, complete in lines:
                writer.writerow(dict(received_local=f'2026-11-21T00:00:{seconds:06.3f}+08:00',
                                     elapsed_s=seconds, line=text, record_type=kind, line_complete=complete))
        spec = dict(id='unit_case', folder=folder, csv=path, legacy=False,
                    metadata={'label': 'unit test', 'status': status,
                              'started_local': '2026-11-21T00:00:00+08:00'})
        return parse_session(spec)

    def test_forward_pair_never_uses_future_temperature(self):
        session = self.session([(0.1, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1),
                                (0.2, 'temp_c=25.00', 'temperature', 1),
                                (0.4, 'raw=32002 net=2 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertIsNone(session['weights'][0]['paired_temp_c'])
        self.assertEqual(session['weights'][1]['paired_temp_c'], 25)
        self.assertAlmostEqual(session['weights'][1]['temp_age_s'], .2)

    def test_error_invalidates_cached_temperature(self):
        session = self.session([(0.1, 'temp_c=25.00', 'temperature', 1),
                                (0.2, 'temp_error=read_or_crc', 'temperature_error', 1),
                                (0.3, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertIsNone(session['weights'][0]['paired_temp_c'])

    def test_temperature_age_limit(self):
        session = self.session([(0.1, 'temp_c=25.00', 'temperature', 1),
                                (2.101, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertIsNone(session['weights'][0]['paired_temp_c'])

    def test_tare_and_reset_split_zero_epoch(self):
        session = self.session([(0.1, 'temp_c=25.00', 'temperature', 1),
                                (0.2, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1),
                                (0.3, 'tare_button_offset=32010', 'tare', 1),
                                (0.4, 'raw=32010 net=0 g=0.0 g_avg=0.0', 'weight', 1),
                                (0.5, 'USART1 OK, 115200 8N1', 'message', 1),
                                (0.6, 'raw=32011 net=1 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertEqual([r['epoch'] for r in session['weights']], [0, 1, 2])
        self.assertIsNone(session['weights'][-1]['paired_temp_c'])

    def test_saturated_and_partial_rows_do_not_become_valid_weights(self):
        session = self.session([(0.1, 'temp_c=25.00', 'temperature', 1),
                                (0.2, 'raw=8388607 net=8388607 g=999 g_avg=999', 'weight', 1),
                                (0.3, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 0),
                                (0.4, 'raw=0 net=0 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertEqual(len(session['weights']), 1)
        self.assertEqual(session['weights'][0]['raw'], 0)

    def test_85_degree_startup_value_flagged_not_fitted(self):
        session = self.session([(0.1, 'temp_c=85.00', 'temperature', 1),
                                (0.2, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertEqual(session['temps'], [])
        self.assertIsNone(session['weights'][0]['paired_temp_c'])

    def test_original_elapsed_clock_is_preserved(self):
        session = self.session([(0.7, 'temp_c=25.00', 'temperature', 1),
                                (0.8, 'raw=32001 net=1 g=0.0 g_avg=0.0', 'weight', 1)])
        self.assertEqual(session['weights'][0]['elapsed_s'], .8)

    def test_stale_running_metadata_is_not_rewritten(self):
        session = self.session([(0.1, 'temp_c=25.00', 'temperature', 1)], status='running')
        self.assertEqual(session['metadata']['status'], 'running')

    def test_linear_fit_and_constant_input(self):
        model = fit_line([1, 2, 3], [5, 7, 9])
        self.assertAlmostEqual(model['slope'], 2)
        self.assertAlmostEqual(model['intercept'], 3)
        self.assertAlmostEqual(model['r_squared'], 1)
        self.assertIsNone(fit_line([1, 1, 1], [2, 3, 4]))


if __name__ == '__main__':
    unittest.main()
