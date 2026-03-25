import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import App from './App.vue'
import './assets/styles/main.scss'

const app = createApp(App)
const pinia = createPinia()

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// ==================== 全局错误捕获 ====================

/**
 * Vue 组件错误处理器
 * 捕获组件渲染、生命周期钩子、侦听器中的错误
 */
app.config.errorHandler = (err, instance, info) => {
  // 生产环境上报错误
  if (import.meta.env.PROD) {
    console.error('[Vue Error]', err)
    // 可接入错误上报服务
    // reportError(err, { component: instance?.$options?.name, info })
  } else {
    console.error('[Vue Error]', err)
    console.error('[Component]', instance?.$options?.name || 'Unknown')
    console.error('[Error Info]', info)
  }
  
  // 显示友好提示
  ElMessage.error('页面发生错误，请刷新重试')
}

/**
 * Vue 警告处理器（仅开发环境）
 */
if (import.meta.env.DEV) {
  app.config.warnHandler = (msg, instance, trace) => {
    console.warn('[Vue Warning]', msg)
    if (trace) {
      console.warn('[Trace]', trace)
    }
  }
}

/**
 * 未捕获的 Promise Rejection
 * 捕获异步操作中未处理的错误
 */
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Promise Rejection]', event.reason)
  
  // 忽略取消请求的错误
  if (event.reason?.name === 'CanceledError' || 
      event.reason?.message?.includes('cancel')) {
    event.preventDefault()
    return
  }
  
  // 显示错误提示（避免重复提示）
  const message = event.reason?.message || '异步操作发生错误'
  if (!message.includes('timeout') && !message.includes('cancel')) {
    ElMessage.error(message)
  }
  
  event.preventDefault()
})

/**
 * 未捕获的 JS 错误
 * 捕获全局 JavaScript 运行时错误
 */
window.addEventListener('error', (event) => {
  // 忽略跨域脚本错误
  if (event.message.includes('Script error')) {
    return
  }
  
  console.error('[Uncaught Error]', event.error)
  
  // 生产环境上报
  if (import.meta.env.PROD) {
    // reportError(event.error, { filename: event.filename, lineno: event.lineno })
  }
  
  // 显示提示
  ElMessage.error('页面发生错误，请刷新重试')
}, { passive: true })

/**
 * 资源加载错误
 * 捕获图片、脚本、样式等资源加载失败
 */
window.addEventListener('error', (event) => {
  if (event.target && (event.target.tagName === 'IMG' || event.target.tagName === 'SCRIPT' || event.target.tagName === 'LINK')) {
    console.error('[Resource Load Error]', event.target.src || event.target.href)
    // 图片加载失败不需要提示用户
  }
}, { capture: true, passive: true })

// ==================== 应用挂载 ====================

app.use(pinia)
app.use(ElementPlus)
app.mount('#app')