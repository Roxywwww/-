"""Test routing and identity checks in temporary folders; never open hardware."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import capture_profiles as profiles
from collect_serial import SessionLog, capture_warnings
from terminal_ui import TerminalPanel


class ProfileRoutingTests(unittest.TestCase):
    def test_repo_profiles_use_distinct_existing_history_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);here=root/'工具/串口采集';here.mkdir(parents=True)
            (root/'AGENTS.md').write_text('TEST ONLY',encoding='utf-8')
            self.assertEqual(profiles.data_directory('1kg',here),root/'实验数据/1kg称重梁/原始数据/串口采集')
            self.assertEqual(profiles.data_directory('20kg',here),root/'实验数据/原始数据/串口采集')
            self.assertFalse((root/'实验数据').exists())

    def test_standalone_profiles_follow_script_folder_not_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            here=Path(tmp)/'Notebook Files';here.mkdir()
            self.assertEqual(profiles.data_directory('1kg',here),here/'采集数据/1kg')
            self.assertEqual(profiles.data_directory('20kg',here),here/'采集数据/20kg')
            self.assertNotEqual(profiles.data_directory('1kg',here),profiles.data_directory('20kg',here))

    def test_output_or_profile_metadata_cannot_be_overridden(self):
        for args in [['--output','wrong'],['--output=wrong'],
                     ['--meta','sensor_capacity_kg=20'],['--meta=capture_profile=20kg'],
                     ['--meta','expected_counts_per_g=1']]:
            with self.subTest(args=args),self.assertRaises(ValueError):
                profiles.configured_arguments('1kg',args)

    def test_metadata_is_expected_not_claimed_verified_firmware(self):
        args=profiles.configured_arguments('1kg',['--port','COM_TEST','--label','TEST ONLY','--meta','bench=test'])
        self.assertIn('sensor_capacity_kg=1',args)
        self.assertIn('expected_counts_per_g=736.8698',args)
        self.assertIn('expected_firmware_id=scale1kg_20261126',args)
        self.assertNotIn('--firmware-version',args)
        self.assertEqual(args.count('--label'),1)
        self.assertIn('bench=test',args)

    def test_show_path_never_installs_or_opens_collector(self):
        with patch.object(profiles.start_capture,'main') as start,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(profiles.run('1kg',['--show-path']),0)
        start.assert_not_called()

    def test_profiles_keep_auto_dependencies_and_awake_wrapper(self):
        with patch.object(profiles.start_capture,'main',return_value=7) as start,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(profiles.run('20kg',['--list']),7)
        args=start.call_args.args[0]
        self.assertEqual(args[0],'long')
        self.assertIn('capture_profile=20kg',args)
        self.assertIn('expected_counts_per_g=178.20',args)

    def test_listing_ports_does_not_request_prevent_sleep(self):
        import long_capture
        with patch.object(long_capture,'main',return_value=0) as collector, \
                patch.object(long_capture.ctypes.windll.kernel32,'SetThreadExecutionState') as request:
            self.assertEqual(long_capture.run(['--list']),0)
        request.assert_not_called()
        collector.assert_called_once_with(['--list'])

    def test_generic_entry_requires_choice_and_does_not_default(self):
        with patch('builtins.input',return_value='q'),patch.object(profiles,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(profiles.choose([]),2)
        run.assert_not_called()
        with patch('builtins.input',return_value='1'),patch.object(profiles,'run',return_value=0) as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(profiles.choose(['--plain']),0)
        run.assert_called_once_with('1kg',['--plain'])


class ProfileIdentityTests(unittest.TestCase):
    def metadata(self,profile='1kg'):
        config=profiles.PROFILES[profile]
        return {'port':'COM_TEST','experiment':{'user_metadata':{
            'capture_profile':profile,'sensor_capacity_kg':config['capacity'],
            'expected_counts_per_g':config['coefficient'],'expected_firmware_id':config['firmware']}}}

    def test_matching_received_fields_saved_without_claiming_physical_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=SessionLog(tmp,self.metadata(),notifier=lambda _:None)
            log.line(b'fw=scale1kg_20261126\n')
            log.line(b'scale_capacity_kg=1 counts_per_g_x10000=7368698\n')
            self.assertEqual(log.metadata['firmware_profile_check']['status'],'matched_received_fields')
            self.assertFalse(log.metadata['firmware_profile_check']['warning'])
            log.close('completed','TEST ONLY')
            saved=json.loads((log.path/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['experiment']['user_metadata']['capture_profile'],'1kg')
            self.assertEqual(saved['firmware_profile_check']['observed']['scale_capacity_kg'],'1')

    def test_mismatch_warns_once_per_change_but_preserves_data(self):
        notices=[]
        with tempfile.TemporaryDirectory() as tmp:
            log=SessionLog(tmp,self.metadata('20kg'),notifier=notices.append)
            for _ in range(2):log.line(b'scale_capacity_kg=1 counts_per_g_x10000=7368698\n')
            log.line(b'raw=400000 net=73687 g=100.0 g_avg=100.0\n')
            self.assertEqual(len(notices),1)
            self.assertEqual(log.stats['weight_valid'],1)
            self.assertEqual(log.metadata['firmware_profile_check']['status'],'mismatch')
            self.assertIn('profile',capture_warnings(log,log.started,30,5,3))
            self.assertEqual(log.markers[0]['event_type'],'profile_mismatch')
            log.close('completed','TEST ONLY')
            self.assertIn('raw=400000',(log.path/'records.csv').read_text(encoding='utf-8-sig'))

    def test_no_boot_parameters_does_not_falsely_verify_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=SessionLog(tmp,self.metadata(),notifier=lambda _:None)
            log.line(b'raw=123 net=0 g=0.0 g_avg=0.0\n')
            self.assertNotIn('firmware_profile_check',log.metadata)
            log.close('completed','TEST ONLY')

    def test_mismatch_recovers_only_after_received_correction(self):
        notices=[]
        with tempfile.TemporaryDirectory() as tmp:
            log=SessionLog(tmp,self.metadata(),notifier=notices.append)
            log.line(b'scale_capacity_kg=20 counts_per_g_x10000=1782000\n')
            log.line(b'scale_capacity_kg=1 counts_per_g_x10000=7368698\n')
            self.assertFalse(log.metadata['firmware_profile_check']['warning'])
            self.assertEqual(len(notices),2)
            self.assertEqual(log.markers[-1]['event_type'],'profile_match_restored')
            log.close('completed','TEST ONLY')

    def test_fixed_panel_keeps_selected_profile_visible(self):
        stream=io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log=SessionLog(tmp,self.metadata(),notifier=lambda _:None)
            panel=TerminalPanel(enabled=False,stream=stream);panel.active=True
            with patch('terminal_ui.shutil.get_terminal_size',return_value=(100,24)):
                panel.render(log,force=True)
            self.assertIn('1kg版',stream.getvalue())
            panel.close();log.close('completed','TEST ONLY')


if __name__=='__main__':unittest.main()
