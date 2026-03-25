/**
 * Pinia 状态管理 - 视频下载
 * 支持本地持久化存储
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { videoApi } from '../api/video'

// 本地存储键名
const STORAGE_KEYS = {
  DOWNLOAD_HISTORY: 'video_downloader_history',
  PREFERENCES: 'video_downloader_prefs',
}

// 最大历史记录数量
const MAX_HISTORY_COUNT = 50

/**
 * 从 localStorage 读取数据
 */
function loadFromStorage(key, defaultValue = null) {
  try {
    const data = localStorage.getItem(key)
    return data ? JSON.parse(data) : defaultValue
  } catch (error) {
    console.warn(`[Storage] 读取 ${key} 失败:`, error)
    return defaultValue
  }
}

/**
 * 保存数据到 localStorage
 */
function saveToStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch (error) {
    console.warn(`[Storage] 保存 ${key} 失败:`, error)
  }
}

export const useVideoStore = defineStore('video', () => {
  // ==================== 状态 ====================
  
  // 当前视频信息
  const currentVideo = ref(null)
  
  // 下载历史（从本地存储恢复）
  const downloadHistory = ref(loadFromStorage(STORAGE_KEYS.DOWNLOAD_HISTORY, []))
  
  // 下载状态
  const downloading = ref(false)
  
  // 下载进度
  const progress = ref(null)
  
  // 用户偏好设置
  const preferences = ref(loadFromStorage(STORAGE_KEYS.PREFERENCES, {
    defaultQuality: 'best',
    autoSaveHistory: true,
  }))

  // ==================== 计算属性 ====================
  
  // 历史记录数量
  const historyCount = computed(() => downloadHistory.value.length)
  
  // 最近下载
  const recentDownloads = computed(() => downloadHistory.value.slice(0, 10))

  // ==================== Actions ====================

  /**
   * 解析视频
   */
  async function parseVideo(url) {
    const res = await videoApi.parse(url)
    if (res.success) {
      currentVideo.value = res.video_info
    }
    return res
  }

  /**
   * 下载视频
   */
  async function downloadVideo(options) {
    downloading.value = true
    progress.value = { status: 'pending', percent: 0 }
    
    try {
      const res = await videoApi.download(options)
      
      if (res.success) {
        // 添加到历史记录
        if (preferences.value.autoSaveHistory) {
          addToHistory({
            ...res,
            video: currentVideo.value,
            downloadedAt: new Date().toISOString(),
          })
        }
        
        progress.value = { status: 'completed', percent: 100 }
      }
      
      return res
    } catch (error) {
      progress.value = { status: 'error', error: error.message }
      throw error
    } finally {
      downloading.value = false
    }
  }

  /**
   * 添加到历史记录
   */
  function addToHistory(record) {
    // 检查是否已存在相同记录
    const existingIndex = downloadHistory.value.findIndex(
      item => item.file_name === record.file_name
    )
    
    if (existingIndex > -1) {
      // 更新现有记录
      downloadHistory.value[existingIndex] = record
    } else {
      // 添加新记录
      downloadHistory.value.unshift(record)
      
      // 限制历史记录数量
      if (downloadHistory.value.length > MAX_HISTORY_COUNT) {
        downloadHistory.value = downloadHistory.value.slice(0, MAX_HISTORY_COUNT)
      }
    }
    
    // 持久化
    saveToStorage(STORAGE_KEYS.DOWNLOAD_HISTORY, downloadHistory.value)
  }

  /**
   * 清除当前视频
   */
  function clearCurrentVideo() {
    currentVideo.value = null
    progress.value = null
  }

  /**
   * 清除下载历史
   */
  function clearHistory() {
    downloadHistory.value = []
    saveToStorage(STORAGE_KEYS.DOWNLOAD_HISTORY, [])
  }

  /**
   * 删除单条历史记录
   */
  function removeFromHistory(index) {
    downloadHistory.value.splice(index, 1)
    saveToStorage(STORAGE_KEYS.DOWNLOAD_HISTORY, downloadHistory.value)
  }

  /**
   * 更新偏好设置
   */
  function updatePreferences(newPrefs) {
    preferences.value = { ...preferences.value, ...newPrefs }
    saveToStorage(STORAGE_KEYS.PREFERENCES, preferences.value)
  }

  /**
   * 重置所有状态
   */
  function reset() {
    currentVideo.value = null
    downloading.value = false
    progress.value = null
  }

  return {
    // 状态
    currentVideo,
    downloadHistory,
    downloading,
    progress,
    preferences,
    
    // 计算属性
    historyCount,
    recentDownloads,
    
    // Actions
    parseVideo,
    downloadVideo,
    clearCurrentVideo,
    clearHistory,
    removeFromHistory,
    updatePreferences,
    reset,
  }
})