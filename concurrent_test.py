#!/usr/bin/env python3
"""
VideoX 并发测试脚本
测试视频解析和下载的并发性能
"""
import asyncio
import aiohttp
import time
import json
import re
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import threading

API_BASE = "http://localhost:8000/api/v1"

@dataclass
class TestResult:
    url: str
    platform: str
    success: bool
    parse_time: float = 0.0
    download_time: float = 0.0
    error: str = ""
    video_title: str = ""
    file_size: int = 0
    file_name: str = ""

@dataclass 
class TestStats:
    total: int = 0
    success: int = 0
    failed: int = 0
    total_parse_time: float = 0.0
    total_download_time: float = 0.0
    results: List[TestResult] = field(default_factory=list)
    
    def add_result(self, result: TestResult):
        self.total += 1
        self.results.append(result)
        if result.success:
            self.success += 1
            self.total_parse_time += result.parse_time
            self.total_download_time += result.download_time
        else:
            self.failed += 1

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if 'xiaohongshu' in url_lower or 'xhslink' in url_lower:
        return "小红书"
    elif 'douyin' in url_lower or 'iesdouyin' in url_lower:
        return "抖音"
    elif 'bilibili' in url_lower or 'b23.tv' in url_lower:
        return "B站"
    elif 'youtube' in url_lower or 'youtu.be' in url_lower:
        return "YouTube"
    elif 'tiktok' in url_lower:
        return "TikTok"
    elif 'twitter' in url_lower or 'x.com' in url_lower:
        return "Twitter"
    elif 'instagram' in url_lower:
        return "Instagram"
    elif 'weibo' in url_lower:
        return "微博"
    return "未知"

def extract_url(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None
    
    http_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', line)
    if http_match:
        return http_match.group(0)
    
    douyin_match = re.search(r'https?://v\.douyin\.com/[^\s/]+', line)
    if douyin_match:
        return douyin_match.group(0)
    
    return None

def load_urls(file_path: str) -> List[str]:
    urls = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            url = extract_url(line)
            if url:
                urls.append(url)
    return urls

print_lock = threading.Lock()

def print_progress(msg: str, end: str = "\n"):
    with print_lock:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}", end=end, flush=True)

async def parse_video(session: aiohttp.ClientSession, url: str, index: int) -> Dict[str, Any]:
    print_progress(f"🔍 [{index}] 开始解析: {url[:60]}...")
    
    start_time = time.time()
    try:
        async with session.post(
            f"{API_BASE}/parse",
            json={"url": url},
            timeout=aiohttp.ClientTimeout(total=120)
        ) as response:
            result = await response.json()
            parse_time = time.time() - start_time
            
            if result.get("success") and result.get("video_info"):
                video_info = result["video_info"]
                title = video_info.get("title", "未知标题")[:40]
                formats_count = len(video_info.get("formats", []))
                print_progress(f"✅ [{index}] 解析成功 ({parse_time:.2f}s): {title}... | {formats_count} 个格式")
                return {
                    "success": True,
                    "parse_time": parse_time,
                    "video_info": video_info,
                    "error": None
                }
            else:
                error = result.get("message", "未知错误")
                print_progress(f"❌ [{index}] 解析失败 ({parse_time:.2f}s): {error}")
                return {
                    "success": False,
                    "parse_time": parse_time,
                    "video_info": None,
                    "error": error
                }
    except asyncio.TimeoutError:
        parse_time = time.time() - start_time
        print_progress(f"⏰ [{index}] 解析超时 ({parse_time:.2f}s)")
        return {"success": False, "parse_time": parse_time, "video_info": None, "error": "超时"}
    except Exception as e:
        parse_time = time.time() - start_time
        print_progress(f"❌ [{index}] 解析异常 ({parse_time:.2f}s): {str(e)[:50]}")
        return {"success": False, "parse_time": parse_time, "video_info": None, "error": str(e)}

async def download_video(session: aiohttp.ClientSession, url: str, index: int, 
                         video_info: Dict = None) -> Dict[str, Any]:
    print_progress(f"⬇️  [{index}] 开始下载...")
    
    start_time = time.time()
    try:
        payload = {"url": url}
        if video_info:
            payload["video_title"] = video_info.get("title", "")
            payload["video_id"] = video_info.get("id", "")
        
        async with session.post(
            f"{API_BASE}/download",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=300)
        ) as response:
            result = await response.json()
            download_time = time.time() - start_time
            
            if result.get("success"):
                file_name = result.get("file_name", "")
                file_size = result.get("file_size", 0)
                size_mb = file_size / (1024 * 1024)
                print_progress(f"✅ [{index}] 下载成功 ({download_time:.2f}s): {file_name} ({size_mb:.2f}MB)")
                return {
                    "success": True,
                    "download_time": download_time,
                    "file_name": file_name,
                    "file_size": file_size,
                    "error": None
                }
            else:
                error = result.get("detail", "下载失败")
                print_progress(f"❌ [{index}] 下载失败 ({download_time:.2f}s): {error}")
                return {
                    "success": False,
                    "download_time": download_time,
                    "file_name": "",
                    "file_size": 0,
                    "error": error
                }
    except asyncio.TimeoutError:
        download_time = time.time() - start_time
        print_progress(f"⏰ [{index}] 下载超时 ({download_time:.2f}s)")
        return {"success": False, "download_time": download_time, "file_name": "", "file_size": 0, "error": "超时"}
    except Exception as e:
        download_time = time.time() - start_time
        print_progress(f"❌ [{index}] 下载异常 ({download_time:.2f}s): {str(e)[:50]}")
        return {"success": False, "download_time": download_time, "file_name": "", "file_size": 0, "error": str(e)}

async def test_single_url(session: aiohttp.ClientSession, url: str, index: int, 
                          download: bool = True) -> TestResult:
    platform = detect_platform(url)
    result = TestResult(url=url, platform=platform, success=False)
    
    parse_result = await parse_video(session, url, index)
    result.parse_time = parse_result["parse_time"]
    
    if not parse_result["success"]:
        result.error = parse_result["error"]
        return result
    
    video_info = parse_result.get("video_info")
    if video_info:
        result.video_title = video_info.get("title", "")
    
    if download:
        download_result = await download_video(session, url, index, video_info)
        result.download_time = download_result["download_time"]
        if download_result["success"]:
            result.success = True
            result.file_name = download_result["file_name"]
            result.file_size = download_result["file_size"]
        else:
            result.error = download_result["error"]
    else:
        result.success = True
    
    return result

async def run_concurrent_test(urls: List[str], max_concurrent: int = 10, 
                               download: bool = True) -> TestStats:
    stats = TestStats()
    
    print_progress(f"\n{'='*70}")
    print_progress(f"🚀 开始并发测试 | 并发数: {max_concurrent} | URL数量: {len(urls)} | 下载: {'是' if download else '否'}")
    print_progress(f"{'='*70}\n")
    
    connector = aiohttp.TCPConnector(limit=max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def limited_test(url: str, index: int):
            async with semaphore:
                return await test_single_url(session, url, index, download)
        
        tasks = [limited_test(url, i+1) for i, url in enumerate(urls)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                stats.add_result(TestResult(
                    url="未知", 
                    platform="未知", 
                    success=False, 
                    error=str(result)
                ))
            else:
                stats.add_result(result)
    
    return stats

def print_final_report(stats: TestStats, test_type: str):
    print_progress(f"\n{'='*70}")
    print_progress(f"📊 {test_type}测试报告")
    print_progress(f"{'='*70}")
    print_progress(f"总请求数: {stats.total}")
    print_progress(f"成功: {stats.success} ({stats.success/stats.total*100:.1f}%)")
    print_progress(f"失败: {stats.failed} ({stats.failed/stats.total*100:.1f}%)")
    
    if stats.success > 0:
        avg_parse = stats.total_parse_time / stats.success
        avg_download = stats.total_download_time / stats.success if stats.total_download_time > 0 else 0
        print_progress(f"平均解析时间: {avg_parse:.2f}s")
        if avg_download > 0:
            print_progress(f"平均下载时间: {avg_download:.2f}s")
    
    print_progress(f"\n按平台统计:")
    platform_stats = {}
    for r in stats.results:
        if r.platform not in platform_stats:
            platform_stats[r.platform] = {"total": 0, "success": 0, "failed": 0}
        platform_stats[r.platform]["total"] += 1
        if r.success:
            platform_stats[r.platform]["success"] += 1
        else:
            platform_stats[r.platform]["failed"] += 1
    
    for platform, pstats in platform_stats.items():
        rate = pstats["success"] / pstats["total"] * 100 if pstats["total"] > 0 else 0
        print_progress(f"  {platform}: {pstats['success']}/{pstats['total']} ({rate:.0f}%)")
    
    if stats.failed > 0:
        print_progress(f"\n失败详情:")
        for r in stats.results:
            if not r.success:
                print_progress(f"  ❌ [{r.platform}] {r.url[:50]}... - {r.error}")
    
    print_progress(f"{'='*70}\n")

async def main():
    urls = load_urls("test_url.txt")
    
    if not urls:
        print("未找到有效的URL")
        return
    
    print(f"\n📋 共加载 {len(urls)} 个测试链接:")
    for i, url in enumerate(urls, 1):
        platform = detect_platform(url)
        print(f"  {i}. [{platform}] {url[:60]}...")
    
    print("\n" + "="*70)
    print("并发解析测试 (不下载)")
    print("="*70)
    
    parse_stats = await run_concurrent_test(urls, max_concurrent=10, download=False)
    print_final_report(parse_stats, "解析")

if __name__ == "__main__":
    asyncio.run(main())
