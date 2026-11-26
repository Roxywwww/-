"""20 kg入口：自动检查依赖，固定保存到20 kg历史数据目录。"""
from capture_profiles import run

if __name__ == '__main__':
    try:
        raise SystemExit(run('20kg'))
    except KeyboardInterrupt:
        raise SystemExit(130)
