"""
下载文件清理脚本
支持在项目启动时自动清理过期文件
"""
import os
import shutil
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from loguru import logger


class DownloadCleaner:
    """下载文件清理器
    
    功能：
    1. 清理超过指定天数的下载文件
    2. 清理超过指定大小的下载目录
    3. 清理空目录
    4. 保留最近 N 天的文件
    """
    
    def __init__(
        self,
        download_dir: str = "downloads",
        max_age_days: int = 7,
        max_size_mb: int = 5000,
        clean_on_startup: bool = True,
    ):
        """
        Args:
            download_dir: 下载目录路径
            max_age_days: 文件最大保留天数（超过此天数的文件将被删除）
            max_size_mb: 目录最大大小 MB（超过此大小将删除最旧的文件）
            clean_on_startup: 是否在启动时执行清理
        """
        self.download_dir = Path(download_dir)
        self.max_age_days = max_age_days
        self.max_size_mb = max_size_mb
        self.clean_on_startup = clean_on_startup
    
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
    
    def get_all_files(self) -> List[Tuple[Path, float, int]]:
        """获取所有文件及其修改时间和大小
        
        Returns:
            List of (filepath, mtime, size)
        """
        files = []
        try:
            for root, dirs, filenames in os.walk(self.download_dir):
                for f in filenames:
                    fp = Path(root) / f
                    try:
                        stat = fp.stat()
                        files.append((fp, stat.st_mtime, stat.st_size))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"遍历文件失败: {e}")
        return files
    
    def clean_by_age(self) -> Tuple[int, int]:
        """按时间清理过期文件
        
        Returns:
            (删除文件数, 释放空间 bytes)
        """
        if not self.download_dir.exists():
            return 0, 0
        
        cutoff_time = time.time() - (self.max_age_days * 86400)
        deleted_count = 0
        freed_bytes = 0
        
        for fp, mtime, size in self.get_all_files():
            if mtime < cutoff_time:
                try:
                    fp.unlink()
                    deleted_count += 1
                    freed_bytes += size
                    logger.debug(f"删除过期文件: {fp.name} ({datetime.fromtimestamp(mtime)})")
                except Exception as e:
                    logger.warning(f"删除文件失败 {fp}: {e}")
        
        return deleted_count, freed_bytes
    
    def clean_by_size(self) -> Tuple[int, int]:
        """按大小清理（删除最旧的文件直到目录大小低于限制）
        
        Returns:
            (删除文件数, 释放空间 bytes)
        """
        if not self.download_dir.exists():
            return 0, 0
        
        max_size_bytes = self.max_size_mb * 1024 * 1024
        current_size = self.get_dir_size()
        
        if current_size <= max_size_bytes:
            return 0, 0
        
        # 按修改时间排序（最旧的在前）
        files = sorted(self.get_all_files(), key=lambda x: x[1])
        
        deleted_count = 0
        freed_bytes = 0
        
        for fp, mtime, size in files:
            if current_size - freed_bytes <= max_size_bytes:
                break
            
            try:
                fp.unlink()
                deleted_count += 1
                freed_bytes += size
                logger.debug(f"删除旧文件（空间限制）: {fp.name}")
            except Exception as e:
                logger.warning(f"删除文件失败 {fp}: {e}")
        
        return deleted_count, freed_bytes
    
    def clean_empty_dirs(self) -> int:
        """清理空目录
        
        Returns:
            删除的目录数
        """
        if not self.download_dir.exists():
            return 0
        
        deleted_count = 0
        
        # 从最深层目录开始清理
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
    
    def cleanup(self) -> dict:
        """执行完整清理
        
        Returns:
            清理统计信息
        """
        start_time = time.time()
        initial_size = self.get_dir_size()
        
        logger.info(f"🧹 开始清理下载目录: {self.download_dir}")
        logger.info(f"   当前大小: {initial_size / 1024 / 1024:.2f} MB")
        logger.info(f"   保留天数: {self.max_age_days} 天")
        logger.info(f"   空间限制: {self.max_size_mb} MB")
        
        # 1. 按时间清理
        age_deleted, age_freed = self.clean_by_age()
        if age_deleted > 0:
            logger.info(f"   按时间清理: 删除 {age_deleted} 个文件, 释放 {age_freed / 1024 / 1024:.2f} MB")
        
        # 2. 按大小清理
        size_deleted, size_freed = self.clean_by_size()
        if size_deleted > 0:
            logger.info(f"   按大小清理: 删除 {size_deleted} 个文件, 释放 {size_freed / 1024 / 1024:.2f} MB")
        
        # 3. 清理空目录
        dirs_deleted = self.clean_empty_dirs()
        if dirs_deleted > 0:
            logger.info(f"   清理空目录: {dirs_deleted} 个")
        
        final_size = self.get_dir_size()
        total_freed = initial_size - final_size
        elapsed = time.time() - start_time
        
        result = {
            "success": True,
            "initial_size_mb": round(initial_size / 1024 / 1024, 2),
            "final_size_mb": round(final_size / 1024 / 1024, 2),
            "freed_mb": round(total_freed / 1024 / 1024, 2),
            "files_deleted": age_deleted + size_deleted,
            "dirs_deleted": dirs_deleted,
            "elapsed_seconds": round(elapsed, 2),
        }
        
        logger.info(f"✅ 清理完成: 释放 {result['freed_mb']} MB, 耗时 {elapsed:.2f}s")
        
        return result
    
    def run_startup_cleanup(self):
        """启动时执行的清理（静默模式）"""
        if not self.clean_on_startup:
            return
        
        try:
            # 只在下载目录存在时执行
            if not self.download_dir.exists():
                logger.debug("下载目录不存在，跳过清理")
                return
            
            # 获取当前状态
            current_size_mb = self.get_dir_size() / 1024 / 1024
            
            # 如果目录不大，跳过清理
            if current_size_mb < 100:
                logger.debug(f"下载目录较小 ({current_size_mb:.1f} MB)，跳过清理")
                return
            
            # 执行清理
            self.cleanup()
            
        except Exception as e:
            logger.warning(f"启动清理失败: {e}")


def run_cleanup(
    download_dir: str = "downloads",
    max_age_days: int = 7,
    max_size_mb: int = 5000,
    clean_on_startup: bool = True,
) -> dict:
    """便捷函数：执行清理
    
    Args:
        download_dir: 下载目录路径
        max_age_days: 文件最大保留天数
        max_size_mb: 目录最大大小 MB
        clean_on_startup: 是否在启动时执行清理
    
    Returns:
        清理统计信息
    """
    cleaner = DownloadCleaner(
        download_dir=download_dir,
        max_age_days=max_age_days,
        max_size_mb=max_size_mb,
        clean_on_startup=clean_on_startup,
    )
    return cleaner.cleanup()


# 命令行入口
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="清理下载文件")
    parser.add_argument("--dir", default="downloads", help="下载目录路径")
    parser.add_argument("--max-age", type=int, default=7, help="文件最大保留天数")
    parser.add_argument("--max-size", type=int, default=5000, help="目录最大大小 MB")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要删除的文件")
    
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), format="{message}")
    
    if args.dry_run:
        cleaner = DownloadCleaner(
            download_dir=args.dir,
            max_age_days=args.max_age,
            max_size_mb=args.max_size,
        )
        files = cleaner.get_all_files()
        cutoff_time = time.time() - (args.max_age * 86400)
        
        print(f"\n文件总数: {len(files)}")
        print(f"目录大小: {cleaner.get_dir_size() / 1024 / 1024:.2f} MB\n")
        
        old_files = [f for f in files if f[1] < cutoff_time]
        if old_files:
            print(f"超过 {args.max_age} 天的文件 ({len(old_files)} 个):")
            for fp, mtime, size in old_files[:10]:
                print(f"  {fp.name} - {datetime.fromtimestamp(mtime)} - {size / 1024:.1f} KB")
            if len(old_files) > 10:
                print(f"  ... 还有 {len(old_files) - 10} 个文件")
    else:
        result = run_cleanup(
            download_dir=args.dir,
            max_age_days=args.max_age,
            max_size_mb=args.max_size,
        )
        print(f"\n清理结果: {result}")
