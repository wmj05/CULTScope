/**
 * TMDb 看板错误文案映射。
 *
 * 纯函数、无副作用：只把 axios / 未知异常转换为固定的中文提示，
 * 绝不回显原始 message、后端 detail、路径或堆栈。
 */

// 后端已确认安全的固定文案（与 backend/app/api/movies.py 的 MOVIES_DATA_UNAVAILABLE 对齐）
export const SAFE_SERVER_MESSAGES = Object.freeze(['电影数据暂时不可用，请稍后重试'])

const TIMEOUT_MESSAGE = '请求超时，请检查网络后重试'
const NETWORK_MESSAGE = '无法连接服务器，请确认后端服务已启动'
const SERVER_MESSAGE = '服务暂时不可用，请稍后重试'
const FALLBACK_MESSAGE = '数据加载失败，请稍后重试'

function isCanceled(error) {
  return error.code === 'ERR_CANCELED' || error.__CANCEL__ === true
}

function isTimeout(error) {
  return error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
}

function isNetworkFailure(error) {
  if (error.code === 'ERR_NETWORK') return true
  // 请求已发出但没有任何响应，才视为连接失败；无 request 的异常不算网络错误
  return Boolean(error.request) && !error.response
}

/**
 * @param {unknown} error
 * @returns {string} 面向用户的中文提示；取消请求返回空字符串（不展示错误）
 */
export function describeApiError(error) {
  if (!error || typeof error !== 'object') return FALLBACK_MESSAGE
  if (isCanceled(error)) return ''

  const response = error.response
  const detail = response && response.data ? response.data.detail : undefined
  if (typeof detail === 'string' && SAFE_SERVER_MESSAGES.includes(detail)) {
    return detail
  }

  if (isTimeout(error)) return TIMEOUT_MESSAGE
  if (isNetworkFailure(error)) return NETWORK_MESSAGE
  if (response) return SERVER_MESSAGE
  return FALLBACK_MESSAGE
}
