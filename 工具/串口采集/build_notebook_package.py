"""Build the runtime-only notebook bundle with an explicit file manifest."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
OUTPUT=HERE/'电子秤采集器_分量程笔记本版_2026-11-26.zip'
FILES=['采集_1kg.py','采集_20kg.py','capture_profiles.py','choose_capture.py',
       'start_capture.py','long_capture.py','collect_serial.py','terminal_ui.py',
       '开始采集_1kg.cmd','开始采集_20kg.cmd','开始采集.cmd','开始长时间采集.cmd',
       '_运行采集.cmd','requirements.txt','使用说明.md','先看这里_保存位置.md']


def main():
    contents={name:(HERE/name).read_bytes() for name in FILES}
    manifest={'version':'2026-11-26_profiles','note':'仅采集运行文件；测试和离线分析工具保留在仓库。',
              'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in contents.items()}}
    with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in contents.items():z.writestr(name,data)
        z.writestr('文件清单.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(OUTPUT) as z:
        assert z.testzip() is None
        assert all(hashlib.sha256(z.read(name)).hexdigest()==item['sha256'] for name,item in manifest['files'].items())
    print(str(OUTPUT));print(f'{len(FILES)+1}个文件，{OUTPUT.stat().st_size}字节')


if __name__=='__main__':main()
