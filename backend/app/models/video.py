"""
视频相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class Platform(str, Enum):
    """支持的平台枚举"""
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    WEIBO = "weibo"
    XIAOHONGSHU = "xiaohongshu"
    OTHER = "other"


class VideoFormat(BaseModel):
    """视频格式信息"""
    format_id: str = Field(..., description="格式ID")
    ext: str = Field(..., description="文件扩展名")
    resolution: Optional[str] = Field(None, description="分辨率，如 1920x1080")
    filesize: Optional[int] = Field(None, description="文件大小（字节）")
    filesize_approx: Optional[int] = Field(None, description="预估文件大小")
    vcodec: Optional[str] = Field(None, description="视频编码")
    acodec: Optional[str] = Field(None, description="音频编码")
    fps: Optional[float] = Field(None, description="帧率")
    quality: Optional[str] = Field(None, description="质量描述")
    is_audio_only: bool = Field(default=False, description="是否仅音频")
    is_video_only: bool = Field(default=False, description="是否仅视频")
    url: Optional[str] = Field(None, description="直接下载URL（某些平台可用）")
    needs_merge: bool = Field(default=False, description="是否需要合并音视频")
    has_audio: bool = Field(default=True, description="是否包含音频")
    has_video: bool = Field(default=True, description="是否包含视频")


class VideoInfo(BaseModel):
    """视频信息"""
    id: str = Field(..., description="视频ID")
    title: str = Field(..., description="视频标题")
    description: Optional[str] = Field(None, description="视频描述")
    thumbnail: Optional[str] = Field(None, description="封面图URL")
    duration: Optional[float] = Field(None, description="时长（秒）")
    uploader: Optional[str] = Field(None, description="上传者")
    uploader_id: Optional[str] = Field(None, description="上传者ID")
    upload_date: Optional[str] = Field(None, description="上传日期")
    view_count: Optional[int] = Field(None, description="播放量")
    like_count: Optional[int] = Field(None, description="点赞数")
    comment_count: Optional[int] = Field(None, description="评论数")
    platform: Platform = Field(default=Platform.OTHER, description="平台")
    original_url: str = Field(..., description="原始URL")
    formats: List[VideoFormat] = Field(default_factory=list, description="可用格式列表")
    best_format: Optional[VideoFormat] = Field(None, description="最佳格式")
    has_direct_url: bool = Field(default=False, description="是否有可直接下载的完整文件URL")
    needs_processing: bool = Field(default=False, description="是否需要服务器处理（合并/转换）")


class DownloadRequest(BaseModel):
    """下载请求"""
    url: str = Field(..., description="视频URL")
    format_id: Optional[str] = Field(None, description="指定格式ID")
    quality: str = Field(default="best", description="质量选择: best, 1080p, 720p, 480p, audio")
    audio_only: bool = Field(default=False, description="仅下载音频")
    cookies: Optional[str] = Field(None, description="Cookie字符串（抖音等平台需要）")
    video_title: Optional[str] = Field(None, description="视频标题（用于精确匹配下载文件）")
    video_id: Optional[str] = Field(None, description="视频ID（用于精确匹配下载文件）")


class DownloadResponse(BaseModel):
    """下载响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    file_path: Optional[str] = Field(None, description="下载文件路径")
    file_name: Optional[str] = Field(None, description="文件名")
    file_size: Optional[int] = Field(None, description="文件大小")


class ParseRequest(BaseModel):
    """解析请求"""
    url: str = Field(..., description="视频URL")
    cookies: Optional[str] = Field(None, description="Cookie字符串（抖音等平台需要）")


class ParseResponse(BaseModel):
    """解析响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    video_info: Optional[VideoInfo] = Field(None, description="视频信息")


class ProgressInfo(BaseModel):
    """下载进度信息"""
    task_id: str = Field(..., description="任务ID")
    status: str = Field(..., description="状态: downloading, finished, error")
    progress: float = Field(..., description="进度百分比 0-100")
    speed: Optional[str] = Field(None, description="下载速度")
    eta: Optional[str] = Field(None, description="预计剩余时间")
    downloaded: Optional[int] = Field(None, description="已下载字节数")
    total: Optional[int] = Field(None, description="总字节数")
    filename: Optional[str] = Field(None, description="文件名")
    error: Optional[str] = Field(None, description="错误信息")


class DownloadProgress:
    """下载进度跟踪类（内部使用）"""
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status: str = "pending"
        self.progress: float = 0.0
        self.speed: Optional[str] = None
        self.eta: Optional[str] = None
        self.downloaded: Optional[int] = None
        self.total: Optional[int] = None
        self.filename: Optional[str] = None
        self.error: Optional[str] = None
