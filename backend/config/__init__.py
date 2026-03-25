"""
配置模块

管理 Cookie 文件路径和其他配置
"""
from pathlib import Path

# 配置目录
CONFIG_DIR = Path(__file__).parent

# Cookie 文件路径
DOUYIN_COOKIES_PATH = CONFIG_DIR / "douyin_cookies.json"
XIAOHONGSHU_COOKIES_PATH = CONFIG_DIR / "xiaohongshu_cookies.json"


def get_douyin_cookies_path() -> Path:
    """获取抖音 Cookie 文件路径"""
    return DOUYIN_COOKIES_PATH


def get_xiaohongshu_cookies_path() -> Path:
    """获取小红书 Cookie 文件路径"""
    return XIAOHONGSHU_COOKIES_PATH
