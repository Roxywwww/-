"""Compile the production zero-control logic and execute it in an ARM emulator.

Requires Keil ARMCC 5, unicorn and pyelftools. No hardware is accessed or flashed.
Set ZERO_TEST_DEPS to an optional directory containing the Python dependencies.
"""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if os.environ.get('ZERO_TEST_DEPS'):
    sys.path.insert(0, os.environ['ZERO_TEST_DEPS'])

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_R0

project = Path(__file__).resolve().parents[1]
compiler = Path(os.environ.get('ARMCC_BIN', r'C:\Keil_v5\ARM\ARMCC\bin'))
source = (project / 'Core/Src/oled.c').read_text(encoding='utf-8-sig')
start = source.index('void OLED_ShowProgressBar(')
brace = source.index('{', start)
depth = 1
end = brace + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1

with tempfile.TemporaryDirectory(prefix='scale_zero_test_') as temp:
    work = Path(temp)
    (work / 'oled_progress_under_test.inc').write_text(source[start:end] + '\n', encoding='utf-8')
    subprocess.run([
        str(compiler / 'armcc.exe'), '--cpu=Cortex-M3', '--thumb', '--c99',
        '--split_sections', '-O2', '-Dmain=test_entry', '-I', str(project / 'Core/Inc'),
        '-I', str(work), '-c', str(project / 'Tests/zero_control_test.c'),
        '-o', str(work / 'test.o'),
    ], check=True)
    subprocess.run([
        str(compiler / 'armlink.exe'), '--entry=test_entry', '--ro_base=0x10000',
        '--rw_base=0x20000000', '--datacompressor=off',
        '--libpath=' + str(compiler.parent / 'lib'),
        str(work / 'test.o'), '-o', str(work / 'test.axf'),
    ], check=True)
    elf = ELFFile(io.BytesIO((work / 'test.axf').read_bytes()))
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    cpu.mem_map(0x10000, 0x100000)
    cpu.mem_map(0x20000000, 0x10000)
    cpu.mem_map(0x900000, 0x1000)
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            cpu.mem_write(segment['p_vaddr'], segment.data())
    cpu.reg_write(UC_ARM_REG_SP, 0x2000F000)
    cpu.reg_write(UC_ARM_REG_LR, 0x900001)
    stopped = []
    def stop_at_return(machine, address, size, user_data):
        if address == 0x900000:
            stopped.append(True)
            machine.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, stop_at_return)
    cpu.emu_start(elf.header['e_entry'] | 1, 0x900002, count=1000000)
    if not stopped:
        raise SystemExit('FAIL: test did not return within the instruction limit')
    result = cpu.reg_read(UC_ARM_REG_R0)
    if result:
        raise SystemExit(f'FAIL: assertion {result}')
    print('PASS: 39 checkpoints, real ARM code; debounce/hold/cancel/wrap/sampling/OLED')
