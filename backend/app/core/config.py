"""
应用配置模块
适配 Pydantic 2.7.0+
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional
import os


class Settings(BaseSettings):
    """应用设置"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 应用基础配置
    APP_NAME: str = "Video Downloader API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False)
    
    # 服务器配置
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    
    # 下载配置
    DOWNLOAD_DIR: str = Field(default="downloads")
    MAX_CONCURRENT_DOWNLOADS: int = Field(default=20)
    
    # 下载文件清理配置
    CLEANUP_ENABLED: bool = Field(default=True, description="是否启用下载文件清理")
    CLEANUP_MAX_AGE_DAYS: int = Field(default=7, description="文件最大保留天数")
    CLEANUP_MAX_SIZE_MB: int = Field(default=5000, description="下载目录最大大小 MB")
    
    # HTTP 客户端配置
    HTTP_TIMEOUT: int = Field(default=30, description="HTTP 请求超时时间（秒）")
    HTTP_CONNECT_TIMEOUT: int = Field(default=10, description="HTTP 连接超时时间（秒）")
    
    # 请求限流配置
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="是否启用请求限流")
    RATE_LIMIT_PER_MINUTE: int = Field(default=30, description="每分钟请求限制")
    
    # CORS 配置
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173", "http://192.168.10.150:5173"]
    )
    CORS_ALLOW_METHODS: list[str] = Field(
        default=["GET", "POST", "DELETE", "OPTIONS"]
    )
    CORS_ALLOW_HEADERS: list[str] = Field(
        default=["Content-Type", "Authorization", "X-Request-ID"]
    )
    
    # yt-dlp 配置
    YT_DLP_CACHE_DIR: Optional[str] = Field(default=None)
    
    # 代理配置 (支持 HTTP/SOCKS5)
    # 例如: http://127.0.0.1:7890 或 socks5://127.0.0.1:7890
    PROXY_URL: Optional[str] = Field(default=None)
    
    # Redis 配置
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_ENABLED: bool = Field(default=True)
    REDIS_MAX_CONNECTIONS: int = Field(default=50, description="Redis 最大连接数")
    
    # 缓存配置
    CACHE_EXPIRE_SECONDS: int = Field(default=3600)  # 缓存1小时
    
    # Celery 配置
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/2")
    
    # API 安全配置
    API_KEY: Optional[str] = Field(default=None, description="API 密钥（可选，用于接口认证）")
    API_KEY_ENABLED: bool = Field(default=False, description="是否启用 API Key 认证")
    IP_WHITELIST: list[str] = Field(default_factory=list, description="IP 白名单")
    
    # 代理白名单域名
    PROXY_ALLOWED_DOMAINS: list[str] = Field(
        default=["douyinpic.com", "xiaohongshu.com", "xhscdn.com"],
        description="图片代理允许的域名"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 确保下载目录存在
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
        # 确保日志目录存在
        os.makedirs("logs", exist_ok=True)
    
    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v):
        """解析 DEBUG 值"""
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)
    
    @field_validator("IP_WHITELIST", "PROXY_ALLOWED_DOMAINS", mode="before")
    @classmethod
    def parse_string_list(cls, v):
        """解析列表类型字段，处理空字符串或逗号分隔格式"""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # 支持 JSON 数组格式
            if v.startswith("["):
                import json
                return json.loads(v)
            # 支持逗号分隔格式
            return [item.strip() for item in v.split(",") if item.strip()]
        return []


# 全局配置实例
settings = Settings()