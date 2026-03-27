<template>
  <div class="app-container">
    <!-- 加载遮罩 -->
    <Transition name="fade">
      <div v-if="loading" class="loading-overlay">
        <div class="loading-spinner"></div>
      </div>
    </Transition>

    <main class="main-content">
      <!-- Hero 区域 -->
      <section class="hero-section">
        <h1 class="hero-title">VideoX</h1>
        <p class="hero-subtitle">
          全平台视频解析下载工具，支持 YouTube、B站、抖音、小红书等网站
        </p>
      </section>

      <!-- 搜索区域 -->
      <section class="search-section">
        <div class="search-card">
          <div class="search-input-wrapper">
            <div class="url-input">
              <el-input
                v-model="url"
                placeholder="粘贴视频链接，支持 YouTube、B站、抖音、小红书 等平台..."
                size="large"
                clearable
                @keyup.enter="handleParse"
              >
                <template #prefix>
                  <el-icon><Link /></el-icon>
                </template>
              </el-input>
            </div>
            <el-button
              type="primary"
              class="parse-btn"
              :loading="parsing"
              :disabled="parseCooldown > 0"
              @click="handleParse"
            >
              <el-icon v-if="!parsing"><Search /></el-icon>
              {{ parsing ? '解析中...' : (parseCooldown > 0 ? `${parseCooldown}s` : '解析视频') }}
            </el-button>
          </div>
        </div>

        <!-- 平台标签 -->
        <div class="platform-tags">
          <span class="platform-tag">
            <el-icon><VideoPlay /></el-icon> YouTube
          </span>
          <span class="platform-tag">
            <el-icon><VideoCamera /></el-icon> Bilibili
          </span>
          <span class="platform-tag douyin-tag">
            <el-icon><Cellphone /></el-icon> 抖音
          </span>
          <span class="platform-tag">
            <el-icon><Pointer /></el-icon> TikTok
          </span>
          <span class="platform-tag">
            <el-icon><ChatDotRound /></el-icon> Twitter/X
          </span>
          <span class="platform-tag">
            <el-icon><Picture /></el-icon> Instagram
          </span>
          <span class="platform-tag">
            <el-icon><Notebook /></el-icon> 小红书
          </span>
        </div>
      </section>

      <!-- 视频信息展示 -->
      <Transition name="slide-up">
        <section v-if="videoInfo" class="video-info-card">
          <div class="video-preview">
            <div class="thumbnail-wrapper">
              <!-- 图片占位符 -->
              <div class="thumbnail-placeholder">
                <el-icon><VideoPlay /></el-icon>
              </div>
              <el-image
                :src="getProxiedImageUrl(videoInfo.thumbnail)"
                :alt="videoInfo.title"
                fit="cover"
                lazy
                referrerpolicy="no-referrer"
              >
                <template #placeholder>
                  <div class="image-placeholder">
                    <el-icon class="is-loading"><Loading /></el-icon>
                  </div>
                </template>
                <template #error>
                  <div class="thumbnail-placeholder" style="display: flex;">
                    <el-icon><VideoPlay /></el-icon>
                  </div>
                </template>
              </el-image>
              <span v-if="videoInfo.duration" class="duration-badge">
                {{ formatDuration(videoInfo.duration) }}
              </span>
              <!-- 图文笔记标识 -->
              <span v-if="isGallery" class="gallery-badge">
                <el-icon><Picture /></el-icon>
                {{ imageCount }} 张图片
              </span>
            </div>
            <div class="video-details">
              <h2 class="video-title">{{ videoInfo.title }}</h2>
              <div class="video-meta">
                <span v-if="videoInfo.uploader" class="meta-item">
                  <el-icon><User /></el-icon>
                  {{ videoInfo.uploader }}
                </span>
                <span v-if="videoInfo.view_count" class="meta-item">
                  <el-icon><View /></el-icon>
                  {{ formatNumber(videoInfo.view_count) }} 次播放
                </span>
                <span v-if="videoInfo.like_count" class="meta-item">
                  <el-icon><Star /></el-icon>
                  {{ formatNumber(videoInfo.like_count) }}
                </span>
                <span v-if="videoInfo.platform" class="meta-item">
                  <el-icon><Platform /></el-icon>
                  {{ getPlatformLabel(videoInfo.platform) }}
                </span>
              </div>
              <p v-if="videoInfo.description" class="video-description">
                {{ videoInfo.description }}
              </p>
            </div>
          </div>

          <!-- 图片预览（仅图文笔记） -->
          <div v-if="isGallery && displayFormats.length > 0" class="gallery-preview">
            <h3 class="section-title">图片预览</h3>
            <div class="gallery-grid">
              <div 
                v-for="(fmt, index) in displayFormats" 
                :key="fmt.format_id"
                class="gallery-item"
              >
                <div class="gallery-image-wrapper">
                  <el-image
                    :src="getProxiedImageUrl(fmt.url)"
                    :alt="`图片 ${index + 1}`"
                    fit="cover"
                    lazy
                    :preview-src-list="galleryPreviewUrls"
                    :initial-index="index"
                    preview-teleported
                    referrerpolicy="no-referrer"
                  >
                    <template #placeholder>
                      <div class="image-placeholder">
                        <el-icon class="is-loading"><Loading /></el-icon>
                      </div>
                    </template>
                    <template #error>
                      <div class="image-error">
                        <el-icon><Picture /></el-icon>
                        <span>加载失败</span>
                      </div>
                    </template>
                  </el-image>
                  <span class="image-index">{{ index + 1 }}</span>
                </div>
                <button 
                  class="image-download-btn"
                  @click="handleDownloadImage(fmt.url, index + 1)"
                  title="下载此图片"
                >
                  <el-icon><Download /></el-icon>
                  下载
                </button>
              </div>
            </div>
          </div>

          <!-- 格式选择和下载 -->
          <div class="download-section">
            <!-- 图文笔记下载 -->
            <template v-if="isGallery">
              <h3 class="section-title">下载图片</h3>
              <div class="gallery-download">
                <el-button
                  type="primary"
                  size="large"
                  :loading="quickDownloading"
                  @click="handleDownloadGallery"
                >
                  <el-icon><Download /></el-icon>
                  下载全部 {{ imageCount }} 张图片
                </el-button>
                <p class="download-hint">图片将以 ZIP 压缩包形式下载</p>
              </div>
              
              <!-- 单张图片下载 -->
              <div class="image-list">
                <div
                  v-for="(fmt, index) in displayFormats"
                  :key="fmt.format_id"
                  class="image-item"
                >
                  <div class="image-info">
                    <span class="image-index-badge">{{ index + 1 }}</span>
                    <span class="image-resolution">{{ fmt.resolution || fmt.quality }}</span>
                  </div>
                  <el-button
                    size="small"
                    @click="handleDownloadImage(fmt.url, index + 1)"
                  >
                    <el-icon><Download /></el-icon>
                    下载
                  </el-button>
                </div>
              </div>
            </template>
            
            <!-- 视频下载 -->
            <template v-else>
              <h3 class="section-title">
                {{ isMultiPart ? (selectedPart ? '选择清晰度' : '选择分P') : '选择格式下载' }}
              </h3>
            
              <!-- B站多P视频分P选择提示 -->
              <div v-if="isMultiPart && !selectedPart" class="multi-part-hint">
                <el-icon><InfoFilled /></el-icon>
                <span>检测到多P视频，请先选择要下载的分P</span>
              </div>
            
              <!-- 已选择分P时显示返回按钮 -->
              <div v-if="isMultiPart && selectedPart" class="selected-part-info">
                <el-button 
                  size="small" 
                  @click="selectedPart = null; partVideoInfo = null"
                  link
                >
                  <el-icon><ArrowLeft /></el-icon>
                  返回分P选择
                </el-button>
                <span class="part-label">当前选择：{{ selectedPart.quality }}</span>
              </div>
            
              <!-- 分P清晰度加载状态 -->
              <div v-if="loadingPartFormats" class="loading-formats">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>正在加载清晰度选项...</span>
              </div>
            
              <!-- 快速下载按钮 -->
              <div class="quick-download" v-if="!isMultiPart || selectedPart">
                <el-button
                  type="primary"
                  size="large"
                  :loading="quickDownloading"
                  @click="handleQuickDownload"
                >
                  <el-icon><Download /></el-icon>
                  快速下载最佳画质
                </el-button>
                <span class="quick-hint">或选择下方特定格式</span>
              </div>
              
              <div class="format-list">
                <div
                  v-for="fmt in formatList"
                  :key="fmt.format_id"
                  class="format-item"
                  :class="{ 'part-item': isMultiPart && !selectedPart }"
                  @click="isMultiPart && !selectedPart && selectPart(fmt)"
                >
                  <div class="format-info">
                    <!-- 多P视频显示 -->
                    <template v-if="isMultiPart && !selectedPart">
                      <span class="part-number">{{ fmt.format_id.toUpperCase() }}</span>
                      <span class="part-title">{{ fmt.quality }}</span>
                    </template>
                    <!-- 普通格式显示 -->
                    <template v-else>
                      <span class="format-badge">{{ fmt.ext?.toUpperCase() || 'MP4' }}</span>
                      <span class="format-resolution">{{ fmt.resolution || '未知' }}</span>
                      <span v-if="fmt.filesize" class="format-size">
                        {{ formatFileSize(fmt.filesize || fmt.filesize_approx) }}
                      </span>
                    </template>
                  </div>
                  <el-button
                    v-if="!isMultiPart || selectedPart"
                    class="download-btn"
                    :loading="downloadingFormat === fmt.format_id"
                    @click.stop="handleDownload(fmt.format_id)"
                  >
                    <el-icon><Download /></el-icon>
                    下载
                  </el-button>
                  <el-icon v-else class="arrow-icon"><ArrowRight /></el-icon>
                </div>
              </div>
            </template>
          </div>

          <!-- 下载进度 -->
          <Transition name="slide-up">
            <div v-if="downloadProgress" class="download-progress">
              <div class="progress-header">
                <span class="filename">{{ downloadProgress.filename }}</span>
                <span class="speed">{{ downloadProgress.speed }}</span>
              </div>
              <el-progress
                :percentage="downloadProgress.progress"
                :stroke-width="8"
                :show-text="false"
              />
              <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.75rem; color: var(--text-muted);">
                <span>{{ downloadProgress.progress.toFixed(1) }}%</span>
                <span>剩余 {{ downloadProgress.eta }}</span>
              </div>
            </div>
          </Transition>
        </section>
      </Transition>
    </main>

    <!-- 页脚 -->
    <footer class="footer">
      <div class="footer-links">
        <a href="#" @click.prevent>使用帮助</a>
        <a href="#" @click.prevent>隐私政策</a>
        <a href="https://github.com" target="_blank">GitHub</a>
      </div>
      <p>© 2026 VideoX. 基于 yt-dlp 构建，仅供学习研究使用。</p>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Link,
  Search,
  Download,
  VideoPlay,
  VideoCamera,
  Cellphone,
  Pointer,
  ChatDotRound,
  Picture,
  User,
  View,
  Star,
  Platform,
  Notebook,
  Loading,
  ArrowLeft,
  ArrowRight,
  InfoFilled,
} from '@element-plus/icons-vue'
import { videoApi } from './api/video'

// ==================== 状态管理 ====================

const url = ref('')
const quality = ref('best')
const parsing = ref(false)
const loading = ref(false)
const downloadingFormat = ref(null)
const videoInfo = ref(null)
const downloadProgress = ref(null)
const quickDownloading = ref(false)
const parseCooldown = ref(0)

// 定时器引用（用于清理）
let cooldownTimer = null

// ==================== 数据校验 ====================

/**
 * 校验并规范化视频信息数据
 * 防止后端返回异常数据导致页面崩溃
 */
function validateVideoInfo(data) {
  if (!data || typeof data !== 'object') {
    return null
  }
  
  return {
    id: String(data.id || ''),
    title: String(data.title || '未知标题'),
    description: data.description ? String(data.description) : null,
    thumbnail: data.thumbnail ? String(data.thumbnail) : '',
    duration: Number(data.duration) || 0,
    uploader: data.uploader ? String(data.uploader) : null,
    uploader_id: data.uploader_id ? String(data.uploader_id) : null,
    upload_date: data.upload_date ? String(data.upload_date) : null,
    view_count: Number(data.view_count) || 0,
    like_count: Number(data.like_count) || 0,
    comment_count: Number(data.comment_count) || 0,
    platform: data.platform ? String(data.platform) : 'unknown',
    original_url: data.original_url ? String(data.original_url) : '',
    formats: Array.isArray(data.formats) ? data.formats.filter(f => f && typeof f === 'object') : [],
  }
}

/**
 * URL 格式校验
 */
function isValidUrl(urlString) {
  if (!urlString || typeof urlString !== 'string') {
    return false
  }
  try {
    const parsed = new URL(urlString)
    return ['http:', 'https:'].includes(parsed.protocol)
  } catch {
    return false
  }
}

/**
 * 从分享文本中提取视频 URL
 * 支持抖音、TikTok、小红书等平台的分享文本
 */
function extractUrl(text) {
  if (!text || typeof text !== 'string') {
    return null
  }
  
  const trimmed = text.trim()
  
  // 如果本身就是有效 URL，直接返回
  if (isValidUrl(trimmed)) {
    return trimmed
  }
  
  // URL 正则匹配 - 匹配 http/https 开头的链接
  const urlPatterns = [
    // 通用 URL 匹配
    /https?:\/\/[^\s<>"{}|\\^`\[\]]+/gi,
    // 抖音短链接
    /https?:\/\/v\.douyin\.com\/[a-zA-Z0-9_-]+\/?/gi,
    // TikTok
    /https?:\/\/(?:vm|www)\.tiktok\.com\/[^\s]+/gi,
    // 小红书
    /https?:\/\/www\.xiaohongshu\.com\/[^\s]+/gi,
    /https?:\/\/xhslink\.com\/[^\s]+/gi,
    // Bilibili
    /https?:\/\/(?:www\.)?bilibili\.com\/[^\s]+/gi,
    /https?:\/\/b23\.tv\/[^\s]+/gi,
    // YouTube
    /https?:\/\/(?:www\.)?youtube\.com\/[^\s]+/gi,
    /https?:\/\/youtu\.be\/[^\s]+/gi,
    // Twitter/X
    /https?:\/\/(?:www\.)?(?:twitter|x)\.com\/[^\s]+/gi,
    // Instagram
    /https?:\/\/(?:www\.)?instagram\.com\/[^\s]+/gi,
    // 微博
    /https?:\/\/(?:www\.)?weibo\.(?:com|cn)\/[^\s]+/gi,
    /https?:\/\/m\.weibo\.cn\/[^\s]+/gi,
  ]
  
  for (const pattern of urlPatterns) {
    const matches = trimmed.match(pattern)
    if (matches && matches.length > 0) {
      // 清理 URL 末尾可能的标点符号
      let url = matches[0]
      url = url.replace(/[。，,；;！!？?）)\]]+$/, '')
      return url
    }
  }
  
  return null
}

// ==================== 防抖/节流工具 ====================

/**
 * 创建节流函数
 */
function createThrottle(fn, delay = 1000) {
  let lastCall = 0
  let timer = null
  
  return function (...args) {
    const now = Date.now()
    const remaining = delay - (now - lastCall)
    
    if (remaining <= 0) {
      lastCall = now
      return fn.apply(this, args)
    }
    
    if (!timer) {
      timer = setTimeout(() => {
        lastCall = Date.now()
        timer = null
        return fn.apply(this, args)
      }, remaining)
    }
  }
}

/**
 * 创建防抖函数
 */
function createDebounce(fn, delay = 300) {
  let timer = null
  
  return function (...args) {
    if (timer) {
      clearTimeout(timer)
    }
    timer = setTimeout(() => {
      timer = null
      return fn.apply(this, args)
    }, delay)
  }
}

// ==================== 计算属性 ====================

const isGallery = computed(() => {
  if (!videoInfo.value?.formats) return false
  const imageFormats = videoInfo.value.formats.filter(f => f.format_id?.startsWith('image_'))
  return imageFormats.length > 0 && (!videoInfo.value.duration || videoInfo.value.duration === 0)
})

const imageCount = computed(() => {
  if (!videoInfo.value?.formats) return 0
  return videoInfo.value.formats.filter(f => f.format_id?.startsWith('image_')).length
})

const galleryPreviewUrls = computed(() => {
  if (!videoInfo.value?.formats) return []
  return videoInfo.value.formats
    .filter(f => f.format_id?.startsWith('image_'))
    .map(f => getProxiedImageUrl(f.url))
})

const displayFormats = computed(() => {
  if (!videoInfo.value?.formats) return []
  
  if (isGallery.value) {
    return videoInfo.value.formats.filter(f => f.format_id?.startsWith('image_'))
  }
  
  const validFormats = videoInfo.value.formats
    .filter(f => {
      const hasVideo = f.vcodec && f.vcodec !== 'none'
      const hasAudio = f.acodec && f.acodec !== 'none'
      // 过滤掉纯音频格式（用户不需要单独下载音频）
      if (!hasVideo && hasAudio) return false
      return hasVideo || hasAudio
    })
    .sort((a, b) => {
      const getHeight = (f) => {
        if (f.resolution) {
          const match = f.resolution.match(/(\d+)p?$/)
          return match ? parseInt(match[1]) : 0
        }
        return 0
      }
      return getHeight(b) - getHeight(a)
    })
  
  return validFormats.slice(0, 15)
})

// 是否是B站多P视频
const isMultiPart = computed(() => {
  if (!videoInfo.value?.formats) return false
  // 检查是否有 p1, p2, p3 格式的 format_id
  return videoInfo.value.formats.some(f => f.format_id?.match(/^p\d+$/))
})

// 多P视频的分P列表
const multiPartList = computed(() => {
  if (!videoInfo.value?.formats) return []
  return videoInfo.value.formats
    .filter(f => f.format_id?.match(/^p\d+$/))
    .sort((a, b) => {
      const numA = parseInt(a.format_id.slice(1))
      const numB = parseInt(b.format_id.slice(1))
      return numA - numB
    })
})

// 当前选中的分P
const selectedPart = ref(null)
// 分P清晰度加载状态
const loadingPartFormats = ref(false)
// 分P视频信息（包含清晰度选项）
const partVideoInfo = ref(null)

// 选中分P后显示的格式列表（从分P视频信息中获取）
const partFormats = computed(() => {
  if (!isMultiPart.value || !selectedPart.value) return []
  
  // 使用分P视频信息中的格式列表
  if (partVideoInfo.value?.formats) {
    return partVideoInfo.value.formats
      .filter(f => {
        const hasVideo = f.vcodec && f.vcodec !== 'none'
        const hasAudio = f.acodec && f.acodec !== 'none'
        // 过滤掉纯音频格式
        if (!hasVideo && hasAudio) return false
        return hasVideo || hasAudio
      })
      .sort((a, b) => {
        const getHeight = (f) => {
          if (f.resolution) {
            const match = f.resolution.match(/(\d+)p?$/)
            return match ? parseInt(match[1]) : 0
          }
          return 0
        }
        return getHeight(b) - getHeight(a)
      })
      .slice(0, 10)
  }
  
  return []
})

// 显示的格式列表（根据是否是B站多P视频）
const formatList = computed(() => {
  if (isMultiPart.value) {
    if (selectedPart.value) {
      // 已选择分P，显示清晰度选择
      return partFormats.value
    }
    // 未选择分P，显示分P列表
    return multiPartList.value
  }
  return displayFormats.value
})

// ==================== 解析视频 ====================

/**
 * 启动冷却计时器
 */
function startCooldown(seconds = 3) {
  parseCooldown.value = seconds
  cooldownTimer = setInterval(() => {
    parseCooldown.value--
    if (parseCooldown.value <= 0) {
      clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }, 1000)
}

/**
 * 解析视频信息（带防抖）
 */
const handleParse = createThrottle(async () => {
  // 提取 URL
  const extractedUrl = extractUrl(url.value)
  
  if (!extractedUrl) {
    ElMessage.warning('请输入视频链接或粘贴分享文本')
    return
  }
  
  // 更新输入框显示提取后的 URL
  if (extractedUrl !== url.value.trim()) {
    url.value = extractedUrl
    ElMessage.info('已自动提取链接')
  }
  
  // 防止重复请求
  if (parsing.value) {
    return
  }
  
  parsing.value = true
  videoInfo.value = null
  downloadProgress.value = null
  
  try {
    const res = await videoApi.parse(extractedUrl)
    
    if (res.success) {
      // 数据校验
      const validatedInfo = validateVideoInfo(res.video_info)
      
      if (!validatedInfo) {
        ElMessage.error('返回数据格式错误')
        return
      }
      
      videoInfo.value = validatedInfo
      ElMessage.success('解析成功！')
    } else {
      ElMessage.error(res.message || '解析失败')
    }
  } catch (err) {
    // 错误已在拦截器中处理
    console.error('[Parse Error]', err)
  } finally {
    parsing.value = false
    startCooldown(2) // 2秒冷却
  }
}, 1000)

// ==================== 下载视频 ====================

// 选择分P
async function selectPart(fmt) {
  selectedPart.value = fmt
  partVideoInfo.value = null
  loadingPartFormats.value = true
  
  ElMessage.info(`正在获取 ${fmt.quality} 的清晰度选项...`)
  
  try {
    // 从 format_id 中提取分P索引 (p1 -> 1, p2 -> 2, ...)
    const partIndex = parseInt(fmt.format_id.slice(1))
    
    // 调用 API 获取该分P的清晰度信息
    const res = await videoApi.parsePart(url.value, partIndex)
    
    if (res.success && res.video_info) {
      partVideoInfo.value = res.video_info
      ElMessage.success(`已加载 ${fmt.quality} 的清晰度选项`)
    } else {
      ElMessage.error(res.message || '获取清晰度失败')
    }
  } catch (err) {
    console.error('[Parse Part Error]', err)
    ElMessage.error('获取清晰度失败')
  } finally {
    loadingPartFormats.value = false
  }
}

/**
 * 下载视频（带节流）
 */
const handleDownload = createThrottle(async (formatId) => {
  if (downloadingFormat.value) {
    return
  }
  
  downloadingFormat.value = formatId
  
  // B站多P视频：构建正确的下载参数
  let actualFormatId = formatId
  let actualUrl = url.value
  
  if (isMultiPart.value && selectedPart.value) {
    // 使用选中的分P索引构建 URL
    const pIndex = selectedPart.value.format_id.slice(1)
    const baseUrl = actualUrl.split('?')[0]
    actualUrl = `${baseUrl}?p=${pIndex}`
    // formatId 已经是清晰度的 format_id，不需要修改
  }
  
  // 先尝试获取直链
  try {
    const directRes = await videoApi.getDirectUrl(actualUrl, actualFormatId)
    
    if (directRes.success && directRes.direct_url && !directRes.needs_server) {
      ElMessage.success('获取直链成功，开始下载...')
      
      const response = await fetch(directRes.direct_url, {
        mode: 'cors',
        credentials: 'omit',
      })
      
      if (!response.ok) {
        throw new Error('下载失败')
      }
      
      const blob = await response.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = `${videoInfo.value?.title || 'video'}.${directRes.ext || 'mp4'}`
      a.click()
      URL.revokeObjectURL(downloadUrl)
      
      downloadingFormat.value = null
      return
    }
    
    if (directRes.needs_server) {
      ElMessage.info('该格式需要服务器处理，请稍候...')
    }
  } catch (err) {
    console.log('[Direct URL Error]', err)
  }

  downloadProgress.value = {
    progress: 0,
    speed: '计算中...',
    eta: '--',
    filename: '准备下载...',
  }

  const downloadParams = {
    url: actualUrl,
    format_id: actualFormatId,
    quality: quality.value,
    audio_only: quality.value === 'audio',
    video_title: videoInfo.value?.title,
  }
  
  if (videoInfo.value?.platform === 'bilibili') {
    downloadParams.video_id = videoInfo.value?.id
  }

  try {
    const res = await videoApi.download(downloadParams)

    if (res.success) {
      ElMessage.success('下载成功！')
      downloadProgress.value = {
        progress: 100,
        speed: '已完成',
        eta: '--',
        filename: res.file_name,
      }
      
      const downloadUrl = `/api/v1/download/${encodeURIComponent(res.file_name)}`
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = res.file_name
      a.click()
    } else {
      ElMessage.error(res.message || '下载失败')
      downloadProgress.value = null
    }
  } catch (err) {
    console.error('[Download Error]', err)
    downloadProgress.value = null
  } finally {
    downloadingFormat.value = null
  }
}, 1500)

// ==================== 快速下载 ====================

const handleQuickDownload = createThrottle(async () => {
  if (quickDownloading.value) {
    return
  }
  
  quickDownloading.value = true
  downloadProgress.value = {
    progress: 0,
    speed: '计算中...',
    eta: '--',
    filename: '准备下载...',
  }

  // B站多P视频：构建正确的下载参数
  let actualUrl = url.value
  if (isMultiPart.value && selectedPart.value) {
    const pIndex = selectedPart.value.format_id.slice(1)
    const baseUrl = actualUrl.split('?')[0]
    actualUrl = `${baseUrl}?p=${pIndex}`
  }

  const downloadParams = {
    url: actualUrl,
    quality: quality.value,
    audio_only: quality.value === 'audio',
    video_title: videoInfo.value?.title,
  }
  
  if (videoInfo.value?.platform === 'bilibili') {
    downloadParams.video_id = videoInfo.value?.id
  }

  try {
    const res = await videoApi.download(downloadParams)

    if (res.success) {
      ElMessage.success('下载成功！')
      downloadProgress.value = {
        progress: 100,
        speed: '已完成',
        eta: '--',
        filename: res.file_name,
      }
      
      const downloadUrl = `/api/v1/download/${encodeURIComponent(res.file_name)}`
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = res.file_name
      a.click()
    } else {
      ElMessage.error(res.message || '下载失败')
      downloadProgress.value = null
    }
  } catch (err) {
    console.error('[Quick Download Error]', err)
    downloadProgress.value = null
  } finally {
    quickDownloading.value = false
  }
}, 1500)

// ==================== 图片下载 ====================

const handleDownloadImage = createThrottle(async (imageUrl, index) => {
  if (!imageUrl) {
    ElMessage.error('无法获取图片地址')
    return
  }
  
  try {
    ElMessage.info(`正在下载第 ${index} 张图片...`)
    
    if (imageUrl.startsWith('data:')) {
      const a = document.createElement('a')
      a.href = imageUrl
      a.download = `${videoInfo.value?.title || 'image'}_${index}.jpg`
      a.click()
      ElMessage.success('下载成功！')
      return
    }
    
    const proxyUrl = getProxiedImageUrl(imageUrl)
    
    const response = await fetch(proxyUrl, {
      mode: 'cors',
      credentials: 'omit',
    })
    
    if (!response.ok) {
      throw new Error('下载失败')
    }
    
    const blob = await response.blob()
    const downloadUrl = URL.createObjectURL(blob)
    const ext = imageUrl.includes('.png') ? 'png' : (imageUrl.includes('.webp') ? 'webp' : 'jpg')
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `${videoInfo.value?.title || 'image'}_${index}.${ext}`
    a.click()
    URL.revokeObjectURL(downloadUrl)
    
    ElMessage.success('下载成功！')
  } catch (err) {
    console.error('[Image Download Error]', err)
    ElMessage.error('下载失败：' + (err.message || '网络错误'))
  }
}, 500)

// ==================== 下载全部图片 ====================

const handleDownloadGallery = createThrottle(async () => {
  if (quickDownloading.value) {
    return
  }
  
  quickDownloading.value = true
  
  try {
    const res = await videoApi.download({
      url: url.value,
      video_title: videoInfo.value?.title,
    })
    
    if (res.success) {
      ElMessage.success('下载成功！')
      
      const downloadUrl = `/api/v1/download/${encodeURIComponent(res.file_name)}`
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = res.file_name
      a.click()
    } else {
      ElMessage.error(res.message || '下载失败')
    }
  } catch (err) {
    console.error('[Gallery Download Error]', err)
  } finally {
    quickDownloading.value = false
  }
}, 1500)

// ==================== 工具函数 ====================

function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatNumber(num) {
  if (!num || isNaN(num)) return '0'
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + 'M'
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'K'
  }
  return num.toString()
}

function formatFileSize(bytes) {
  if (!bytes || isNaN(bytes)) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let unitIndex = 0
  let size = bytes
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return size.toFixed(1) + ' ' + units[unitIndex]
}

function getPlatformLabel(platform) {
  const labels = {
    youtube: 'YouTube',
    bilibili: 'Bilibili',
    douyin: '抖音',
    tiktok: 'TikTok',
    twitter: 'Twitter/X',
    instagram: 'Instagram',
    xiaohongshu: '小红书',
  }
  return labels[platform] || platform
}

function getProxiedImageUrl(url) {
  if (!url) return ''
  if (url.startsWith('data:')) {
    return url
  }
  const needsProxy = ['douyinpic.com', 'xiaohongshu.com', 'xhscdn.com'].some(d => url.includes(d))
  if (needsProxy) {
    return `/api/v1/proxy/image?url=${encodeURIComponent(url)}`
  }
  return url
}

// ==================== 生命周期 ====================

onUnmounted(() => {
  // 清理冷却计时器
  if (cooldownTimer) {
    clearInterval(cooldownTimer)
    cooldownTimer = null
  }
  
  // 取消所有待处理请求
  videoApi.cancelAll?.()
})
</script>

<style lang="scss" scoped>
// 过渡动画
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.4s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(20px);
}

// 图片占位符样式
.image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--dark-surface, #1a1a2e);
  
  .el-icon {
    font-size: 2rem;
    color: rgba(255, 255, 255, 0.3);
  }
}

// 分P清晰度加载状态
.loading-formats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 20px;
  color: var(--text-muted, rgba(255, 255, 255, 0.6));
  font-size: 14px;
  
  .el-icon {
    font-size: 18px;
  }
}
</style>