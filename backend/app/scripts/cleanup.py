"""
下载文件清理脚本
支持在项目启动时自动清理过期文件，同步清理 Redis 缓存

清理策略：
1. 扫描本地图片目录，获取所有已下载的文件
2. 检查 Redis 缓存，找出哪些文件没有对应的缓存（缓存已过期）
3. 删除无缓存关联的本地文件
4. 清理空目录
"""
import os
import json
import time
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Set, Dict
from loguru import logger
from ..core.config import settings

class DownloadCleaner:
    """下载文件清理器
    
    与 Redis 缓存同步：
    - 当 Redis 缓存过期后，自动删除对应的本地文件
    - 避免本地文件无限增长
    """
    
    # Redis 缓存 key 前缀
    CACHE_KEY_PREFIX = "video:parse:"
    
    def __init__(
        self,
        download_dir: str = settings.DOWNLOAD_DIR,
        max_size_mb: int = 5000,
        redis_url: Optional[str] = None,
        cache_expire_hours: int = 1,
    ):
        """
        Args:
            download_dir: 下载目录路径
            max_size_mb: 目录最大大小 MB（超过此大小将强制清理最旧文件）
            redis_url: Redis 连接 URL
            cache_expire_hours: 缓存过期时间（小时），用于判断文件是否应该保留
        """
        self.download_dir = Path(download_dir)
        self.max_size_mb = max_size_mb
        self.redis_url = redis_url
        self.cache_expire_hours = cache_expire_hours
        self._redis_client = None
    
    async def _get_redis_client(self):
        """获取 Redis 客户端"""
        if self._redis_client is None and self.redis_url:
            try:
                import redis.asyncio as redis
                self._redis_client = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except ImportError:
                logger.warning("Redis 库未安装，将只按文件时间清理")
                return None
            except Exception as e:
                logger.warning(f"Redis 连接失败: {e}")
                return None
        return self._redis_client
    
    async def close_redis(self):
        """关闭 Redis 连接"""
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None
    
    def get_dir_size(self) -> int:
        """获取目录总大小（字节）"""
        total_size = 0
        try:
            for root, dirs, files in os.walk(self.download_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
        except Exception as e:
            logger.warning(f"计算目录大小失败: {e}")
        return total_size
    
    def get_local_image_dirs(self) -> List[Tuple[Path, str, float]]:
        """获取所有本地图片目录
        
        Returns:
            List of (dir_path, content_id, mtime)
            content_id: 视频/笔记 ID（如 douyin/123456 -> 123456）
        """
        images_dir = self.download_dir / "images"
        if not images_dir.exists():
            return []
        
        result = []
        
        # 遍历平台目录
        for platform_dir in images_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            
            platform = platform_dir.name  # douyin, xiaohongshu 等
            
            # 遍历内容 ID 目录
            for content_dir in platform_dir.iterdir():
                if not content_dir.is_dir():
                    continue
                
                content_id = content_dir.name
                try:
                    # 使用目录的修改时间
                    mtime = content_dir.stat().st_mtime
                    result.append((content_dir, f"{platform}/{content_id}", mtime))
                except Exception:
                    pass
        
        return result
    
    async def get_cached_content_ids(self) -> Set[str]:
        """从 Redis 缓存中获取所有内容 ID
        
        缓存数据中 original_url 包含内容 ID，例如：
        - https://www.xiaohongshu.com/discovery/item/69be604a000000001a033053
        - https://www.douyin.com/video/123456789
        
        Returns:
            Set of "platform/content_id" strings
        """
        redis_client = await self._get_redis_client()
        if not redis_client:
            return set()
        
        cached_ids = set()
        
        try:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor,
                    match=f"{self.CACHE_KEY_PREFIX}*",
                    count=100
                )
                
                for key in keys:
                    try:
                        cache_value = await redis_client.get(key)
                        if not cache_value:
                            continue
                        
                        cache_data = json.loads(cache_value)
                        platform = cache_data.get("platform", "")
                        original_url = cache_data.get("original_url", "")
                        
                        # 从 URL 提取内容 ID
                        content_id = self._extract_content_id(original_url, platform)
                        if content_id:
                            cached_ids.add(f"{platform}/{content_id}")
                        
                    except Exception as e:
                        logger.debug(f"解析缓存 {key} 失败: {e}")
                
                if cursor == 0:
                    break
                    
        except Exception as e:
            logger.error(f"扫描 Redis 缓存失败: {e}")
        
        return cached_ids
    
    def _extract_content_id(self, url: str, platform: str) -> Optional[str]:
        """从 URL 提取内容 ID"""
        import re
        
        if platform == "xiaohongshu":
            # https://www.xiaohongshu.com/discovery/item/69be604a000000001a033053
            match = re.search(r'/item/([a-zA-Z0-9]+)', url)
            if match:
                return match.group(1)
            match = re.search(r'/explore/([a-zA-Z0-9]+)', url)
            if match:
                return match.group(1)
        
        elif platform == "douyin":
            # https://www.douyin.com/video/123456789
            match = re.search(r'/video/(\d+)', url)
            if match:
                return match.group(1)
        
        elif platform == "bilibili":
            # https://www.bilibili.com/video/BV1xxx
            match = re.search(r'/video/(BV[a-zA-Z0-9]+)', url)
            if match:
                return match.group(1)
        
        return None
    
    async def clean_orphan_files(self) -> Tuple[int, int]:
        """清理孤儿文件（没有缓存关联的本地文件）
        
        Returns:
            (删除目录数, 释放空间 bytes)
        """
        local_dirs = self.get_local_image_dirs()
        
        if not local_dirs:
            return 0, 0
        
        # 获取所有有缓存的内容 ID
        cached_ids = await self.get_cached_content_ids()
        
        deleted_count = 0
        freed_bytes = 0
        
        for dir_path, content_key, mtime in local_dirs:
            # 如果有缓存，跳过
            if content_key in cached_ids:
                continue
            
            # 没有缓存，检查是否超过缓存过期时间
            # 给一个缓冲时间（缓存过期时间的 2 倍）
            buffer_seconds = self.cache_expire_hours * 3600 * 2
            if time.time() - mtime < buffer_seconds:
                # 文件还比较新，可能缓存还没建立，跳过
                continue
            
            # 删除整个目录
            try:
                dir_size = sum(f.stat().st_size for f in dir_path.rglob("*") if f.is_file())
                shutil.rmtree(dir_path)
                deleted_count += 1
                freed_bytes += dir_size
                logger.debug(f"删除孤儿目录: {dir_path.name} ({dir_size / 1024:.1f} KB)")
            except Exception as e:
                logger.warning(f"删除目录失败 {dir_path}: {e}")
        
        return deleted_count, freed_bytes
    
    def clean_by_size(self) -> Tuple[int, int]:
        """按大小清理（删除最旧的文件直到目录大小低于限制）
        
        Returns:
            (删除目录数, 释放空间 bytes)
        """
        images_dir = self.download_dir / "images"
        if not images_dir.exists():
            return 0, 0
        
        max_size_bytes = self.max_size_mb * 1024 * 1024
        current_size = self.get_dir_size()
        
        if current_size <= max_size_bytes:
            return 0, 0
        
        # 获取所有图片目录，按修改时间排序（最旧的在前）
        local_dirs = sorted(self.get_local_image_dirs(), key=lambda x: x[2])
        
        deleted_count = 0
        freed_bytes = 0
        
        for dir_path, content_key, mtime in local_dirs:
            if current_size - freed_bytes <= max_size_bytes:
                break
            
            try:
                dir_size = sum(f.stat().st_size for f in dir_path.rglob("*") if f.is_file())
                shutil.rmtree(dir_path)
                deleted_count += 1
                freed_bytes += dir_size
                logger.debug(f"删除旧目录（空间限制）: {dir_path.name}")
            except Exception as e:
                logger.warning(f"删除目录失败 {dir_path}: {e}")
        
        return deleted_count, freed_bytes
    
    def clean_empty_dirs(self) -> int:
        """清理空目录"""
        if not self.download_dir.exists():
            return 0
        
        deleted_count = 0
        
        for root, dirs, files in os.walk(self.download_dir, topdown=False):
            for d in dirs:
                dir_path = Path(root) / d
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        deleted_count += 1
                        logger.debug(f"删除空目录: {dir_path}")
                except Exception as e:
                    logger.debug(f"删除目录失败 {dir_path}: {e}")
        
        return deleted_count
    
    async def cleanup_async(self) -> dict:
        """执行完整清理
        
        Returns:
            清理统计信息
        """
        start_time = time.time()
        initial_size = self.get_dir_size()
        
        logger.info(f"🧹 开始清理下载目录: {self.download_dir}")
        logger.info(f"   当前大小: {initial_size / 1024 / 1024:.2f} MB")
        logger.info(f"   空间限制: {self.max_size_mb} MB")
        
        total_dirs_deleted = 0
        total_freed_bytes = 0
        
        # 1. 清理孤儿文件（没有缓存关联的）
        orphan_deleted, orphan_freed = await self.clean_orphan_files()
        if orphan_deleted > 0:
            total_dirs_deleted += orphan_deleted
            total_freed_bytes += orphan_freed
            logger.info(f"   清理孤儿文件: 删除 {orphan_deleted} 个目录, 释放 {orphan_freed / 1024 / 1024:.2f} MB")
        
        # 2. 按大小清理
        size_deleted, size_freed = self.clean_by_size()
        if size_deleted > 0:
            total_dirs_deleted += size_deleted
            total_freed_bytes += size_freed
            logger.info(f"   按大小清理: 删除 {size_deleted} 个目录, 释放 {size_freed / 1024 / 1024:.2f} MB")
        
        # 3. 清理空目录
        dirs_deleted = self.clean_empty_dirs()
        if dirs_deleted > 0:
            logger.info(f"   清理空目录: {dirs_deleted} 个")
        
        final_size = self.get_dir_size()
        elapsed = time.time() - start_time
        
        # 关闭 Redis 连接
        await self.close_redis()
        
        result = {
            "success": True,
            "initial_size_mb": round(initial_size / 1024 / 1024, 2),
            "final_size_mb": round(final_size / 1024 / 1024, 2),
            "freed_mb": round(total_freed_bytes / 1024 / 1024, 2),
            "dirs_deleted": total_dirs_deleted,
            "empty_dirs_deleted": dirs_deleted,
            "elapsed_seconds": round(elapsed, 2),
        }
        
        logger.info(f"✅ 清理完成: 释放 {result['freed_mb']} MB, 耗时 {elapsed:.2f}s")
        
        return result
    
    def cleanup(self) -> dict:
        """执行完整清理（同步版本）"""
        return asyncio.run(self.cleanup_async())


# 需要导入 shutil
import shutil


async def run_cleanup_async(
    download_dir: str = "downloads",
    max_size_mb: int = 5000,
    redis_url: Optional[str] = None,
    cache_expire_hours: int = 1,
) -> dict:
    """便捷函数：执行清理（异步）"""
    cleaner = DownloadCleaner(
        download_dir=download_dir,
        max_size_mb=max_size_mb,
        redis_url=redis_url,
        cache_expire_hours=cache_expire_hours,
    )
    return await cleaner.cleanup_async()


def run_cleanup(
    download_dir: str = "downloads",
    max_size_mb: int = 5000,
    redis_url: Optional[str] = None,
    cache_expire_hours: int = 1,
) -> dict:
    """便捷函数：执行清理（同步）"""
    return asyncio.run(run_cleanup_async(
        download_dir=download_dir,
        max_size_mb=max_size_mb,
        redis_url=redis_url,
        cache_expire_hours=cache_expire_hours,
    ))


# 命令行入口
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="清理下载文件")
    parser.add_argument("--dir", default="downloads", help="下载目录路径")
    parser.add_argument("--max-size", type=int, default=5000, help="目录最大大小 MB")
    parser.add_argument("--redis-url", default=None, help="Redis 连接 URL")
    parser.add_argument("--cache-hours", type=int, default=1, help="缓存过期时间（小时）")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要删除的内容")
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), format="{message}")
    
    async def main():
        cleaner = DownloadCleaner(
            download_dir=args.dir,
            max_size_mb=args.max_size,
            redis_url=args.redis_url,
            cache_expire_hours=args.cache_hours,
        )
        
        if args.dry_run:
            # 显示统计信息
            local_dirs = cleaner.get_local_image_dirs()
            print(f"\n本地目录统计:")
            print(f"  图片目录数: {len(local_dirs)}")
            print(f"  总大小: {cleaner.get_dir_size() / 1024 / 1024:.2f} MB\n")
            
            # 获取缓存信息
            cached_ids = await cleaner.get_cached_content_ids()
            print(f"Redis 缓存统计:")
            print(f"  缓存内容数: {len(cached_ids)}\n")
            
            # 显示孤儿目录
            buffer_seconds = args.cache_hours * 3600 * 2
            orphan_dirs = []
            for dir_path, content_key, mtime in local_dirs:
                if content_key not in cached_ids and time.time() - mtime >= buffer_seconds:
                    dir_size = sum(f.stat().st_size for f in dir_path.rglob("*") if f.is_file())
                    orphan_dirs.append((dir_path, dir_size, datetime.fromtimestamp(mtime)))
            
            if orphan_dirs:
                print(f"孤儿目录（无缓存关联，可删除）:")
                for dir_path, dir_size, mtime in orphan_dirs[:10]:
                    print(f"  {dir_path.name} - {mtime} - {dir_size / 1024:.1f} KB")
                if len(orphan_dirs) > 10:
                    print(f"  ... 还有 {len(orphan_dirs) - 10} 个目录")
                print(f"\n总计可释放: {sum(d[1] for d in orphan_dirs) / 1024 / 1024:.2f} MB")
            
            await cleaner.close_redis()
        else:
            result = await cleaner.cleanup_async()
            print(f"\n清理结果: {result}")
    
    asyncio.run(main())
