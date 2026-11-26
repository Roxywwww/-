"""兼容通用入口：先选称重梁，不默认为20 kg。"""
from capture_profiles import choose

if __name__ == '__main__':
    raise SystemExit(choose())
