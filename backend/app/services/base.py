"""
视频下载器基类
提供各平台下载器的共同功能
"""
import os
import re
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs, unquote
import requests
from loguru import logger

from ..core.config import settings
from ..models.video import VideoInfo, VideoFormat, ProgressInfo, DownloadProgress, Platform


class BaseDownloader(ABC):
    """视频下载器基类
    
    所有平台专用下载器都应继承此类并实现抽象方法
    """
    
    # 平台标识
    platform: Platform = Platform.OTHER
    
    # URL 匹配模式（子类应重写）
    URL_PATTERNS: List[str] = []
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None):
        self.download_dir = download_dir or Path(settings.DOWNLOAD_DIR)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.proxy = proxy or settings.PROXY_URL
    
    @classmethod
    def is_supported_url(cls, url: str) -> bool:
        """检查 URL 是否支持该平台"""
        url_lower = url.lower()
        for pattern in cls.URL_PATTERNS:
            if re.search(pattern, url_lower):
                return True
        return False
    
    @abstractmethod
    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析视频信息（抽象方法，子类必须实现）"""
        pass
    
    @abstractmethod
    async def download_video(self, url: str, **kwargs) -> str:
        """下载视频（抽象方法，子类必须实现）"""
        pass
    
    # ==================== 共享工具方法 ====================
    
    @staticmethod
    def sanitize_filename(name: str, max_length: int = 50) -> str:
        """清理文件名，移除非法字符"""
        # 移除特殊字符：Windows 文件系统禁止字符 + URL 不友好字符
        name = re.sub(r'[<>:"/\\|?*#%&{}[\]^~`\';@=+$!，。！？、…（）《》【】\s]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')
        return name[:max_length]
    
    @staticmethod
    def format_filesize(size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    @staticmethod
    def format_duration(seconds: int) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}分{secs}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}时{minutes}分"
    
    @staticmethod
    def extract_url_from_text(text: str, patterns: List[str]) -> str:
        """从文本中提取 URL"""
        text = text.strip()
        
        # 如果本身就是有效 URL，直接返回
        if text.startswith(('http://', 'https://')):
            return text
        
        # 尝试从文本中提取 URL
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                url = match.group(0)
                # 清理 URL 末尾可能的无用字符
                url = re.sub(r'[,\.\!\?\。，。！？]+$', '', url)
                return url
        
        return text
    
    def resolve_short_url(self, url: str, max_redirects: int = 5) -> str:
        """解析短链接获取真实 URL"""
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            response = session.head(url, allow_redirects=True, timeout=15, verify=True)
            return str(response.url)
        except Exception as e:
            logger.debug(f"解析短链接失败: {e}")
            return url


class YtdlpDownloader(BaseDownloader):
    """基于 yt-dlp 的通用下载器
    
    用于支持 yt-dlp 能够处理的平台（B站、YouTube、TikTok 等）
    """
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None):
        super().__init__(download_dir, proxy)
        self._executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_DOWNLOADS)
        self._progress_store: Dict[str, DownloadProgress] = {}
    
    def _build_ydl_options(self, download: bool = True, format_id: Optional[str] = None,
                           quality: str = "best", audio_only: bool = False,
                           task_id: Optional[str] = None, cookies: Optional[str] = None,
                           http_headers: Optional[Dict] = None) -> Dict[str, Any]:
        """构建 yt-dlp 配置选项"""
        import yt_dlp
        
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
        if http_headers:
            options["http_headers"] = http_headers
        
        # Cookie 支持
        if cookies:
            import tempfile
            cookie_content = self._convert_cookie_to_netscape(cookies)
            cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            cookie_file.write(cookie_content)
            cookie_file.close()
            options["cookiefile"] = cookie_file.name
        
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
    
    def _get_progress_hook(self, task_id: str):
        """创建进度回调函数"""
        def hook(d: Dict[str, Any]):
            progress = self._progress_store.get(task_id)
            if not progress:
                return
            
            if d["status"] == "downloading":
                progress.status = "downloading"
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                
                if total > 0:
                    progress.progress = (downloaded / total) * 100
                    progress.total = total
                    progress.downloaded = downloaded
                
                speed = d.get("speed")
                if speed:
                    progress.speed = self._format_speed(speed)
                
                eta = d.get("eta")
                if eta:
                    progress.eta = self._format_eta(eta)
                
                if "filename" in d:
                    progress.filename = os.path.basename(d["filename"])
            
            elif d["status"] == "finished":
                progress.status = "finished"
                progress.progress = 100.0
                progress.filename = os.path.basename(d.get("filename", ""))
                logger.info(f"下载完成: {progress.filename}")
            
            elif d["status"] == "error":
                progress.status = "error"
                progress.error = str(d.get("error", "未知错误"))
                logger.error(f"下载错误: {progress.error}")
        
        return hook
    
    @staticmethod
    def _format_speed(speed: float) -> str:
        """格式化下载速度"""
        if speed < 1024:
            return f"{speed:.0f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.1f} MB/s"
    
    @staticmethod
    def _format_eta(seconds: int) -> str:
        """格式化剩余时间"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}分{secs}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}时{minutes}分"
    
    # 文件名中不允许的字符（yt-dlp 会替换这些）
    INVALID_FILENAME_CHARS = r'<>:"/\|?*'
    
    def _sanitize_filename_for_search(self, filename: str, max_length: int = 100) -> str:
        """清理文件名用于搜索，匹配 yt-dlp 的行为"""
        # 替换不允许的字符为下划线
        for char in self.INVALID_FILENAME_CHARS:
            filename = filename.replace(char, '_')
        # 移除控制字符
        filename = ''.join(c for c in filename if ord(c) >= 32)
        # 截断长度
        if len(filename) > max_length:
            filename = filename[:max_length]
        # 移除首尾空格和点
        filename = filename.strip(' .')
        return filename
    
    def _find_downloaded_file(self, video_title: str, video_id: Optional[str] = None,
                               existing_files: Optional[set] = None) -> Optional[Path]:
        """通过视频标题和ID查找下载的文件
        
        Args:
            video_title: 视频标题
            video_id: 视频ID（可选，B站等平台建议提供）
            existing_files: 下载前已存在的文件集合（可选）
        
        Returns:
            找到的文件路径，或 None
        """
        clean_title = self._sanitize_filename_for_search(video_title, max_length=100)
        
        # 构建搜索模式
        if video_id:
            # 使用标题+ID精确匹配
            pattern = f"{clean_title}_{video_id}.*"
        else:
            # 只使用标题匹配
            pattern = f"{clean_title}.*"
        
        # 在下载目录中查找匹配的文件
        matches = list(self.download_dir.glob(pattern))
        
        if not matches:
            # 尝试更宽松的匹配（标题可能被进一步截断）
            for f in self.download_dir.iterdir():
                if f.is_file() and clean_title[:50] in f.name:
                    matches.append(f)
        
        if matches:
            # 如果提供了已存在文件集合，排除这些文件
            if existing_files:
                matches = [f for f in matches if f.name not in existing_files]
            
            if matches:
                # 返回最新的文件（或最大的文件）
                matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                return matches[0]
        
        return None
    
    @staticmethod
    def _convert_cookie_to_netscape(cookie_string: str, domain: str = ".example.com") -> str:
        """将浏览器 Cookie 字符串转换为 Netscape 格式"""
        lines = ["# Netscape HTTP Cookie File", ""]
        
        for cookie in cookie_string.strip().split(';'):
            cookie = cookie.strip()
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}")
        
        return '\n'.join(lines)
    
    def raw_to_video_info(self, raw_info: Dict[str, Any], url: str, platform: Platform) -> VideoInfo:
        """将 yt-dlp 返回的原始信息转换为 VideoInfo"""
        formats = []
        has_direct_url = False
        
        for fmt in raw_info.get("formats", []):
            if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
                continue
            
            # 文件大小：优先使用 filesize，否则使用 filesize_approx
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            
            # 判断是否有视频/音频
            vcodec = fmt.get("vcodec") or "none"
            acodec = fmt.get("acodec") or "none"
            has_video = vcodec != "none"
            has_audio = acodec != "none"
            is_audio_only = not has_video and has_audio
            is_video_only = has_video and not has_audio
            
            # 判断是否需要合并（只有视频或只有音频）
            needs_merge = is_video_only or is_audio_only
            
            # 检查是否有直链
            direct_url = fmt.get("url")
            
            # 如果是完整文件（同时有视频和音频）且有URL，标记为直链可用
            if has_video and has_audio and direct_url:
                has_direct_url = True
            
            video_format = VideoFormat(
                format_id=fmt.get("format_id", ""),
                ext=fmt.get("ext", "mp4"),
                resolution=self._get_resolution(fmt),
                filesize=filesize,
                filesize_approx=fmt.get("filesize_approx"),
                vcodec=vcodec if vcodec != "none" else None,
                acodec=acodec if acodec != "none" else None,
                fps=fmt.get("fps"),
                quality=fmt.get("format_note") or fmt.get("quality_label"),
                is_audio_only=is_audio_only,
                is_video_only=is_video_only,
                url=direct_url,
                needs_merge=needs_merge,
                has_audio=has_audio,
                has_video=has_video,
            )
            formats.append(video_format)
        
        # 判断是否需要服务器处理
        # 如果没有直链可用，或者用户请求的格式需要合并，则需要服务器处理
        needs_processing = not has_direct_url
        
        best_format = None
        if raw_info.get("format_id"):
            best_format = next(
                (f for f in formats if f.format_id == raw_info["format_id"]),
                formats[0] if formats else None
            )
        
        # 处理封面 URL（转 HTTPS）
        thumbnail = raw_info.get("thumbnail")
        if thumbnail and thumbnail.startswith("http://"):
            thumbnail = "https://" + thumbnail[7:]
        
        return VideoInfo(
            id=str(raw_info.get("id", "")),
            title=raw_info.get("title", "未知标题"),
            description=raw_info.get("description"),
            thumbnail=thumbnail,
            duration=raw_info.get("duration"),
            uploader=raw_info.get("uploader") or raw_info.get("channel"),
            uploader_id=raw_info.get("uploader_id"),
            upload_date=raw_info.get("upload_date"),
            view_count=raw_info.get("view_count"),
            like_count=raw_info.get("like_count"),
            comment_count=raw_info.get("comment_count"),
            platform=platform,
            original_url=url,
            formats=formats,
            best_format=best_format,
            has_direct_url=has_direct_url,
            needs_processing=needs_processing,
        )
    
    @staticmethod
    def _get_resolution(fmt: Dict) -> Optional[str]:
        """获取分辨率字符串"""
        width = fmt.get("width")
        height = fmt.get("height")
        if width and height:
            return f"{width}x{height}"
        if height:
            return f"{height}p"
        return None
