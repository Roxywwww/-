"""仅测试启动流程，不接真实串口，也不真正安装软件包。"""
import contextlib
import io
import subprocess
import sys
import unittest
from unittest.mock import patch

import start_capture as start


class StartTests(unittest.TestCase):
    def test_ready_does_not_install(self):
        with patch.object(start, 'dependency_ready', return_value=True), \
                patch.object(start.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(start.ensure_dependencies())
        run.assert_not_called()

    def test_missing_installs_and_checks_with_same_python(self):
        with patch.object(start, 'dependency_ready', return_value=False), \
                patch.object(start.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], 0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(start.ensure_dependencies())
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(all(cmd[0] == sys.executable for cmd in commands))
        self.assertIn('install', commands[1])
        self.assertIn(str(start.HERE / 'requirements.txt'), commands[1])
        self.assertEqual(commands[-1][1], '-c')

    def test_failed_install_never_opens_collector(self):
        outcomes = [subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 1)]
        with patch.object(start, 'dependency_ready', return_value=False), \
                patch.object(start.subprocess, 'run', side_effect=outcomes) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.main(['long', '--port', 'COM_TEST']), 2)
        self.assertEqual(run.call_count, 2)

    def test_arguments_forwarded_and_exit_code_preserved(self):
        with patch.object(start, 'ensure_dependencies', return_value=True), \
                patch.object(start.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(start.main(['long', '--list']), 7)
        self.assertEqual(run.call_args.args[0],
                         [sys.executable, '-u', str(start.HERE / 'long_capture.py'), '--list'])


if __name__ == '__main__':
    unittest.main()
