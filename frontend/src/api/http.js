import axios from 'axios'

// 统一 API 入口：开发环境由 Vite 代理到 FastAPI
const http = axios.create({
  baseURL: '/api',
  timeout: 10000
})

export default http
