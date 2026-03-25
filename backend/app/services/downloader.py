"""
视频下载服务 - 统一入口
根据 URL 自动选择对应平台的下载器
"""
import os
import re
import asyncio
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests
import yt_dlp
from loguru import logger

from ..core.config import settings
from .platform_handler import PlatformHandler, Platform
from ..models.video import VideoInfo, VideoFormat, ProgressInfo, DownloadProgress
from .base import BaseDownloader, YtdlpDownloader

# 导入各平台专用下载器
from .douyin import DouyinDownloader
from .bilibili import BilibiliDownloader
from .youtube import YouTubeDownloader
from .tiktok import TikTokDownloader
from .twitter import TwitterDownloader
from .instagram import InstagramDownloader
from .weibo import WeiboDownloader
from .xiaohongshu import XiaohongshuDownloader


class VideoDownloader:
    """视频下载器 - 统一入口
    
    功能：
    - 自动识别 URL 对应的平台
    - 路由到对应的平台下载器
    - 提供统一的 API 接口
    """
    
    # URL 模式列表（用于从文本中提取 URL）
    URL_PATTERNS = [
        # 抖音
        r'https?://v\.douyin\.com/[A-Za-z0-9_-]+/?',
        r'https?://www\.douyin\.com/video/\d+',
        # B站
        r'https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+',
        r'https?://b23\.tv/[A-Za-z0-9]+',
        # YouTube
        r'https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+',
        r'https?://youtu\.be/[A-Za-z0-9_-]+',
        # TikTok
        r'https?://(?:www\.)?tiktok\.com/@[\w.]+/video/\d+',
        r'https?://vm\.tiktok\.com/[A-Za-z0-9]+',
        # Twitter/X
        r'https?://(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/\d+',
        # Instagram
        r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+',
        # 微博
        r'https?://(?:www\.)?weibo\.(?:com|cn)/\d+/[A-Za-z0-9]+',
        r'https?://t\.cn/[A-Za-z0-9]+',
        # 通用 HTTP/HTTPS URL
        r'https?://[^\s<>"{}|\\^`\[\]]+',
    ]
    
    def __init__(self):
        self.download_dir = Path(settings.DOWNLOAD_DIR)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # 进度跟踪
        self._progress_callbacks: Dict[str, Callable] = {}
        self._progress_store: Dict[str, DownloadProgress] = {}
        self._executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_DOWNLOADS)
        
        # 初始化各平台下载器实例
        self._init_downloaders()
    
    def _init_downloaders(self):
        """初始化各平台下载器实例"""
        proxy = settings.PROXY_URL if settings.PROXY_URL else None
        
        self._downloaders: Dict[Platform, BaseDownloader] = {
            Platform.DOUYIN: DouyinDownloader(self.download_dir, proxy=proxy),
            Platform.BILIBILI: BilibiliDownloader(self.download_dir, proxy=proxy),
            Platform.YOUTUBE: YouTubeDownloader(self.download_dir, proxy=proxy),
            Platform.TIKTOK: TikTokDownloader(self.download_dir, proxy=proxy),
            Platform.TWITTER: TwitterDownloader(self.download_dir, proxy=proxy),
            Platform.INSTAGRAM: InstagramDownloader(self.download_dir, proxy=proxy),
            Platform.WEIBO: WeiboDownloader(self.download_dir, proxy=proxy),
            Platform.XIAOHONGSHU: XiaohongshuDownloader(self.download_dir, proxy=proxy),
        }
    
    def _get_downloader(self, url: str) -> BaseDownloader:
        """根据 URL 获取对应的下载器"""
        # 确定平台
        platform_name = PlatformHandler.get_platform_name(url)
        try:
            platform = Platform(platform_name)
        except ValueError:
            platform = Platform.OTHER
        
        downloader = self._downloaders.get(platform)
        if downloader:
            return downloader
        
        # 如果没有专用下载器，使用 yt-dlp 通用下载器
        logger.warning(f"平台 {platform} 没有专用下载器，使用 yt-dlp 通用下载")
        return self._downloaders.get(Platform.BILIBILI)  # 使用 B站下载器作为通用 yt-dlp 实现
    
    def extract_url(self, text: str) -> str:
        """从文本中提取视频 URL"""
        text = text.strip()
        
        # 如果本身就是有效 URL，直接返回
        if text.startswith(('http://', 'https://')):
            return text
        
        # 尝试从文本中提取 URL
        for pattern in self.URL_PATTERNS:
            match = re.search(pattern, text)
            if match:
                url = match.group(0)
                # 清理 URL 末尾可能的无用字符
                url = re.sub(r'[,\.\!\?\。，。！？]+$', '', url)
                logger.info(f"从文本中提取到 URL: {url}")
                return url
        
        # 没找到，返回原文本
        logger.warning(f"未能从文本中提取 URL: {text[:50]}...")
        return text
    
    def _resolve_weibo_short_url(self, url: str) -> str:
        """解析微博短链接"""
        import time
        from urllib.parse import urlparse, parse_qs, unquote
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        for attempt in range(3):
            try:
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                response = session.head(url, allow_redirects=False, timeout=15, verify=True)
                redirect_url = response.headers.get('Location', '')
                
                if 'passport.weibo.com' in redirect_url:
                    parsed = urlparse(redirect_url)
                    params = parse_qs(parsed.query)
                    if 'url' in params:
                        return unquote(params['url'][0])
                
                if redirect_url and 'weibo.com' in redirect_url:
                    return redirect_url
                
                response = session.get(url, allow_redirects=True, timeout=15, verify=True)
                final_url = response.url
                
                if 'passport.weibo.com' in final_url:
                    parsed = urlparse(final_url)
                    params = parse_qs(parsed.query)
                    if 'url' in params:
                        return unquote(params['url'][0])
                
                if 'weibo.com' in final_url and 'passport' not in final_url:
                    return final_url
                
                return url
                
            except requests.exceptions.SSLError:
                if attempt < 2:
                    time.sleep(1)
                    continue
                try:
                    response = requests.get(url, allow_redirects=True, timeout=15, verify=False)
                    final_url = response.url
                    if 'passport.weibo.com' in final_url:
                        parsed = urlparse(final_url)
                        params = parse_qs(parsed.query)
                        if 'url' in params:
                            return unquote(params['url'][0])
                    return final_url if 'weibo.com' in final_url else url
                except:
                    return url
            except Exception:
                if attempt < 2:
                    time.sleep(1)
                    continue
                return url
        
        return url
    
    async def parse_video_info(self, url: str, cookies: Optional[str] = None) -> VideoInfo:
        """解析视频信息"""
        # 从分享文本中提取 URL
        url = self.extract_url(url)
        
        # 处理微博短链接
        if 't.cn' in url:
            url = self._resolve_weibo_short_url(url)
        
        # 获取对应的下载器
        downloader = self._get_downloader(url)
        
        logger.info(f"使用 {downloader.__class__.__name__} 解析: {url}")
        
        # 调用下载器的解析方法
        return await downloader.parse_video_info(url, cookies=cookies)
    
    def download(
        self,
        url: str,
        format_id: Optional[str] = None,
        quality: str = "best",
        audio_only: bool = False,
        cookies: Optional[str] = None,
    ) -> str:
        """同步下载视频"""
        # 从分享文本中提取 URL
        url = self.extract_url(url)
        
        # 处理微博短链接
        if 't.cn' in url:
            url = self._resolve_weibo_short_url(url)
        
        # 获取对应的下载器
        downloader = self._get_downloader(url)
        
        logger.info(f"使用 {downloader.__class__.__name__} 下载: {url}")
        
        # 使用 asyncio 运行异步下载
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                downloader.download_video(
                    url,
                    quality=quality,
                    format_id=format_id,
                    audio_only=audio_only,
                    cookies=cookies,
                )
            )
        finally:
            loop.close()
    
    async def download_async(
        self,
        url: str,
        format_id: Optional[str] = None,
        quality: str = "best",
        audio_only: bool = False,
        cookies: Optional[str] = None,
        video_title: Optional[str] = None,
        video_id: Optional[str] = None,
    ) -> str:
        """异步下载视频
        
        Args:
            video_title: 视频标题（用于精确匹配下载文件）
            video_id: 视频ID（用于精确匹配下载文件）
        """
        # 从分享文本中提取 URL
        url = self.extract_url(url)
        
        # 处理微博短链接
        if 't.cn' in url:
            url = self._resolve_weibo_short_url(url)
        
        # 获取对应的下载器
        downloader = self._get_downloader(url)
        
        logger.info(f"使用 {downloader.__class__.__name__} 下载（异步）: {url}")
        
        return await downloader.download_video(
            url,
            quality=quality,
            format_id=format_id,
            audio_only=audio_only,
            cookies=cookies,
            video_title=video_title,
            video_id=video_id,
        )
    
    def get_progress(self, task_id: str) -> Optional[ProgressInfo]:
        """获取下载进度"""
        progress = self._progress_store.get(task_id)
        if not progress:
            return None
        return ProgressInfo(**progress.to_dict())
    
    def clear_progress(self, task_id: str):
        """清理进度记录"""
        if task_id in self._progress_store:
            del self._progress_store[task_id]


# 全局下载器实例
downloader = VideoDownloader()