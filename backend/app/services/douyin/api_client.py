"""
抖音 API 客户端
基于 jiji262/douyin-downloader 项目
用于解析抖音视频信息并获取无水印下载链接
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import aiohttp
from loguru import logger

from .xbogus import XBogus
from .cookie_utils import sanitize_cookies

# 可选导入 ABogus
try:
    from .abogus import ABogus, BrowserFingerprintGenerator
    ABOGUS_AVAILABLE = True
except ImportError:
    ABOGUS_AVAILABLE = False
    ABogus = None
    BrowserFingerprintGenerator = None

# 可选导入 MsTokenManager
try:
    from .ms_token_manager import MsTokenManager
    MSTOKEN_AVAILABLE = True
except ImportError:
    MSTOKEN_AVAILABLE = False
    MsTokenManager = None


_USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


class DouyinAPIClient:
    """抖音 Web API 客户端
    
    支持功能：
    - 视频详情获取
    - 短链接解析
    - 无水印视频 URL 构建
    - URL 签名（X-Bogus / A-Bogus）
    - msToken 自动生成
    """
    
    BASE_URL = "https://www.douyin.com"
    
    # 浏览器 Cookie 黑名单（不在浏览器模式下设置的敏感 Cookie）
    _BROWSER_COOKIE_BLOCKLIST = {
        "sessionid",
        "sessionid_ss",
        "sid_tt",
        "sid_guard",
        "uid_tt",
        "uid_tt_ss",
        "passport_auth_status",
        "passport_auth_status_ss",
        "passport_assist_user",
        "passport_auth_mix_state",
        "passport_mfa_token",
        "login_time",
    }
    
    def __init__(self, cookies: Optional[Dict[str, str]] = None, proxy: Optional[str] = None):
        self.cookies = sanitize_cookies(cookies or {})
        self.proxy = str(proxy or "").strip() if proxy else None
        self._session: Optional[aiohttp.ClientSession] = None
        
        selected_ua = random.choice(_USER_AGENT_POOL)
        self.headers = {
            "User-Agent": selected_ua,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }
        
        self._signer = XBogus(self.headers["User-Agent"])
        self._ms_token = self.cookies.get("msToken", "")
        
        # 初始化 MsTokenManager
        if MSTOKEN_AVAILABLE and MsTokenManager:
            self._ms_token_manager = MsTokenManager(user_agent=self.headers["User-Agent"])
        else:
            self._ms_token_manager = None
        
        self._abogus_enabled = ABOGUS_AVAILABLE and ABogus is not None and BrowserFingerprintGenerator is not None
    
    async def __aenter__(self) -> "DouyinAPIClient":
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
    
    async def _ensure_session(self):
        """确保 aiohttp session 已创建"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.headers,
                cookies=self.cookies,
                timeout=aiohttp.ClientTimeout(total=30),
                raise_for_status=False,
            )
    
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_session(self) -> aiohttp.ClientSession:
        """获取 session"""
        await self._ensure_session()
        if self._session is None:
            raise RuntimeError("Failed to create aiohttp session")
        return self._session
    
    async def _ensure_ms_token(self) -> str:
        """确保有有效的 msToken"""
        if self._ms_token:
            return self._ms_token
        
        # 尝试生成真实 msToken
        if self._ms_token_manager:
            try:
                token = await asyncio.to_thread(
                    self._ms_token_manager.ensure_ms_token,
                    self.cookies,
                )
                self._ms_token = token.strip()
                if self._ms_token:
                    self.cookies["msToken"] = self._ms_token
                    if self._session and not self._session.closed:
                        self._session.cookie_jar.update_cookies({"msToken": self._ms_token})
                    return self._ms_token
            except Exception as e:
                logger.warning(f"生成 msToken 失败: {e}")
        
        # 回退到假 token
        self._ms_token = self._gen_false_ms_token()
        return self._ms_token
    
    @staticmethod
    def _gen_false_ms_token() -> str:
        """生成假的 msToken"""
        import string
        token = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="
        return token
    
    async def _default_query(self) -> Dict[str, Any]:
        """获取默认请求参数"""
        ms_token = await self._ensure_ms_token()
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "123.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "123.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "8",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "msToken": ms_token,
        }
    
    def sign_url(self, url: str) -> Tuple[str, str]:
        """对 URL 进行 X-Bogus 签名
        
        Args:
            url: 原始 URL
            
        Returns:
            (签名后的URL, User-Agent)
        """
        signed_url, _xbogus, ua = self._signer.build(url)
        return signed_url, ua
    
    def build_signed_path(self, path: str, params: Dict[str, Any]) -> Tuple[str, str]:
        """构建签名的请求路径
        
        Args:
            path: API 路径
            params: 请求参数
            
        Returns:
            (签名后的完整URL, User-Agent)
        """
        query = urlencode(params)
        base_url = f"{self.BASE_URL}{path}"
        
        # 尝试使用 A-Bogus（更高级的签名）
        if self._abogus_enabled and ABogus and BrowserFingerprintGenerator:
            try:
                browser_fp = BrowserFingerprintGenerator.generate_fingerprint("Edge")
                signer = ABogus(fp=browser_fp, user_agent=self.headers["User-Agent"])
                params_with_ab, _ab, ua, _body = signer.generate_abogus(query, "")
                return f"{base_url}?{params_with_ab}", ua
            except Exception as exc:
                logger.debug(f"A-Bogus 生成失败，回退到 X-Bogus: {exc}")
        
        return self.sign_url(f"{base_url}?{query}")
    
    async def _request_json(
        self,
        path: str,
        params: Dict[str, Any],
        *,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """发送 JSON 请求
        
        Args:
            path: API 路径
            params: 请求参数
            max_retries: 最大重试次数
            
        Returns:
            JSON 响应数据
        """
        await self._ensure_session()
        delays = [1, 2, 5]
        last_exc: Optional[Exception] = None
        
        for attempt in range(max_retries):
            signed_url, ua = self.build_signed_path(path, params)
            try:
                async with self._session.get(
                    signed_url,
                    headers={**self.headers, "User-Agent": ua},
                    proxy=self.proxy,
                ) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        return data if isinstance(data, dict) else {}
                    
                    if response.status < 500 and response.status != 429:
                        logger.error(f"请求失败: path={path}, status={response.status}")
                        return {}
                    
                    last_exc = RuntimeError(f"HTTP {response.status} for {path}")
            except Exception as exc:
                last_exc = exc
            
            if attempt < max_retries - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.debug(f"请求重试 {attempt + 1}/{max_retries} for {path} in {delay}s")
                await asyncio.sleep(delay)
        
        logger.error(f"请求失败 after {max_retries} attempts: path={path}, error={last_exc}")
        return {}
    
    async def get_video_detail(self, aweme_id: str) -> Optional[Dict[str, Any]]:
        """
        获取视频详情
        
        Args:
            aweme_id: 视频ID
            
        Returns:
            视频详情数据（aweme_detail），如果失败返回 None
            
        Raises:
            Exception: 当 Cookie 不完整或 API 返回错误时
        """
        # 检查关键 Cookie
        required_cookies = ['ttwid']
        missing_cookies = [c for c in required_cookies if c not in self.cookies]
        
        if missing_cookies:
            logger.warning(f"缺少关键 Cookie: {missing_cookies}，可能导致解析失败")
        
        params = await self._default_query()
        params.update({
            "aweme_id": aweme_id,
            "aid": "1128",
        })
        
        data = await self._request_json("/aweme/v1/web/aweme/detail/", params)
        if data:
            aweme_detail = data.get("aweme_detail")
            if aweme_detail:
                return aweme_detail
            else:
                # 检查是否被限流
                status_msg = data.get("status_msg", "")
                status_code = data.get("status_code", 0)
                if status_msg:
                    raise Exception(f"抖音 API 返回错误: {status_msg} (code: {status_code})")
                logger.warning(f"抖音 API 返回空数据，可能需要更完整的 Cookie")
                return None
        
        # 如果完全无响应，给出提示
        if missing_cookies:
            raise Exception(f"解析失败，请提供完整的抖音 Cookie。缺少关键字段: {missing_cookies}")
        
        return None
    
    async def resolve_short_url(self, short_url: str) -> Optional[str]:
        """
        解析短链接
        
        Args:
            short_url: 短链接（如 v.douyin.com）
            
        Returns:
            真实 URL
        """
        try:
            await self._ensure_session()
            async with self._session.get(
                short_url,
                allow_redirects=True,
                proxy=self.proxy,
            ) as response:
                return str(response.url)
        except Exception as e:
            logger.error(f"解析短链接失败: {short_url}, error: {e}")
            return None
    
    @staticmethod
    def extract_aweme_id(url: str) -> Optional[str]:
        """
        从 URL 中提取视频 ID
        
        Args:
            url: 视频 URL
            
        Returns:
            视频 ID (aweme_id)
        """
        # 匹配 /video/xxxxxxxxxx
        match = re.search(r'/video/(\d+)', url)
        if match:
            return match.group(1)
        
        # 匹配 modal_id=xxxxxxxxxx
        match = re.search(r'modal_id=(\d+)', url)
        if match:
            return match.group(1)
        
        # 匹配 /note/xxxxxxxxxx（图文）
        match = re.search(r'/note/(\d+)', url)
        if match:
            return match.group(1)
        
        return None
    
    def build_no_watermark_url(self, aweme_data: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, str]]]:
        """
        构建无水印视频下载 URL（默认最高清晰度）
        
        Args:
            aweme_data: 视频详情数据
            
        Returns:
            (下载URL, 请求头) 或 None
        """
        return self._build_video_url(aweme_data, format_id=None)
    
    def build_bitrate_url(self, aweme_data: Dict[str, Any], format_id: str) -> Optional[Tuple[str, Dict[str, str]]]:
        """
        构建指定清晰度的视频下载 URL
        
        Args:
            aweme_data: 视频详情数据
            format_id: 清晰度标识（如 "720_1_1", "540_1_1"）
            
        Returns:
            (下载URL, 请求头) 或 None
        """
        return self._build_video_url(aweme_data, format_id=format_id)
    
    def _build_video_url(self, aweme_data: Dict[str, Any], format_id: Optional[str] = None) -> Optional[Tuple[str, Dict[str, str]]]:
        """
        构建视频下载 URL
        
        Args:
            aweme_data: 视频详情数据
            format_id: 清晰度标识，None 表示最高清晰度
                       支持: "1080p", "720_1_1", "540_1_1" 等
            
        Returns:
            (下载URL, 请求头) 或 None
        """
        video = aweme_data.get("video", {})
        headers = {
            "Referer": f"{self.BASE_URL}/",
            "Origin": self.BASE_URL,
            "User-Agent": self.headers["User-Agent"],
        }
        
        # 获取视频 URI（用于构建 1080p URL）
        video_uri = (
            video.get("play_addr", {}).get("uri")
            or video.get("vid")
            or video.get("download_addr", {}).get("uri")
        )
        
        # 如果请求 1080p，直接使用 /aweme/v1/play/ 接口
        if format_id == "1080p" and video_uri:
            params = {
                "video_id": video_uri,
                "ratio": "1080p",
                "line": "0",
                "is_play_url": "1",
                "watermark": "0",
                "source": "PackSourceEnum_PUBLISH",
            }
            signed_url, ua = self.build_signed_path("/aweme/v1/play/", params)
            headers["User-Agent"] = ua
            logger.info(f"构建 1080p 视频下载链接: video_id={video_uri}")
            return signed_url, headers
        
        # 如果指定了 format_id，从 bit_rate 数组中查找
        if format_id:
            bit_rate_list = video.get("bit_rate", [])
            if bit_rate_list and isinstance(bit_rate_list, list):
                for br_item in bit_rate_list:
                    gear_name = br_item.get("gear_name", "")
                    if gear_name == format_id:
                        play_addr = br_item.get("play_addr", {})
                        if isinstance(play_addr, dict):
                            url_list = play_addr.get("url_list", [])
                            if url_list:
                                candidate = url_list[0]
                                parsed = urlparse(candidate)
                                
                                if parsed.netloc.endswith("douyin.com") or "amemv.com" in parsed.netloc:
                                    if "X-Bogus=" not in candidate:
                                        signed_url, ua = self.sign_url(candidate)
                                        headers["User-Agent"] = ua
                                        return signed_url, headers
                                
                                return candidate, headers
        
        # 回退到原有逻辑：使用 play_addr
        play_addr = video.get("play_addr", {})
        url_candidates = [c for c in (play_addr.get("url_list") or []) if c]
        
        # 优先选择无水印的 URL
        url_candidates.sort(key=lambda u: 0 if "watermark=0" in u else 1)
        
        fallback_candidate: Optional[Tuple[str, Dict[str, str]]] = None
        
        for candidate in url_candidates:
            parsed = urlparse(candidate)
            
            # 如果是抖音域名，需要签名
            if parsed.netloc.endswith("douyin.com"):
                if "X-Bogus=" not in candidate:
                    signed_url, ua = self.sign_url(candidate)
                    headers["User-Agent"] = ua
                    return signed_url, headers
                return candidate, headers
            
            # 非抖音域名的 URL 直接使用
            fallback_candidate = (candidate, headers.copy())
        
        # 尝试通过 vid 构建 URL（默认最高清晰度）
        if video_uri:
            params = {
                "video_id": video_uri,
                "ratio": "1080p",
                "line": "0",
                "is_play_url": "1",
                "watermark": "0",
                "source": "PackSourceEnum_PUBLISH",
            }
            signed_url, ua = self.build_signed_path("/aweme/v1/play/", params)
            headers["User-Agent"] = ua
            logger.info(f"构建默认视频下载链接: video_id={video_uri}")
            return signed_url, headers
        
        if fallback_candidate:
            return fallback_candidate
        
        return None
    
    async def get_1080p_filesize(self, aweme_data: Dict[str, Any]) -> Optional[int]:
        """
        获取 1080p 视频的文件大小
        
        通过发送 GET 请求获取 Content-Length（抖音不支持 HEAD 请求）
        
        Args:
            aweme_data: 视频详情数据
            
        Returns:
            文件大小（字节）或 None
        """
        video = aweme_data.get("video", {})
        
        # 获取视频 URI
        video_uri = (
            video.get("play_addr", {}).get("uri")
            or video.get("vid")
            or video.get("download_addr", {}).get("uri")
        )
        
        if not video_uri:
            return None
        
        # 构建 1080p URL
        params = {
            "video_id": video_uri,
            "ratio": "1080p",
            "line": "0",
            "is_play_url": "1",
            "watermark": "0",
            "source": "PackSourceEnum_PUBLISH",
        }
        signed_url, ua = self.build_signed_path("/aweme/v1/play/", params)
        
        try:
            import aiohttp
            # 使用新的 session 发送 GET 请求（抖音不支持 HEAD）
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    signed_url,
                    headers={**self.headers, "User-Agent": ua},
                    proxy=self.proxy,
                ) as response:
                    if response.status == 200:
                        content_length = response.headers.get("Content-Length")
                        if content_length:
                            return int(content_length)
        except Exception as e:
            logger.debug(f"获取 1080p 文件大小失败: {e}")
        
        return None
    
    def detect_media_type(self, aweme_data: Dict[str, Any]) -> str:
        """
        检测媒体类型
        
        Args:
            aweme_data: 视频详情数据
            
        Returns:
            'video' 或 'gallery'（图文）
        """
        if aweme_data.get("image_post_info") or aweme_data.get("images"):
            return "gallery"
        return "video"
    
    def extract_image_urls(self, aweme_data: Dict[str, Any]) -> List[str]:
        """
        提取图文作品的图片 URL 列表
        
        Args:
            aweme_data: 视频详情数据
            
        Returns:
            图片 URL 列表
        """
        image_urls = []
        
        # 从 image_post_info 提取
        image_post = aweme_data.get("image_post_info", {})
        images = image_post.get("images") or aweme_data.get("images") or []
        
        for item in images if isinstance(images, list) else []:
            if not isinstance(item, dict):
                continue
            
            img_url = None
            
            # 尝试多个可能的 URL 字段（按优先级排序）
            url_fields = [
                "display_image",           # 显示图片
                "owner_watermark_image",   # 水印图片
                "download_url",            # 下载 URL
                "download_addr",           # 下载地址
                "url_list",                # 直接的 URL 列表
                "urlList",                 # URL 列表（驼峰命名）
            ]
            
            for url_field in url_fields:
                url_data = item.get(url_field)
                if isinstance(url_data, dict):
                    # 从字典中提取 url_list
                    for list_field in ["url_list", "urlList"]:
                        url_list = url_data.get(list_field, [])
                        if url_list and isinstance(url_list, list) and url_list[0]:
                            img_url = url_list[0]
                            break
                elif isinstance(url_data, list) and url_data:
                    img_url = url_data[0]
                elif isinstance(url_data, str) and url_data:
                    img_url = url_data
                
                if img_url:
                    break
            
            # 如果有 base64 数据，优先使用
            if item.get("base64"):
                img_url = item["base64"]
            
            if img_url:
                image_urls.append(img_url)
        
        # 去重
        return list(dict.fromkeys(image_urls))


def parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    """
    解析 Cookie 字符串为字典
    
    Args:
        cookie_string: Cookie 字符串（如 "name1=value1; name2=value2"）
        
    Returns:
        Cookie 字典
    """
    cookies = {}
    if not cookie_string:
        return cookies
    
    for item in cookie_string.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookies[name.strip()] = value.strip()
    
    return cookies