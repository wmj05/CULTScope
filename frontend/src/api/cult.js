import http from './http'

// Cult 知识库只读接口封装
export function fetchCultMovies(params) {
  return http.get('/cult/movies', { params }).then((response) => response.data)
}

export function fetchCultMovie(seedId) {
  return http.get(`/cult/movies/${encodeURIComponent(seedId)}`).then((response) => response.data)
}

export function fetchCultEvidence(seedId, includePending = false) {
  return http
    .get(`/cult/movies/${encodeURIComponent(seedId)}/evidence`, {
      params: { include_pending: includePending }
    })
    .then((response) => response.data)
}

export function fetchCultTags(seedId, includeCandidates = false) {
  return http
    .get(`/cult/movies/${encodeURIComponent(seedId)}/tags`, {
      params: { include_candidates: includeCandidates }
    })
    .then((response) => response.data)
}

export function fetchCultCriteria() {
  return http.get('/cult/criteria').then((response) => response.data)
}

export function fetchCultTagDictionary() {
  return http.get('/cult/tags').then((response) => response.data)
}

export function fetchCultStats() {
  return http.get('/cult/stats').then((response) => response.data)
}

// 只向前端暴露友好文案，不透传后端内部异常信息
export function describeCultError(error) {
  const status = error?.response?.status
  if (status === 503) return '知识库暂时不可用，请稍后再试。'
  if (status === 404) return '未找到该电影。'
  if (status === 422) return '查询条件不合法，请调整后重试。'
  return '请求失败，请确认后端服务已启动。'
}
