"""1 kg入口：自动检查依赖，固定保存到1 kg数据目录。"""
from capture_profiles import run

if __name__ == '__main__':
    try:
        raise SystemExit(run('1kg'))
    except KeyboardInterrupt:
        raise SystemExit(130)
