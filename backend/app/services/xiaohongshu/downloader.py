"""
小红书视频下载器
支持视频和图文笔记下载
"""
import os
import re
import json
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile
import sqlite3
import shutil

from loguru import logger
import yt_dlp

from ..base import YtdlpDownloader
from ..platform_handler import Platform
from ...models.video import VideoInfo, VideoFormat, DownloadProgress


class XiaohongshuDownloader(YtdlpDownloader):
    """小红书专用下载器
    
    功能：
    - 支持视频笔记下载
    - 支持图文笔记下载
    - 支持短链接解析
    - 自动从浏览器读取 Cookie
    """
    
    platform = Platform.XIAOHONGSHU
    
    URL_PATTERNS = [
        r'xiaohongshu\.com/discovery/item/',
        r'xiaohongshu\.com/explore/',
        r'xiaohongshu\.com/user/',
        r'xhslink\.com/',
    ]
    
    API_BASE = "https://www.xiaohongshu.com"
    
    # Cookie 文件路径：backend/config/xiaohongshu_cookies.json
    COOKIE_FILE_PATHS = [
        Path(__file__).parent.parent.parent.parent / "config" / "xiaohongshu_cookies.json",
    ]
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None,
                 cookies: Optional[str] = None):
        super().__init__(download_dir, proxy)
        self.cookies = cookies
        self._cookie_dict = self._init_cookies()
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._progress_store: Dict[str, DownloadProgress] = {}
    
    async def _download_gallery_images(self, note_id: str, images: List[Dict]) -> List[Dict]:
        """下载图文作品图片到本地，返回本地静态文件 URL
        
        与抖音一样，将图片下载到本地服务器，避免：
        1. 缓存数据过大（base64 数据）
        2. 远程图片防盗链问题
        3. 前端直接请求远程图片失败
        """
        # 图片存储目录
        images_dir = self.download_dir / "images" / "xiaohongshu" / note_id
        images_dir.mkdir(parents=True, exist_ok=True)
        
        headers = self._get_headers()
        
        result = []
        skipped = 0  # 已存在的图片数量
        
        async with aiohttp.ClientSession() as session:
            for idx, img in enumerate(images):
                img_url = img.get("urlDefault") or img.get("url")
                if not img_url:
                    continue
                
                # 转换为 HTTPS
                if img_url.startswith("http://"):
                    img_url = "https://" + img_url[7:]
                
                # 获取图片尺寸
                width = img.get("width") or img.get("liveUrl", {}).get("width")
                height = img.get("height") or img.get("liveUrl", {}).get("height")
                
                # 获取文件扩展名
                ext = ".jpg"
                if ".png" in img_url.lower():
                    ext = ".png"
                elif ".webp" in img_url.lower():
                    ext = ".webp"
                
                filename = f"{idx + 1:02d}{ext}"
                filepath = images_dir / filename
                
                # 如果文件已存在，跳过下载
                if filepath.exists() and filepath.stat().st_size > 0:
                    skipped += 1
                    result.append({
                        "url": f"/static/images/xiaohongshu/{note_id}/{filename}",
                        "width": width,
                        "height": height,
                    })
                    logger.debug(f"图片 {idx + 1} 已存在，跳过下载")
                    continue
                
                try:
                    async with session.get(img_url, headers=headers, proxy=self.proxy, timeout=30) as response:
                        if response.status == 200:
                            img_data = await response.read()
                            with open(filepath, 'wb') as f:
                                f.write(img_data)
                        else:
                            logger.warning(f"下载图片 {idx + 1} 失败: HTTP {response.status}")
                            continue
                    
                    result.append({
                        "url": f"/static/images/xiaohongshu/{note_id}/{filename}",
                        "width": width,
                        "height": height,
                    })
                    logger.debug(f"已保存图片 {idx + 1}/{len(images)}: {filename}")
                    
                except Exception as e:
                    logger.warning(f"保存图片 {idx + 1} 失败: {e}")
                    continue
        
        if skipped > 0:
            logger.info(f"已存在 {skipped} 张图片，新下载 {len(result) - skipped} 张")
        logger.info(f"已保存 {len(result)}/{len(images)} 张图片到 {images_dir}")
        return result
    
    def _init_cookies(self) -> Dict[str, str]:
        """初始化 Cookie"""
        if self.cookies:
            return self._parse_cookie_string(self.cookies)
        
        cookies = self._read_cookies_from_file()
        if cookies:
            return cookies
        
        cookies = self._read_cookies_from_browser()
        if cookies:
            return cookies
        
        return {}
    
    def _parse_cookie_string(self, cookie_str: str) -> Dict[str, str]:
        """解析 cookie 字符串"""
        cookies = {}
        for item in cookie_str.split(';'):
            item = item.strip()
            if '=' in item:
                name, value = item.split('=', 1)
                cookies[name.strip()] = value.strip()
        return cookies
    
    def _read_cookies_from_file(self) -> Optional[Dict[str, str]]:
        """从文件读取 Cookie"""
        for path in self.COOKIE_FILE_PATHS:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                    if isinstance(cookies, dict) and cookies:
                        logger.info(f"从文件读取到 {len(cookies)} 个小红书 Cookie")
                        return cookies
                except Exception as e:
                    logger.debug(f"读取 Cookie 文件失败: {e}")
        return None
    
    def _read_cookies_from_browser(self) -> Optional[Dict[str, str]]:
        """从浏览器读取小红书 Cookie
        
        同时尝试多个浏览器，优先返回有登录凭证(web_session)的 Cookie
        """
        all_cookies = []  # 存储 (cookies, has_login, source) 元组
        
        # 1. 尝试使用 browser-cookie3 库读取 Chrome 和 Firefox
        try:
            import browser_cookie3
            
            # 尝试 Chrome
            try:
                chrome_cookies = {}
                for cookie in browser_cookie3.chrome(domain_name='xiaohongshu.com'):
                    chrome_cookies[cookie.name] = cookie.value
                if chrome_cookies:
                    has_login = 'web_session' in chrome_cookies
                    all_cookies.append((chrome_cookies, has_login, 'Chrome'))
                    logger.debug(f"从 Chrome 读取到 {len(chrome_cookies)} 个 Cookie, 登录状态: {has_login}")
            except Exception as e:
                logger.debug(f"Chrome Cookie 读取失败: {e}")
            
            # 尝试 Firefox
            try:
                firefox_cookies = {}
                for cookie in browser_cookie3.firefox(domain_name='xiaohongshu.com'):
                    firefox_cookies[cookie.name] = cookie.value
                if firefox_cookies:
                    has_login = 'web_session' in firefox_cookies
                    all_cookies.append((firefox_cookies, has_login, 'Firefox'))
                    logger.debug(f"从 Firefox 读取到 {len(firefox_cookies)} 个 Cookie, 登录状态: {has_login}")
            except Exception as e:
                logger.debug(f"Firefox Cookie 读取失败: {e}")
                
        except ImportError:
            logger.debug("未安装 browser-cookie3，尝试其他方式")
        except Exception as e:
            logger.debug(f"browser-cookie3 读取失败: {e}")
        
        # 2. 尝试从 Firefox 数据库直接读取（备选方案）
        if not any(c[2] == 'Firefox' for c in all_cookies):
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
                        cookies = self._read_firefox_cookies(profile_path)
                        if cookies:
                            has_login = 'web_session' in cookies
                            all_cookies.append((cookies, has_login, 'Firefox(DB)'))
                            break
        
        # 3. 优先返回有登录凭证的 Cookie
        for cookies, has_login, source in all_cookies:
            if has_login:
                logger.info(f"从 {source} 读取到 {len(cookies)} 个小红书 Cookie (已登录)")
                return cookies
        
        # 4. 如果都没有登录，返回第一个有效的
        for cookies, has_login, source in all_cookies:
            if cookies:
                logger.info(f"从 {source} 读取到 {len(cookies)} 个小红书 Cookie (未登录)")
                return cookies
        
        return None
    
    def _read_firefox_cookies(self, profile_path: str) -> Optional[Dict[str, str]]:
        """从 Firefox 读取小红书 Cookie"""
        cookies_file = os.path.join(profile_path, "cookies.sqlite")
        if not os.path.exists(cookies_file):
            return None
        
        try:
            temp_cookies = os.path.join(tempfile.gettempdir(), "firefox_xhs_cookies.sqlite")
            shutil.copy2(cookies_file, temp_cookies)
            
            conn = sqlite3.connect(temp_cookies)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE '%xiaohongshu%'"
            )
            cookies = {name: value for name, value in cursor.fetchall()}
            conn.close()
            os.unlink(temp_cookies)
            
            if cookies:
                logger.info(f"从 Firefox 读取到 {len(cookies)} 个小红书 Cookie")
                return cookies
        except Exception as e:
            logger.debug(f"从 Firefox 读取 Cookie 失败: {e}")
        return None
    
    @staticmethod
    def _safe_int(value) -> int:
        """安全转换为整数，处理空字符串和 None"""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if not value.strip():
                return 0
            try:
                return int(value)
            except ValueError:
                return 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
    
    def _get_headers(self, with_cookie: bool = True) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        
        if with_cookie and self._cookie_dict:
            cookie_str = '; '.join(f'{k}={v}' for k, v in self._cookie_dict.items())
            headers["Cookie"] = cookie_str
        
        return headers
    
    @staticmethod
    def extract_note_id(url: str) -> Optional[str]:
        """从小红书 URL 提取笔记 ID"""
        patterns = [
            r'xiaohongshu\.com/discovery/item/([a-zA-Z0-9]+)',
            r'xiaohongshu\.com/explore/([a-zA-Z0-9]+)',
            r'xiaohongshu\.com/user/[^/]+/([a-zA-Z0-9]+)',
            # 匹配带参数的URL
            r'/item/([a-zA-Z0-9]+)',
            r'/explore/([a-zA-Z0-9]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    async def _resolve_short_url(self, url: str) -> str:
        """解析小红书短链接"""
        if 'xhslink.com' not in url:
            return url
        
        try:
            # 使用 GET 请求并禁用重定向，手动获取 Location
            async with aiohttp.ClientSession() as session:
                # 先尝试 GET 请求（不跟随重定向）
                async with session.get(url, allow_redirects=False, timeout=15) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if location:
                            logger.debug(f"短链接解析（重定向）: {url} -> {location}")
                            return location
                
                # 如果没有重定向，尝试跟随重定向
                async with session.get(url, allow_redirects=True, timeout=15) as response:
                    final_url = str(response.url)
                    logger.debug(f"短链接解析（跟随）: {url} -> {final_url}")
                    return final_url
        except Exception as e:
            logger.warning(f"解析短链接失败: {e}")
            return url
    
    async def _fetch_note_info(self, note_id: str, original_url: str = None) -> Dict[str, Any]:
        """通过 API 获取笔记信息
        
        Args:
            note_id: 笔记 ID
            original_url: 原始 URL（可能包含 xsec_token 等参数）
        """
        from urllib.parse import urlparse, parse_qs, urlencode
        
        # 确定路径格式（保留原始 URL 的路径）
        path = f"/discovery/item/{note_id}"  # 默认路径
        if original_url:
            parsed_original = urlparse(original_url)
            if '/explore/' in parsed_original.path:
                path = f"/explore/{note_id}"
            elif '/discovery/item/' in parsed_original.path:
                path = f"/discovery/item/{note_id}"
        
        # 构建请求 URL，保留原始 URL 中的参数（如 xsec_token）
        if original_url and '?' in original_url:
            parsed = urlparse(original_url)
            query_params = parse_qs(parsed.query)
            keep_params = {}
            if 'xsec_token' in query_params:
                keep_params['xsec_token'] = query_params['xsec_token'][0]
            if 'xsec_source' in query_params:
                keep_params['xsec_source'] = query_params['xsec_source'][0]
            if 'source' in query_params:
                keep_params['source'] = query_params['source'][0]
            
            if keep_params:
                url = f"{self.API_BASE}{path}?{urlencode(keep_params)}"
            else:
                url = f"{self.API_BASE}{path}"
        else:
            url = f"{self.API_BASE}{path}"
        
        headers = self._get_headers(with_cookie=True)
        has_cookie = bool(self._cookie_dict)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=self.proxy, timeout=30) as response:
                if response.status != 200:
                    raise Exception(f"获取笔记信息失败: HTTP {response.status}")
                
                html = await response.text()
                
                # 检测页面是否失效
                if '页面不见了' in html or '你访问的页面不存在' in html:
                    if not has_cookie:
                        raise Exception("小红书需要登录 Cookie 才能访问。请在浏览器登录小红书后重试。")
                    raise Exception("笔记不存在或已被删除，请检查链接是否正确")
                
                # 检测是否需要登录
                if '请登录' in html or '登录后查看' in html:
                    raise Exception("此笔记需要登录才能查看，请提供小红书 Cookie")
                
                # 从 HTML 中提取 __INITIAL_STATE__ 数据
                match = re.search(r'__INITIAL_STATE__\s*=\s*({.+?})\s*</script>', html, re.DOTALL)
                if match:
                    try:
                        json_str = match.group(1)
                        # 找到 JSON 的正确结束位置
                        depth = 0
                        end_pos = 0
                        for i, char in enumerate(json_str):
                            if char == '{':
                                depth += 1
                            elif char == '}':
                                depth -= 1
                                if depth == 0:
                                    end_pos = i + 1
                                    break
                        
                        json_str = json_str[:end_pos]
                        json_str = re.sub(r':\s*undefined\b', ': null', json_str)
                        json_str = json_str.replace('"undefined"', '"null_key"')
                        
                        data = json.loads(json_str)
                        return data
                    except json.JSONDecodeError as e:
                        logger.debug(f"解析 JSON 失败: {e}")
                
                raise Exception("无法从页面提取笔记数据")
    
    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析小红书笔记信息"""
        original_url = url  # 保存原始 URL（包含 xsec_token 等参数）
        url = await self._resolve_short_url(url)
        
        note_id = self.extract_note_id(url)
        if not note_id:
            raise Exception(f"无法从 URL 提取笔记 ID: {url}")
        
        logger.info(f"解析小红书笔记: note_id={note_id}")
        
        try:
            # 传递原始 URL 以保留查询参数
            initial_state = await self._fetch_note_info(note_id, original_url)
            return await self._parse_initial_state(initial_state, url, note_id)
        except Exception as e:
            error_msg = str(e)
            if 'Cookie' in error_msg or '登录' in error_msg:
                raise
            logger.warning(f"API 方式失败，尝试 yt-dlp: {e}")
            return await self._parse_with_ytdlp(url)
    
    async def _parse_with_ytdlp(self, url: str) -> VideoInfo:
        """使用 yt-dlp 解析"""
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        
        if self.proxy:
            options["proxy"] = self.proxy
        
        loop = asyncio.get_event_loop()
        
        def _extract():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)
        
        try:
            raw_info = await loop.run_in_executor(self._executor, _extract)
            return self.raw_to_video_info(raw_info, url, Platform.XIAOHONGSHU)
        except Exception as e:
            logger.error(f"yt-dlp 解析也失败: {e}")
            raise Exception(f"小红书解析失败: {e}")
    
    async def _parse_initial_state(self, data: Dict[str, Any], original_url: str, note_id: str) -> VideoInfo:
        """解析 INITIAL_STATE 数据"""
        note_data = None
        
        # 尝试从不同位置获取笔记数据
        note_state = data.get('note', {})
        note_map = note_state.get('noteDetailMap', {})
        
        if note_map:
            for key, value in note_map.items():
                if isinstance(value, dict) and 'note' in value:
                    inner_note = value['note']
                    if inner_note and (inner_note.get('title') or inner_note.get('video') or inner_note.get('imageList')):
                        note_data = inner_note
                        break
        
        if not note_data:
            raise Exception("无法解析笔记数据结构，可能需要登录")
        
        # 提取基本信息
        title = note_data.get("title") or note_data.get("desc", "")[:50] or "未知标题"
        description = note_data.get("desc")
        
        # 提取封面
        cover = None
        cover_info = note_data.get("imageList") or note_data.get("imagesList")
        if cover_info and isinstance(cover_info, list) and cover_info:
            cover = cover_info[0].get("urlDefault") or cover_info[0].get("url")
        elif note_data.get("video"):
            video_info = note_data["video"]
            cover = video_info.get("cover", {}).get("urlDefault") or video_info.get("coverUrl")
        
        # 提取用户信息
        user_info = note_data.get("user") or {}
        uploader = user_info.get("nickname") or user_info.get("name") or "未知用户"
        uploader_id = user_info.get("userId") or user_info.get("user_id") or ""
        
        # 提取互动数据（确保转为整数，处理空字符串情况）
        interact_info = note_data.get("interactInfo") or {}
        like_count = self._safe_int(interact_info.get("likedCount"))
        comment_count = self._safe_int(interact_info.get("commentCount"))
        
        # 判断内容类型
        is_video = bool(note_data.get("video"))
        
        formats = []
        duration = None
        
        if is_video:
            video_info = note_data["video"]
            duration = video_info.get("duration", 0)
            if duration:
                duration = duration // 1000
            else:
                # 尝试从视频流中获取时长
                stream_info = video_info.get("media", {}).get("stream", {})
                for codec, streams in stream_info.items():
                    if isinstance(streams, list) and streams:
                        duration = streams[0].get("duration", 0)
                        if duration:
                            duration = duration // 1000
                            break
                    elif isinstance(streams, dict):
                        duration = streams.get("duration", 0)
                        if duration:
                            duration = duration // 1000
                            break
            
            # 提取所有视频流
            stream_info = video_info.get("media", {}).get("stream", {})
            
            # 存储所有可用格式
            all_streams = []
            
            for codec, streams in stream_info.items():
                # streams 可能是 dict 或 list
                if isinstance(streams, list):
                    for stream in streams:
                        if isinstance(stream, dict) and stream.get("masterUrl"):
                            all_streams.append({
                                "codec": codec,
                                "stream": stream,
                            })
                elif isinstance(streams, dict) and streams.get("masterUrl"):
                    all_streams.append({
                        "codec": codec,
                        "stream": streams,
                    })
            
            # 按文件大小排序（大的在前）
            all_streams.sort(key=lambda x: x["stream"].get("size", 0), reverse=True)
            
            # 创建格式列表
            for idx, item in enumerate(all_streams):
                stream = item["stream"]
                codec = item["codec"]
                
                width = stream.get("width")
                height = stream.get("height")
                resolution = f"{width}x{height}" if width and height else None
                
                size = stream.get("size", 0)
                
                # 生成格式 ID
                format_id = f"{codec}_{stream.get('streamType', idx)}"
                
                quality_label = stream.get("qualityType", "HD")
                quality_desc = f"{codec.upper()} {quality_label}"
                if size:
                    size_mb = size / (1024 * 1024)
                    quality_desc += f" ({size_mb:.1f}MB)"
                
                formats.append(VideoFormat(
                    format_id=format_id,
                    ext=stream.get("format", "mp4"),
                    resolution=resolution,
                    filesize=size,
                    vcodec=codec,
                    acodec=stream.get("audioCodec", "aac"),
                    fps=stream.get("fps"),
                    quality=quality_desc,
                    is_audio_only=False,
                    is_video_only=False,
                    # 存储下载 URL
                    url=stream.get("masterUrl"),
                ))
            
            # 如果没有找到格式，添加一个默认格式
            if not formats:
                for codec in ["h264", "h265", "av1"]:
                    if codec in stream_info:
                        stream = stream_info[codec]
                        if isinstance(stream, list) and stream:
                            stream = stream[0]
                        if isinstance(stream, dict) and stream.get("masterUrl"):
                            formats.append(VideoFormat(
                                format_id=codec,
                                ext="mp4",
                                resolution=None,
                                filesize=stream.get("size"),
                                vcodec=codec,
                                acodec="aac",
                                quality=f"{codec.upper()}",
                                is_audio_only=False,
                                is_video_only=False,
                                url=stream.get("masterUrl"),
                            ))
                            break
        else:
            # 图文笔记 - 下载图片到本地
            images = note_data.get("imageList") or note_data.get("imagesList") or []
            
            # 调用 _download_gallery_images 下载图片到本地
            local_images = await self._download_gallery_images(note_id, images)
            
            for idx, local_img in enumerate(local_images):
                width = local_img.get("width")
                height = local_img.get("height")
                resolution = f"{width}x{height}" if width and height else f"图片 {idx + 1}"
                
                # 获取扩展名
                ext = "jpg"
                url = local_img.get("url", "")
                if ".png" in url.lower():
                    ext = "png"
                elif ".webp" in url.lower():
                    ext = "webp"
                
                formats.append(VideoFormat(
                    format_id=f"image_{idx}",
                    ext=ext,
                    resolution=resolution,
                    filesize=None,
                    vcodec="none",
                    acodec="none",
                    quality="原图" if not (width and height) else f"原图 {width}x{height}",
                    is_audio_only=False,
                    is_video_only=False,
                    url=url,  # 本地静态文件 URL
                ))
        
        # 处理封面 URL（转 HTTPS）
        if cover and cover.startswith("http://"):
            cover = "https://" + cover[7:]
        
        return VideoInfo(
            id=note_id,
            title=title,
            description=description,
            thumbnail=cover,
            duration=duration,
            uploader=uploader,
            uploader_id=str(uploader_id),
            view_count=None,
            like_count=like_count,
            comment_count=comment_count,
            platform=Platform.XIAOHONGSHU,
            original_url=original_url,
            formats=formats,
            best_format=formats[0] if formats else None,
        )
    
    async def download_video(self, url: str, quality: str = "best",
                             format_id: Optional[str] = None,
                             audio_only: bool = False, **kwargs) -> str:
        """下载小红书内容
        
        Args:
            url: 视频 URL
            quality: 质量选择 (best, worst, 或具体格式ID)
            format_id: 指定格式 ID
            audio_only: 仅下载音频（小红书不支持）
        """
        original_url = url  # 保存原始 URL
        url = await self._resolve_short_url(url)
        
        note_id = self.extract_note_id(url)
        if not note_id:
            raise Exception(f"无法从 URL 提取笔记 ID: {url}")
        
        try:
            # 传递原始 URL 以保留查询参数
            initial_state = await self._fetch_note_info(note_id, original_url)
            note_data = self._extract_note_from_state(initial_state, note_id)
        except Exception as e:
            logger.warning(f"API 方式获取失败，使用 yt-dlp: {e}")
            return await self._download_with_ytdlp(url)
        
        if note_data.get("video"):
            return await self._download_video(note_data, note_id, format_id=format_id)
        else:
            return await self._download_images(note_data, note_id)
    
    def _extract_note_from_state(self, data: Dict[str, Any], note_id: str) -> Dict[str, Any]:
        """从 INITIAL_STATE 提取笔记数据"""
        note_state = data.get('note', {})
        note_map = note_state.get('noteDetailMap', {})
        
        if note_map:
            for key, value in note_map.items():
                if isinstance(value, dict) and 'note' in value:
                    inner_note = value['note']
                    if inner_note and (inner_note.get('title') or inner_note.get('video') or inner_note.get('imageList')):
                        return inner_note
        
        raise Exception("无法解析笔记数据结构")
    
    async def _download_video(self, note_data: Dict[str, Any], note_id: str, 
                               format_id: Optional[str] = None) -> str:
        """下载视频
        
        Args:
            note_data: 笔记数据
            note_id: 笔记 ID
            format_id: 指定的格式 ID（如 h264_259, h265_115）
        """
        video_info = note_data.get("video", {})
        stream_info = video_info.get("media", {}).get("stream", {})
        
        # 收集所有可用流
        all_streams = []
        for codec, streams in stream_info.items():
            if isinstance(streams, list):
                for stream in streams:
                    if isinstance(stream, dict) and stream.get("masterUrl"):
                        all_streams.append({
                            "codec": codec,
                            "stream": stream,
                            "format_id": f"{codec}_{stream.get('streamType', '')}",
                        })
            elif isinstance(streams, dict) and streams.get("masterUrl"):
                all_streams.append({
                    "codec": codec,
                    "stream": streams,
                    "format_id": f"{codec}_{streams.get('streamType', '')}",
                })
        
        # 按文件大小排序（大的在前）
        all_streams.sort(key=lambda x: x["stream"].get("size", 0), reverse=True)
        
        # 选择要下载的流
        selected_stream = None
        
        if format_id:
            # 尝试匹配指定的格式 ID
            for item in all_streams:
                if item["format_id"] == format_id:
                    selected_stream = item
                    break
            
            if not selected_stream:
                # 尝试部分匹配
                for item in all_streams:
                    if format_id in item["format_id"] or item["codec"] == format_id:
                        selected_stream = item
                        break
        
        if not selected_stream and all_streams:
            # 默认选择最大的（最清晰的）
            selected_stream = all_streams[0]
        
        if not selected_stream:
            raise Exception("无法获取视频下载地址")
        
        video_url = selected_stream["stream"].get("masterUrl")
        stream_size = selected_stream["stream"].get("size", 0)
        codec = selected_stream["codec"]
        
        # 转换为 HTTPS
        if video_url and video_url.startswith("http://"):
            video_url = "https://" + video_url[7:]
        
        title = self.sanitize_filename(note_data.get("title") or note_data.get("desc", "")[:30] or "xiaohongshu")
        filename = f"{title}_{note_id}.mp4"
        filepath = self.download_dir / filename
        
        size_mb = stream_size / (1024 * 1024) if stream_size else "未知"
        logger.info(f"开始下载小红书视频: {filename} ({codec.upper()}, {size_mb}MB)")
        
        headers = self._get_headers()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, headers=headers, proxy=self.proxy, timeout=120) as response:
                if response.status != 200:
                    raise Exception(f"下载失败: HTTP {response.status}")
                
                with open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
        
        logger.info(f"小红书视频下载完成: {filename}")
        return str(filepath)
    
    async def _download_images(self, note_data: Dict[str, Any], note_id: str) -> str:
        """下载图片"""
        images = note_data.get("imageList") or note_data.get("imagesList") or []
        
        if not images:
            raise Exception("没有找到图片")
        
        title = self.sanitize_filename(note_data.get("title") or note_data.get("desc", "")[:30] or "xiaohongshu")
        save_dir = self.download_dir / f"{title}_{note_id}"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"开始下载小红书图文: {len(images)} 张图片")
        
        headers = self._get_headers()
        
        async with aiohttp.ClientSession() as session:
            for idx, img in enumerate(images, start=1):
                img_url = img.get("urlDefault") or img.get("url")
                if not img_url:
                    continue
                
                if img_url.startswith("http://"):
                    img_url = "https://" + img_url[7:]
                
                ext = ".jpg"
                if ".png" in img_url.lower():
                    ext = ".png"
                elif ".webp" in img_url.lower():
                    ext = ".webp"
                
                img_path = save_dir / f"{idx:02d}{ext}"
                
                async with session.get(img_url, headers=headers, proxy=self.proxy, timeout=30) as response:
                    if response.status == 200:
                        with open(img_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        logger.debug(f"已下载图片 {idx}/{len(images)}")
        
        logger.info(f"小红书图文下载完成: {save_dir}")
        return str(save_dir)
    
    async def _download_with_ytdlp(self, url: str) -> str:
        """使用 yt-dlp 下载"""
        task_id = f"xhs_{os.urandom(4).hex()}"
        self._progress_store[task_id] = DownloadProgress(task_id)
        
        options = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(self.download_dir / "%(title).80s_%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
        }
        
        if self.proxy:
            options["proxy"] = self.proxy
        
        options["progress_hooks"] = [self._get_progress_hook(task_id)]
        
        logger.info(f"使用 yt-dlp 下载小红书: {url}")
        
        loop = asyncio.get_event_loop()
        
        def _download():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.download([url])
        
        try:
            result = await loop.run_in_executor(self._executor, _download)
            
            if result != 0:
                raise Exception(f"下载失败，返回码: {result}")
            
            progress = self._progress_store.get(task_id)
            if progress and progress.filename:
                filepath = self.download_dir / progress.filename
                if filepath.exists():
                    return str(filepath)
            
            files = sorted(self.download_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
            if files:
                return str(files[0])
            
            raise Exception("无法找到下载的文件")
        finally:
            self._progress_store.pop(task_id, None)
    
    def raw_to_video_info(self, raw_info: Dict[str, Any], url: str, platform: Platform) -> VideoInfo:
        """将 yt-dlp 返回的原始信息转换为 VideoInfo"""
        formats = []
        seen_formats = set()  # 用于去重
        
        for fmt in raw_info.get("formats", []):
            if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
                continue
            
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            resolution = self._get_resolution(fmt)
            vcodec = fmt.get("vcodec") or "none"
            acodec = fmt.get("acodec") or "none"
            
            # 创建去重 key（分辨率+文件大小+编码）
            dedup_key = (resolution, filesize, vcodec, acodec)
            if dedup_key in seen_formats:
                continue
            seen_formats.add(dedup_key)
            
            video_format = VideoFormat(
                format_id=fmt.get("format_id", ""),
                ext=fmt.get("ext", "mp4"),
                resolution=resolution,
                filesize=filesize,
                filesize_approx=fmt.get("filesize_approx"),
                vcodec=vcodec,
                acodec=acodec,
                fps=fmt.get("fps"),
                quality=fmt.get("format_note") or fmt.get("quality_label"),
                is_audio_only=fmt.get("vcodec") == "none",
                is_video_only=fmt.get("acodec") == "none",
            )
            formats.append(video_format)
        
        formats.sort(key=lambda f: int(f.resolution.split('x')[-1]) if f.resolution and 'x' in f.resolution else 0, reverse=True)
        
        best_format = formats[0] if formats else None
        
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
            view_count=raw_info.get("view_count"),
            like_count=raw_info.get("like_count"),
            comment_count=raw_info.get("comment_count"),
            platform=platform,
            original_url=url,
            formats=formats,
            best_format=best_format,
        )
    
    @staticmethod
    def _get_resolution(fmt: Dict) -> Optional[str]:
        width = fmt.get("width")
        height = fmt.get("height")
        if width and height:
            return f"{width}x{height}"
        if height:
            return f"{height}p"
        return None
    
    def _get_progress_hook(self, task_id: str):
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
            elif d["status"] == "error":
                progress.status = "error"
                progress.error = str(d.get("error", "未知错误"))
        return hook
    
    @staticmethod
    def _format_speed(speed: float) -> str:
        if speed < 1024:
            return f"{speed:.0f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.1f} MB/s"
    
    @staticmethod
    def _format_eta(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            return f"{seconds // 60}分{seconds % 60}秒"
        else:
            return f"{seconds // 3600}时{(seconds % 3600) // 60}分"