# VideoX - 全平台视频下载器

一个基于 FastAPI + Vue 3 的全平台视频解析下载工具，支持 YouTube、B站、抖音、TikTok、小红书等 8 个主流平台。

## 支持平台

| 平台 | 状态 | 说明 |
|------|------|------|
| YouTube | ✅ | 各种分辨率、Shorts、音频提取 |
| Bilibili | ✅ | 普通视频、番剧、多P视频 |
| 抖音 | ✅ | 短视频、图文，自动读取浏览器 Cookie |
| TikTok | ✅ | 无水印下载 |
| Twitter/X | ✅ | 推文视频下载 |
| Instagram | ✅ | Reels、普通视频 |
| 微博 | ✅ | 微博视频下载 |
| 小红书 | ✅ | 视频、图文笔记、高清视频提取 |

## 技术栈

**后端**
- Python 3.10+
- FastAPI + Uvicorn
- yt-dlp (核心下载引擎)
- Redis 缓存
- Celery 任务队列

**前端**
- Vue 3 + Vite
- Element Plus UI
- Pinia 状态管理
- Axios 请求封装

## 项目结构

```
ai_shipinxiazai/
├── backend/
│   ├── app/
│   │   ├── api/               # API 路由
│   │   │   └── video.py       # 视频 API（含安全认证）
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 环境配置
│   │   │   ├── cache.py       # Redis 缓存
│   │   │   ├── tasks.py       # Celery 任务
│   │   │   └── celery_app.py  # Celery 配置
│   │   ├── models/            # 数据模型
│   │   │   └── video.py
│   │   ├── services/          # 各平台下载器
│   │   │   ├── base.py        # 基础下载器
│   │   │   ├── downloader.py  # 统一下载入口
│   │   │   ├── youtube/
│   │   │   ├── bilibili/
│   │   │   ├── douyin/
│   │   │   ├── tiktok/
│   │   │   ├── twitter/
│   │   │   ├── instagram/
│   │   │   ├── weibo/
│   │   │   └── xiaohongshu/
│   │   ├── utils/
│   │   │   └── logger.py
│   │   └── main.py
│   ├── config/                # Cookie 配置
│   │   ├── douyin_cookies.json
│   │   └── xiaohongshu_cookies.json
│   ├── downloads/             # 下载文件
│   ├── logs/                  # 日志文件
│   ├── .env                   # 环境变量
│   ├── start.sh               # 一键启动脚本
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/               # API 封装
│   │   │   └── video.js       # Axios 实例 + 拦截器
│   │   ├── assets/            # 样式资源
│   │   │   └── styles/
│   │   │       └── main.scss
│   │   ├── stores/            # Pinia 状态
│   │   │   └── video.js
│   │   ├── App.vue            # 主组件
│   │   └── main.js
│   ├── public/
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
│
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- ffmpeg（视频处理必需）
- Redis（可选，用于缓存加速）

```bash
# Ubuntu/Debian
sudo apt install ffmpeg redis-server

# macOS
brew install ffmpeg redis
```

### 2. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt

# 安装 Playwright 浏览器（抖音图文解析需要）
playwright install chromium
```

### 3. 配置环境变量

创建 `backend/.env` 文件：

```env
# 应用配置
DEBUG=false
HOST=0.0.0.0
PORT=8000

# 代理配置（YouTube、TikTok 等海外平台需要）
PROXY_URL=http://127.0.0.1:7890

# Redis 配置
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true

# 请求限流
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=30

# API 安全（生产环境启用）
# API_KEY_ENABLED=true
# API_KEY=your-secret-key-here
```

### 4. 启动服务

```bash
cd backend
./start.sh
```

`start.sh` 会自动启动：
- Redis 检测与启动
- Celery Worker（后台）
- FastAPI 服务（前台）

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 6. 访问应用

- 前端界面: http://localhost:5173
- API 文档: http://localhost:8000/docs

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/parse` | POST | 解析视频信息（同步，自动缓存） |
| `/api/v1/parse/async` | POST | 异步解析（Celery 任务） |
| `/api/v1/download` | POST | 下载视频 |
| `/api/v1/download/async` | POST | 异步下载（Celery 任务） |
| `/api/v1/direct-url` | POST | 获取视频直链 |
| `/api/v1/task/{task_id}` | GET | 查询异步任务状态 |
| `/api/v1/download/{filename}` | GET | 获取已下载的文件 |
| `/api/v1/platforms` | GET | 获取支持的平台列表 |
| `/api/v1/cache/stats` | GET | 获取缓存统计信息 |
| `/api/v1/proxy/image` | GET | 图片代理（绕过防盗链） |
| `/api/v1/health` | GET | 健康检查 |

## 安全特性

### API 认证（可选）

生产环境可启用 API Key 认证：

```env
API_KEY_ENABLED=true
API_KEY=your-secret-key-here
```

前端请求时添加 Header：
```
X-API-Key: your-secret-key-here
```

### SSRF 防护

图片代理接口已实现 SSRF 防护：
- 域名白名单验证
- 禁止访问私有 IP
- 协议限制（仅 HTTP/HTTPS）

### 请求限流

默认启用请求限流：
- 每分钟 30 次请求
- 可通过环境变量配置

### 全局错误处理

- 后端：全局异常捕获 + 请求 ID 追踪
- 前端：Vue errorHandler + unhandledrejection 捕获

## Cookie 配置

### 抖音

系统自动从浏览器读取 Cookie：
1. 在浏览器中打开 https://www.douyin.com 并登录
2. 播放任意视频
3. 系统自动读取 Cookie

或手动配置 `backend/config/douyin_cookies.json`

### 小红书

系统自动从浏览器读取 Cookie，部分内容需要登录。

### YouTube

系统自动从浏览器读取 Cookie 以绕过机器人检测。

## 性能特性

**Redis 缓存**
- 解析结果缓存 1 小时
- 缓存命中响应时间 < 10ms
- 无 Redis 自动降级内存缓存

**高并发支持**
- 最大并发数：20（可配置）
- 线程池隔离，避免阻塞

**Celery 任务队列**
- 长时间操作异步处理
- 支持任务状态查询

**前端优化**
- 图片懒加载
- 请求节流/防抖
- 代码分割打包

## 常见问题

**Q: 抖音视频解析失败？**

A: 确保已在浏览器登录抖音，系统会自动读取 Cookie。

**Q: YouTube 无法访问？**

A: 配置代理，在 `.env` 文件设置 `PROXY_URL=http://127.0.0.1:7890`

**Q: 视频下载后没有声音？**

A: 确保已安装 ffmpeg，视频合并需要 ffmpeg 支持。

**Q: Redis 连接失败？**

A: 系统会自动降级使用内存缓存，不影响正常使用。建议安装 Redis 以获得更好性能。

**Q: 分享文本无法识别？**

A: 前端会自动从分享文本中提取 URL，支持抖音、小红书等平台的分享格式。