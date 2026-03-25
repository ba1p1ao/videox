import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    // 安全头配置
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'X-XSS-Protection': '1; mode=block',
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 目标浏览器
    target: 'es2015',
    
    // 输出目录
    outDir: 'dist',
    
    // 启用压缩（使用 esbuild）
    minify: 'esbuild',
    
    // Rollup 配置
    rollupOptions: {
      output: {
        // 分包策略
        manualChunks: {
          // Vue 生态
          'vue-vendor': ['vue', 'pinia'],
          // Element Plus
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          // Axios
          'axios': ['axios'],
        },
        // 文件名格式
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          const info = assetInfo.name.split('.')
          let extType = info[info.length - 1]
          if (/\.(png|jpe?g|gif|svg|webp|ico)$/i.test(assetInfo.name)) {
            return 'assets/images/[name]-[hash].[ext]'
          } else if (/\.(woff2?|eot|ttf|otf)$/i.test(assetInfo.name)) {
            return 'assets/fonts/[name]-[hash].[ext]'
          } else if (/\.css$/i.test(assetInfo.name)) {
            return 'assets/css/[name]-[hash].[ext]'
          }
          return 'assets/[name]-[hash].[ext]'
        },
      },
    },
    
    // Chunk 大小警告阈值
    chunkSizeWarningLimit: 1000,
    
    // 启用 source map（生产环境可关闭）
    sourcemap: false,
    
    // CSS 代码分割
    cssCodeSplit: true,
  },
  
  // CSS 配置
  css: {
    preprocessorOptions: {
      scss: {
        // 禁用废弃警告
        silenceDeprecations: ['legacy-js-api'],
      },
    },
  },
  
  // 依赖优化
  optimizeDeps: {
    include: [
      'vue',
      'pinia',
      'axios',
      'element-plus/es',
      'element-plus/es/components/message/style/css',
      'element-plus/es/components/button/style/css',
      'element-plus/es/components/input/style/css',
      'element-plus/es/components/image/style/css',
      'element-plus/es/components/progress/style/css',
    ],
  },
})