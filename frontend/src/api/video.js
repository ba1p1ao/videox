/**
 * 视频 API 封装
 * 包含完整的错误处理、重试机制、请求取消
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

// ==================== Axios 实例配置 ====================

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000, // 30秒超时（与后端一致）
  retry: {
    count: 2,           // 重试次数
    delay: 1000,        // 重试延迟（毫秒）
    statusCodes: [408, 429, 500, 502, 503, 504], // 需要重试的状态码
  },
})

// ==================== 请求取消机制 ====================

const pendingRequests = new Map()

/**
 * 生成请求唯一标识
 */
function generateRequestKey(config) {
  const { method, url, params, data } = config
  return `${method}-${url}-${JSON.stringify(params)}-${JSON.stringify(data)}`
}

/**
 * 添加请求到待处理队列
 */
function addPendingRequest(config) {
  const key = generateRequestKey(config)
  if (pendingRequests.has(key)) {
    // 取消之前的相同请求
    pendingRequests.get(key).abort('取消重复请求')
  }
  const controller = new AbortController()
  config.signal = controller.signal
  pendingRequests.set(key, controller)
}

/**
 * 从待处理队列移除请求
 */
function removePendingRequest(config) {
  const key = generateRequestKey(config)
  pendingRequests.delete(key)
}

/**
 * 取消所有待处理请求（路由跳转时调用）
 */
export function cancelAllRequests() {
  pendingRequests.forEach((controller) => {
    controller.abort('路由跳转，取消请求')
  })
  pendingRequests.clear()
}

// ==================== 请求拦截器 ====================

api.interceptors.request.use(
  (config) => {
    // 添加请求到队列
    addPendingRequest(config)
    
    // 添加 token（如果有）
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    
    // 添加请求 ID（用于日志追踪）
    config.headers['X-Request-ID'] = generateRequestId()
    
    return config
  },
  (error) => {
    console.error('[Request Error]', error)
    return Promise.reject(error)
  }
)

/**
 * 生成请求 ID
 */
function generateRequestId() {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
}

// ==================== 响应拦截器 ====================

api.interceptors.response.use(
  (response) => {
    // 移除待处理请求
    removePendingRequest(response.config)
    return response.data
  },
  async (error) => {
    const { config, response, code, message } = error
    
    // 移除待处理请求
    if (config) {
      removePendingRequest(config)
    }
    
    // 取消请求不处理
    if (error.name === 'CanceledError' || message?.includes('cancel')) {
      return Promise.reject(error)
    }
    
    // ========== 超时处理 ==========
    if (code === 'ECONNABORTED' || message?.includes('timeout')) {
      // 尝试重试
      if (config?.retry?.count > 0) {
        return retryRequest(config)
      }
      ElMessage.error('请求超时，请稍后重试')
      return Promise.reject(new Error('请求超时'))
    }
    
    // ========== 网络错误 ==========
    if (!response) {
      ElMessage.error('网络连接失败，请检查网络')
      return Promise.reject(new Error('网络错误'))
    }
    
    // ========== HTTP 状态码处理 ==========
    const status = response.status
    const errorData = response.data
    
    // 尝试重试
    if (config?.retry?.statusCodes?.includes(status) && config.retry.count > 0) {
      return retryRequest(config)
    }
    
    // 根据状态码显示不同提示
    switch (status) {
      case 400:
        ElMessage.error(errorData?.detail || '请求参数错误')
        break
      case 401:
        ElMessage.error('登录已过期，请重新登录')
        // 清除 token
        localStorage.removeItem('token')
        break
      case 403:
        ElMessage.error('没有权限访问该资源')
        break
      case 404:
        ElMessage.error('请求的资源不存在')
        break
      case 422:
        ElMessage.error(errorData?.message || '参数校验失败')
        break
      case 429:
        ElMessage.error('请求过于频繁，请稍后再试')
        break
      case 500:
        ElMessage.error('服务器内部错误')
        break
      case 502:
      case 503:
      case 504:
        ElMessage.error('服务暂时不可用，请稍后重试')
        break
      default:
        ElMessage.error(errorData?.detail || `请求失败 (${status})`)
    }
    
    return Promise.reject(new Error(errorData?.detail || `HTTP ${status}`))
  }
)

/**
 * 重试请求
 */
async function retryRequest(config) {
  config.retry.count -= 1
  
  // 显示重试提示
  console.log(`[Retry] 第 ${config.retry.count + 1} 次重试: ${config.url}`)
  
  // 延迟后重试
  await new Promise(resolve => setTimeout(resolve, config.retry.delay))
  
  return api.request(config)
}

// ==================== API 方法 ====================

export const videoApi = {
  /**
   * 解析视频信息
   * @param {string} url - 视频 URL
   * @param {string} cookies - Cookie 字符串（可选）
   */
  parse(url, cookies = '') {
    return api.post('/parse', { url, cookies: cookies || undefined })
  },

  /**
   * 获取直链
   * @param {string} url - 视频 URL
   * @param {string} formatId - 格式 ID
   * @param {string} cookies - Cookie 字符串（可选）
   */
  getDirectUrl(url, formatId, cookies = '') {
    return api.post('/direct-url', { url, format_id: formatId, cookies: cookies || undefined })
  },

  /**
   * 下载视频
   * @param {object} params - 下载参数
   */
  download(params) {
    return api.post('/download', params, {
      timeout: 300000, // 5分钟超时（视频下载可能很慢）
    })
  },

  /**
   * 获取下载进度
   */
  getProgress(taskId) {
    return api.get(`/progress/${taskId}`)
  },

  /**
   * 获取支持的平台列表
   */
  getPlatforms() {
    return api.get('/platforms')
  },

  /**
   * 健康检查
   */
  healthCheck() {
    return api.get('/health')
  },
  
  /**
   * 取消所有请求
   */
  cancelAll: cancelAllRequests,
}

// 默认导出
export default videoApi