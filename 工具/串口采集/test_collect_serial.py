"""全部使用临时目录和模拟输入，不向实验数据目录写测试数据。"""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import serial
import collect_serial as capture


def rows(folder):
    with (folder / 'records.csv').open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


class CaptureTests(unittest.TestCase):
    def test_fragmented_input_and_bounded_memory(self):
        b = capture.LineBuffer()
        self.assertEqual(list(b.feed(b'raw=12\r')), [])
        self.assertEqual(list(b.feed(b'\ntemp_c=20.00\nraw=')),
                         [(b'raw=12\r\n', True), (b'temp_c=20.00\n', True)])
        self.assertEqual(b.finish(), b'raw=')
        self.assertEqual(list(b.feed(b'x' * 8193)), [(b'x' * 8192, False)])
        self.assertEqual(b.finish(), b'x')

    def test_temperature_age_errors_and_raw_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = capture.SessionLog(tmp, {'label': 'TEST ONLY'})
            fixture = (b'raw=10 net=-2 g=-0.1 g_avg=0.0 g_iir=-0.1\r\n'
                       b'temp_c=21.25\r\ntemp_error=no_presence\r\nraw=9\r\n'
                       b'tare_button_offset=9\r\n\xff')
            log.chunk(fixture)
            b = capture.LineBuffer()
            for data, complete in b.feed(fixture):
                log.line(data, complete)
            log.line(b.finish(), False)
            log.close('stopped', 'TEST ONLY')
            r = rows(log.path)
            self.assertEqual((log.path / 'received.bin').read_bytes(), fixture)
            self.assertEqual(r[0]['latest_temp_c'], '')
            self.assertEqual(r[0]['net'], '-2')
            self.assertEqual(r[0]['g_iir'], '-0.1')
            self.assertEqual(r[3]['g_iir'], '')
            self.assertEqual(r[3]['latest_temp_c'], '21.25')
            self.assertEqual(r[3]['temp_state'], 'error')
            self.assertEqual(r[3]['latest_temp_seq'], '2')
            self.assertGreaterEqual(float(r[3]['temp_age_s']), 0)
            self.assertEqual(r[4]['record_type'], 'tare')
            self.assertEqual(r[5]['record_type'], 'partial')
            self.assertEqual(r[5]['original_line'], r'\xff')
            self.assertRegex(r[0]['received_local'], r'\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$')
            self.assertEqual(json.loads((log.path/'session.json').read_text(encoding='utf-8'))['records'], 6)

    def test_event_commands_aliases_and_load_mass(self):
        self.assertEqual(
            capture.parse_event_command('c cold 放入密封冰杯'),
            {'event_type': 'cold_add', 'reference_mass_g': '',
             'note': '放入密封冰杯'})
        self.assertEqual(
            capture.parse_event_command('c 放载荷 500 中心位置'),
            {'event_type': 'load', 'reference_mass_g': '500',
             'note': '中心位置'})
        self.assertEqual(
            capture.parse_event_command('c stable'),
            {'event_type': 'stable_start', 'reference_mass_g': '', 'note': ''})
        self.assertEqual(capture.parse_event_command('h'), 'help')
        with self.assertRaises(ValueError):
            capture.parse_event_command('c load 中心位置')
        with self.assertRaises(ValueError):
            capture.parse_event_command('c unknown')

    def test_events_health_warnings_and_end_summary(self):
        fixture = (b'temp_c=20.00\r\n'
                   b'raw=100 net=10 g=0.1 g_avg=0.1\r\n'
                   b'temp_error=read_or_crc\r\n'
                   b'raw=101 net=11 g=0.1 g_avg=0.1\r\n'
                   b'temp_c=21.00\r\n')
        with tempfile.TemporaryDirectory() as tmp:
            log = capture.SessionLog(tmp, {
                'label': 'TEST ONLY',
                'experiment': {
                    'experiment_type': '空载测试（模拟）',
                    'assembly_version': 'TEST-BOARD',
                    'user_metadata': {'fixture': 'simulated'},
                },
            })
            for data, complete in capture.LineBuffer().feed(fixture):
                log.line(data, complete)
            log.record_event('cold_add', note='TEST ONLY', source='console')
            log.record_event('data_gap', note='TEST ONLY', source='capture')
            log.close('completed', 'TEST ONLY')

            with (log.path / 'events.csv').open(
                    encoding='utf-8-sig', newline='') as f:
                event_rows = list(csv.DictReader(f))
            self.assertEqual(len(event_rows), 2)
            self.assertEqual(event_rows[0]['event_type'], 'cold_add')
            self.assertEqual(event_rows[0]['latest_seq'], '5')
            self.assertEqual(list(event_rows[0]), capture.EVENT_FIELDS)

            summary = json.loads(
                (log.path / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['weight_valid_rows'], 2)
            self.assertEqual(summary['temperature_valid_rows'], 2)
            self.assertEqual(summary['temperature_min_c'], 20.0)
            self.assertEqual(summary['temperature_max_c'], 21.0)
            self.assertEqual(summary['temperature_error_rows'], 1)
            self.assertEqual(summary['temperature_error_episodes'], 1)
            self.assertEqual(summary['data_gap_events'], 1)
            self.assertTrue((log.path / 'summary.md').exists())
            self.assertEqual(list(rows(log.path)[0]), capture.FIELDS)

            session = json.loads(
                (log.path / 'session.json').read_text(encoding='utf-8'))
            self.assertEqual(
                session['experiment']['experiment_type'],
                '空载测试（模拟）')
            self.assertEqual(
                session['experiment']['user_metadata']['fixture'],
                'simulated')

            log.temp = (
                '20.00', log.temp[1], log.temp[2],
                capture.time.monotonic() - 10)
            log.temp_state = 'ok'
            self.assertEqual(
                log.health_warning_key(5), 'stale_temperature')
            self.assertIn('超过5秒阈值', log.health_warnings(5)[0])

    def test_real_pyserial_loopback_transport(self):
        fixture = b'temp_c=-1.25\r\nraw=123 net=1 g=0.1 g_avg=0.1\r\n'
        with serial.serial_for_url('loop://', timeout=1) as port:
            port.write(fixture)  # 仅测试内存回环，不打开实际设备。
            received = port.read(len(fixture))
        self.assertEqual(received, fixture)
        with tempfile.TemporaryDirectory() as tmp:
            log = capture.SessionLog(tmp, {'label': 'TEST ONLY loopback'})
            log.chunk(received)
            for data, complete in capture.LineBuffer().feed(received):
                log.line(data, complete)
            log.close('completed', 'TEST ONLY')
            self.assertEqual(rows(log.path)[1]['latest_temp_c'], '-1.25')

    def test_disconnect_retains_partial_and_closes_port(self):
        fixture = b'temp_c=20.0\nraw=123\nraw=45'

        class FakeSerial:
            def __init__(self, **kwargs):
                self.pending = bytearray(fixture)
                self.closed = False
            def open(self):
                pass
            def close(self):
                self.closed = True
            @property
            def in_waiting(self):
                return 0
            def read(self, size):
                if not self.pending:
                    raise serial.SerialException('TEST disconnect')
                data = bytes(self.pending[:size])
                del self.pending[:size]
                return data

        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeSerial()
            with patch('serial.Serial', return_value=fake), patch('serial.tools.list_ports.comports', return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = capture.main(['--port', 'COM_TEST', '--output', tmp])
            session = next(Path(tmp).iterdir())
            self.assertEqual(result, 1)
            self.assertTrue(fake.closed)
            self.assertEqual((session/'received.bin').read_bytes(), fixture)
            self.assertEqual(rows(session)[-1]['line_complete'], '0')
            self.assertEqual(json.loads((session/'session.json').read_text(encoding='utf-8'))['status'], 'error')

    def test_unique_session_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = capture.SessionLog(tmp, {})
            a.close('completed', 'TEST ONLY')
            b = capture.SessionLog(tmp, {})
            b.close('completed', 'TEST ONLY')
            self.assertNotEqual(a.path, b.path)

    def test_metadata_replace_failure_keeps_raw_capture_running(self):
        fixture = b'temp_c=20.00\r\nraw=123 net=1 g=0.1 g_avg=0.1\r\n'
        with tempfile.TemporaryDirectory() as tmp:
            log = capture.SessionLog(tmp, {'label': 'TEST ONLY'})
            with patch.object(capture.Path, 'replace',
                              side_effect=PermissionError('TEST metadata lock')):
                self.assertFalse(log.checkpoint(durable=True))
            self.assertEqual(log.metadata_write_failure_count, 1)
            self.assertTrue(log.metadata_warning_active)
            self.assertTrue((log.path / 'session.pending').exists())
            log.chunk(fixture)
            for data, complete in capture.LineBuffer().feed(fixture):
                log.line(data, complete)
            self.assertEqual(len(rows(log.path)), 2)
            self.assertTrue(log.checkpoint(durable=True))
            self.assertFalse(log.metadata_warning_active)
            log.close('completed', 'TEST ONLY')
            self.assertEqual(
                json.loads((log.path / 'session.json').read_text(encoding='utf-8'))['status'],
                'completed')

    def test_cli_session_information_and_explicit_blanks(self):
        class IdleSerial:
            def __init__(self, **kwargs):
                pass
            def open(self):
                pass
            def close(self):
                pass
            def read(self, size):
                capture.time.sleep(0.002)
                return b''

        with tempfile.TemporaryDirectory() as tmp:
            with patch('serial.Serial', return_value=IdleSerial()), \
                    patch('serial.tools.list_ports.comports', return_value=[]), \
                    redirect_stdout(io.StringIO()):
                result = capture.main([
                    '--port', 'COM_TEST', '--seconds', '0.01',
                    '--output', tmp, '--no-events',
                    '--experiment-type', 'CLI TEST ONLY',
                    '--assembly-version', 'TEST-V2',
                    '--meta', 'fixture=simulated',
                ])
            folder = next(Path(tmp).iterdir())
            meta = json.loads(
                (folder / 'session.json').read_text(encoding='utf-8'))
            self.assertEqual(result, 0)
            self.assertEqual(
                meta['experiment']['experiment_type'], 'CLI TEST ONLY')
            self.assertEqual(
                meta['experiment']['assembly_version'], 'TEST-V2')
            self.assertEqual(
                meta['experiment']['firmware_version'], '')
            self.assertEqual(
                meta['experiment']['sensor_ids'], '')
            self.assertEqual(
                meta['experiment']['user_metadata']['fixture'], 'simulated')

    def test_disk_error_reports_and_closes_port(self):
        class IdleSerial:
            def __init__(self, **kwargs):
                self.closed = False
            def open(self):
                pass
            def close(self):
                self.closed = True
            def read(self, size):
                return b''

        port = IdleSerial()
        with patch('serial.Serial', return_value=port), \
                patch('serial.tools.list_ports.comports', return_value=[]), \
                patch.object(capture, 'SessionLog',
                             side_effect=OSError('TEST disk failure')), \
                redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()):
            result = capture.main([
                '--port', 'COM_TEST', '--seconds', '1',
                '--output', tempfile.gettempdir(), '--no-events',
            ])
        self.assertEqual(result, 1)
        self.assertTrue(port.closed)

    def test_duration_and_ctrl_c_finish_session(self):
        for stop in ('duration', 'keyboard'):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as tmp:
                class IdleSerial:
                    def __init__(self, **kwargs):
                        self.closed = False
                    def open(self):
                        pass
                    def close(self):
                        self.closed = True
                    def read(self, size):
                        if stop == 'keyboard':
                            raise KeyboardInterrupt()
                        capture.time.sleep(0.005)
                        return b''
                port = IdleSerial()
                with patch('serial.Serial', return_value=port), patch('serial.tools.list_ports.comports', return_value=[]), redirect_stdout(io.StringIO()):
                    result = capture.main(['--port', 'COM_TEST', '--seconds', '0.02', '--output', tmp])
                folder = next(Path(tmp).iterdir())
                meta = json.loads((folder/'session.json').read_text(encoding='utf-8'))
                self.assertEqual(result, 0)
                self.assertTrue(port.closed)
                self.assertEqual(meta['status'], 'stopped' if stop == 'keyboard' else 'completed')
                self.assertEqual(meta['received_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
