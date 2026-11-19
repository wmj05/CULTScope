import http from './http.js'

// IMDb 统计只读接口：页面不读取 CSV，也不触发重新聚合
export function fetchImdbAggregates() {
  return http.get('/imdb/aggregates').then((response) => response.data)
}

// 不向用户透传后端异常详情或本机路径
export function describeImdbError(error) {
  const status = error?.response?.status
  if (status === 503) {
    return 'IMDb 统计服务暂时不可用，聚合数据可能尚未生成或无法读取，请稍后重试。'
  }
  if (!error?.response) {
    return '无法连接 IMDb 统计服务，请确认后端服务已启动后重试。'
  }
  return 'IMDb 统计加载失败，请稍后重试。'
}
