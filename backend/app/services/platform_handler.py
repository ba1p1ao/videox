"""
平台特定处理器
针对不同视频平台的特殊配置和反爬策略
"""
# 添加 deno 到 PATH（YouTube 签名挑战求解需要）- 必须在所有导入之前
import os
_deno_path = os.path.expanduser("~/.deno/bin")
if os.path.isdir(_deno_path) and _deno_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _deno_path + os.pathsep + os.environ.get("PATH", "")

from typing import Dict, Any, Optional
from urllib.parse import urlparse
from enum import Enum
import re
import logging

from ..core.config import settings

# 设置 logger
logger = logging.getLogger(__name__)

# 检测 curl_cffi 是否可用（impersonate 功能依赖）
try:
    import curl_cffi  # noqa: F401
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

# 尝试导入 ImpersonateTarget
try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    IMPERSONATE_AVAILABLE = True
except ImportError:
    IMPERSONATE_AVAILABLE = False


class Platform(Enum):
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    WEIBO = "weibo"
    XIAOHONGSHU = "xiaohongshu"
    OTHER = "other"


class PlatformHandler:
    """平台处理器 - 针对各平台的自定义配置"""
    
    # 平台 URL 模式匹配
    PLATFORM_PATTERNS = {
        Platform.YOUTUBE: [
            r'youtube\.com',
            r'youtu\.be',
        ],
        Platform.BILIBILI: [
            r'bilibili\.com',
            r'b23\.tv',
        ],
        Platform.DOUYIN: [
            r'douyin\.com',
            r'iesdouyin\.com',
        ],
        Platform.TIKTOK: [
            r'tiktok\.com',
            r'vm\.tiktok\.com',
        ],
        Platform.TWITTER: [
            r'twitter\.com',
            r'x\.com',
        ],
        Platform.INSTAGRAM: [
            r'instagram\.com',
            r'instagr\.am',
        ],
        Platform.WEIBO: [
            r'weibo\.com',
            r'weibo\.cn',
            r't\.cn',  # 微博短链接
        ],
        Platform.XIAOHONGSHU: [
            r'xiaohongshu\.com',
            r'xhslink\.com',
        ],
    }
    
    # 通用浏览器 User-Agent
    CHROME_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    
    # 平台特定 Headers
    PLATFORM_HEADERS = {
        Platform.BILIBILI: {
            "Referer": "https://www.bilibili.com",
            "User-Agent": CHROME_UA,
        },
        Platform.DOUYIN: {
            "Referer": "https://www.douyin.com",
            "User-Agent": CHROME_UA,
        },
        Platform.TIKTOK: {
            "Referer": "https://www.tiktok.com",
            "User-Agent": CHROME_UA,
        },
        Platform.TWITTER: {
            "Referer": "https://twitter.com",
            "User-Agent": CHROME_UA,
        },
        Platform.INSTAGRAM: {
            "Referer": "https://www.instagram.com",
            "User-Agent": CHROME_UA,
        },
        Platform.WEIBO: {
            "Referer": "https://weibo.com",
            "User-Agent": CHROME_UA,
        },
    }
    
    @classmethod
    def detect_platform(cls, url: str) -> Platform:
        """检测URL所属平台"""
        url_lower = url.lower()
        for platform, patterns in cls.PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return platform
        return Platform.OTHER
    
    @classmethod
    def get_yt_dlp_options(cls, url: str) -> Dict[str, Any]:
        """
        根据平台获取 yt-dlp 配置选项
        
        Args:
            url: 视频 URL
            
        Returns:
            yt-dlp 配置字典
        """
        platform = cls.detect_platform(url)
        base_options = cls._get_base_options()
        
        # 根据平台添加特定配置
        if platform == Platform.BILIBILI:
            return cls._get_bilibili_options(base_options)
        elif platform == Platform.DOUYIN:
            return cls._get_douyin_options(base_options)
        elif platform == Platform.TIKTOK:
            return cls._get_tiktok_options(base_options)
        elif platform == Platform.TWITTER:
            return cls._get_twitter_options(base_options)
        elif platform == Platform.INSTAGRAM:
            return cls._get_instagram_options(base_options)
        elif platform == Platform.YOUTUBE:
            return cls._get_youtube_options(base_options)
        else:
            return base_options
    
    @classmethod
    def _get_base_options(cls) -> Dict[str, Any]:
        """获取基础配置"""
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 60,
            "retries": 3,
        }
        # 添加代理支持
        if settings.PROXY_URL:
            options["proxy"] = settings.PROXY_URL
        return options
    
    @classmethod
    def _get_bilibili_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """
        B站特定配置
        解决防盗链问题
        """
        options = base.copy()
        options.update({
            "http_headers": cls.PLATFORM_HEADERS[Platform.BILIBILI],
        })
        # 使用 ImpersonateTarget 对象
        if CURL_CFFI_AVAILABLE and IMPERSONATE_AVAILABLE:
            options["impersonate"] = ImpersonateTarget("chrome")
        return options
    
    @classmethod
    def _get_douyin_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """
        抖音特定配置
        抖音需要 cookies 才能访问，自动从浏览器读取
        """
        options = base.copy()
        options.update({
            "http_headers": cls.PLATFORM_HEADERS[Platform.DOUYIN],
        })
        
        # 优先从 Firefox 读取完整 cookie（包括 ttwid）
        firefox_profiles = [
            # snap Firefox
            os.path.expanduser("~/snap/firefox/common/.mozilla/firefox"),
            # 标准 Firefox
            os.path.expanduser("~/.mozilla/firefox"),
            # Flatpak Firefox
            os.path.expanduser("~/.var/app/org.mozilla.firefox/.mozilla/firefox"),
        ]
        
        cookie_source = None
        firefox_profile_path = None
        
        for profiles_dir in firefox_profiles:
            if os.path.isdir(profiles_dir):
                for item in os.listdir(profiles_dir):
                    if item.endswith('.default') or item.endswith('.default-release'):
                        candidate = os.path.join(profiles_dir, item)
                        if os.path.isdir(candidate):
                            firefox_profile_path = candidate
                            break
            if firefox_profile_path:
                break
        
        if firefox_profile_path:
            cookies_file = os.path.join(firefox_profile_path, "cookies.sqlite")
            if os.path.exists(cookies_file):
                import tempfile
                import shutil
                import sqlite3
                try:
                    # 复制数据库到临时文件（避免锁定问题）
                    temp_dir = tempfile.gettempdir()
                    temp_cookies = os.path.join(temp_dir, "firefox_douyin_cookies.sqlite")
                    shutil.copy2(cookies_file, temp_cookies)
                    
                    # 读取抖音相关的 cookie
                    conn = sqlite3.connect(temp_cookies)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name, value FROM moz_cookies WHERE host LIKE '%douyin%'"
                    )
                    cookies = cursor.fetchall()
                    conn.close()
                    os.unlink(temp_cookies)
                    
                    # 检查是否包含关键 cookie
                    cookie_names = [name for name, _ in cookies]
                    if 'ttwid' in cookie_names:
                        # 转换为 Netscape 格式
                        netscape_lines = ['# Netscape HTTP Cookie File', '']
                        for name, value in cookies:
                            netscape_lines.append(f".douyin.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
                        
                        # 写入临时 cookie 文件
                        cookie_file = tempfile.NamedTemporaryFile(
                            mode='w', suffix='.txt', delete=False
                        )
                        cookie_file.write('\n'.join(netscape_lines))
                        cookie_file.close()
                        options["cookiefile"] = cookie_file.name
                        cookie_source = f"firefox (含 ttwid, 共 {len(cookies)} 个 cookie)"
                    else:
                        # 回退到 cookiesfrombrowser
                        options["cookiesfrombrowser"] = ('firefox', firefox_profile_path)
                        cookie_source = f"firefox ({firefox_profile_path})"
                except Exception as e:
                    logger.debug(f"从 Firefox 读取 cookie 失败: {e}")
        
        if not cookie_source:
            # 尝试其他浏览器
            for browser in ['chrome', 'edge', 'chromium', 'brave']:
                try:
                    options["cookiesfrombrowser"] = (browser,)
                    cookie_source = browser
                    break
                except Exception:
                    continue
        
        if cookie_source:
            logger.debug(f"抖音 Cookie 来源: {cookie_source}")
        
        if CURL_CFFI_AVAILABLE and IMPERSONATE_AVAILABLE:
            options["impersonate"] = ImpersonateTarget("chrome")
        return options
    
    @classmethod
    def _get_tiktok_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """TikTok 特定配置"""
        options = base.copy()
        options.update({
            "http_headers": cls.PLATFORM_HEADERS[Platform.TIKTOK],
        })
        if CURL_CFFI_AVAILABLE and IMPERSONATE_AVAILABLE:
            options["impersonate"] = ImpersonateTarget("chrome")
        return options
    
    @classmethod
    def _get_twitter_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """Twitter/X 特定配置"""
        options = base.copy()
        options.update({
            "http_headers": cls.PLATFORM_HEADERS[Platform.TWITTER],
        })
        return options
    
    @classmethod
    def _get_instagram_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """Instagram 特定配置"""
        options = base.copy()
        options.update({
            "http_headers": cls.PLATFORM_HEADERS[Platform.INSTAGRAM],
        })
        return options
    
    @classmethod
    def _get_youtube_options(cls, base: Dict[str, Any]) -> Dict[str, Any]:
        """YouTube 特定配置"""
        options = base.copy()
        options.update({
            "http_headers": {
                "User-Agent": cls.CHROME_UA,
            },
            # 不指定 player_client，让 yt-dlp 自动选择（会使用 android vr 获取更多格式）
        })
        return options
    
    @classmethod
    def get_platform_name(cls, url: str) -> str:
        """获取平台名称"""
        platform = cls.detect_platform(url)
        return platform.value
