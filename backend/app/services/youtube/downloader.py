"""
YouTube 视频下载器
基于 yt-dlp 实现
支持从浏览器读取 Cookies 绕过机器人检测
"""
import os
import asyncio
import tempfile
import shutil
import sqlite3
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from loguru import logger
import yt_dlp

from ..base import YtdlpDownloader
from ..platform_handler import Platform
from ...models.video import VideoInfo, DownloadProgress


class YouTubeDownloader(YtdlpDownloader):
    """YouTube 专用下载器
    
    功能：
    - 支持各种视频分辨率
    - 支持 YouTube Shorts
    - 支持音频提取
    - 自动从浏览器读取 Cookies 绕过机器人检测
    - 需要代理访问
    """
    
    platform = Platform.YOUTUBE
    
    URL_PATTERNS = [
        r'youtube\.com/watch',
        r'youtube\.com/shorts',
        r'youtu\.be/',
        r'youtube\.com/embed/',
    ]
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None,
                 cookies: Optional[str] = None):
        super().__init__(download_dir, proxy)
        self.cookies = cookies
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._progress_store: Dict[str, DownloadProgress] = {}
        self._cookie_file: Optional[str] = None
    
    def _get_youtube_cookies(self) -> Optional[str]:
        """从浏览器获取 YouTube Cookies"""
        # 1. 尝试使用 browser-cookie3 库（最可靠）
        try:
            import browser_cookie3
            cookies = []
            for cookie in browser_cookie3.chrome(domain_name='youtube.com'):
                cookies.append((cookie.name, cookie.value, cookie.domain))
            
            if cookies:
                # 转换为 Netscape 格式
                netscape_lines = ['# Netscape HTTP Cookie File', '']
                for name, value, domain in cookies:
                    domain = domain if domain.startswith('.') else f'.{domain}'
                    netscape_lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
                
                # 写入临时文件
                cookie_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False
                )
                cookie_file.write('\n'.join(netscape_lines))
                cookie_file.close()
                
                self._cookie_file = cookie_file.name
                logger.info(f"从 Chrome 读取到 {len(cookies)} 个 YouTube Cookie (browser-cookie3)")
                return cookie_file.name
        except ImportError:
            logger.debug("未安装 browser-cookie3，尝试其他方式")
        except Exception as e:
            logger.debug(f"browser-cookie3 读取失败: {e}")
        
        # 2. 尝试从 Firefox 获取
        firefox_profiles = [
            os.path.expanduser("~/snap/firefox/common/.mozilla/firefox"),
            os.path.expanduser("~/.mozilla/firefox"),
            os.path.expanduser("~/.var/app/org.mozilla.firefox/.mozilla/firefox"),
        ]
        
        for profiles_dir in firefox_profiles:
            if not os.path.isdir(profiles_dir):
                continue
            for item in os.listdir(profiles_dir):
                if item.endswith('.default') or item.endswith('.default-release'):
                    profile_path = os.path.join(profiles_dir, item)
                    cookie_file = self._read_firefox_cookies(profile_path)
                    if cookie_file:
                        return cookie_file
        
        return None

    def _read_firefox_cookies(self, profile_path: str) -> Optional[str]:
        """从 Firefox 读取 YouTube Cookies"""
        cookies_file = os.path.join(profile_path, "cookies.sqlite")
        if not os.path.exists(cookies_file):
            return None
        
        try:
            # 复制到临时文件避免锁定
            temp_cookies = os.path.join(tempfile.gettempdir(), "firefox_yt_cookies.sqlite")
            shutil.copy2(cookies_file, temp_cookies)
            
            conn = sqlite3.connect(temp_cookies)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE '%youtube%'"
            )
            cookies = cursor.fetchall()
            conn.close()
            os.unlink(temp_cookies)
            
            if cookies:
                # 转换为 Netscape 格式
                netscape_lines = ['# Netscape HTTP Cookie File', '']
                for name, value in cookies:
                    netscape_lines.append(f".youtube.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
                
                # 写入临时文件
                cookie_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.txt', delete=False
                )
                cookie_file.write('\n'.join(netscape_lines))
                cookie_file.close()
                
                self._cookie_file = cookie_file.name
                logger.info(f"从 Firefox 读取到 {len(cookies)} 个 YouTube Cookie")
                return cookie_file.name
        except Exception as e:
            logger.debug(f"从 Firefox 读取 YouTube Cookie 失败: {e}")
        
        return None

    def _build_ydl_options(self, download: bool = True, format_id: Optional[str] = None,
                           quality: str = "best", audio_only: bool = False,
                           task_id: Optional[str] = None, cookies: Optional[str] = None,
                           http_headers: Optional[Dict] = None) -> Dict[str, Any]:
        """构建 yt-dlp 配置选项"""
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 60,
            "retries": 3,
        }
        
        # 代理设置
        if self.proxy:
            options["proxy"] = self.proxy
        
        # HTTP Headers
        options["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        
        # Cookie 支持 - YouTube 需要登录验证
        cookie_source = None
        
        # 1. 优先使用传入的 cookies
        if cookies:
            import tempfile
            cookie_content = self._convert_cookie_to_netscape(cookies, ".youtube.com")
            cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            cookie_file.write(cookie_content)
            cookie_file.close()
            options["cookiefile"] = cookie_file.name
            cookie_source = "参数传入"
        # 2. 尝试从浏览器读取
        elif not self.cookies:
            browser_cookie = self._get_youtube_cookies()
            if browser_cookie:
                options["cookiefile"] = browser_cookie
                cookie_source = "浏览器"
        
        if cookie_source:
            logger.debug(f"YouTube Cookie 来源: {cookie_source}")
        
        # 输出模板
        options["outtmpl"] = {
            "default": str(self.download_dir / "%(title).100s_%(id)s.%(ext)s"),
        }
        
        # 格式选择
        if audio_only:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif format_id:
            options["format"] = format_id
        else:
            format_map = {
                "best": "bestvideo+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
                "audio": "bestaudio/best",
            }
            options["format"] = format_map.get(quality, format_map["best"])
        
        # 下载时添加进度回调
        if download and task_id:
            options["progress_hooks"] = [self._get_progress_hook(task_id)]
        
        # 合并视频和音频
        options["merge_output_format"] = "mp4"
        
        return options

    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析 YouTube 视频信息"""
        options = self._build_ydl_options(download=False)
        
        loop = asyncio.get_event_loop()
        
        def _extract():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)
        
        try:
            raw_info = await loop.run_in_executor(self._executor, _extract)
        except Exception as e:
            error_msg = str(e)
            if "Sign in to confirm" in error_msg or "not a bot" in error_msg:
                logger.error(f"YouTube 需要登录验证，请在浏览器中登录 YouTube")
                raise Exception("YouTube 需要登录验证。请在 Firefox 中登录 YouTube 后重试。")
            logger.error(f"解析 YouTube 视频失败: {e}")
            raise Exception(f"解析 YouTube 视频失败: {e}")
        finally:
            # 清理临时 cookie 文件
            self._cleanup_cookie_file()
        
        return self.raw_to_video_info(raw_info, url, Platform.YOUTUBE)

    async def download_video(self, url: str, quality: str = "best",
                             format_id: Optional[str] = None,
                             audio_only: bool = False, **kwargs) -> str:
        """下载 YouTube 视频
        
        支持通过 video_title 精确匹配下载文件
        """
        video_title = kwargs.get("video_title")
        
        task_id = f"yt_{os.urandom(4).hex()}"
        self._progress_store[task_id] = DownloadProgress(task_id)
        
        options = self._build_ydl_options(
            download=True,
            format_id=format_id,
            quality=quality,
            audio_only=audio_only,
            task_id=task_id,
        )
        
        logger.info(f"开始下载 YouTube 视频: {url}")
        
        # 记录下载前已存在的文件
        existing_files = set(f.name for f in self.download_dir.glob("*") if f.is_file())
        
        loop = asyncio.get_event_loop()
        
        def _download():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.download([url])
        
        try:
            result = await loop.run_in_executor(self._executor, _download)
            
            if result != 0:
                raise Exception(f"下载失败，返回码: {result}")
            
            # 方法1：通过进度回调获取文件名
            progress = self._progress_store.get(task_id)
            if progress and progress.filename:
                filepath = self.download_dir / progress.filename
                if filepath.exists():
                    logger.info(f"YouTube 视频下载完成: {progress.filename}")
                    return str(filepath)
            
            # 方法2：通过视频标题查找文件（优先使用）
            if video_title:
                filepath = self._find_downloaded_file(video_title, existing_files=existing_files)
                if filepath:
                    logger.info(f"YouTube 视频下载完成（通过标题匹配）: {filepath.name}")
                    return str(filepath)
            
            # 方法3：查找新增的文件
            current_files = set(f.name for f in self.download_dir.glob("*") if f.is_file())
            new_files = current_files - existing_files
            video_extensions = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.mp3', '.m4a'}
            new_video_files = [f for f in new_files if Path(f).suffix.lower() in video_extensions]
            if new_video_files:
                new_video_files.sort(key=lambda f: (self.download_dir / f).stat().st_size, reverse=True)
                filename = new_video_files[0]
                logger.info(f"YouTube 视频下载完成（通过文件对比）: {filename}")
                return str(self.download_dir / filename)
            
            raise Exception("无法找到下载的文件")
        finally:
            self._progress_store.pop(task_id, None)
            self._cleanup_cookie_file()

    def _cleanup_cookie_file(self):
        """清理临时 cookie 文件"""
        if self._cookie_file and os.path.exists(self._cookie_file):
            try:
                os.unlink(self._cookie_file)
            except:
                pass
            self._cookie_file = None
