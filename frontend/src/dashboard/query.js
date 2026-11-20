/**
 * TMDb 看板查询参数构造。
 *
 * 与修改前的内联逻辑保持一致：空筛选不传字段，非空筛选原样传入。
 */

function normalize(value) {
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * @param {{ decade?: string, genre?: string }} [filters]
 * @returns {{ decade?: string, genre?: string }}
 */
export function buildMovieParams(filters = {}) {
  const params = {}
  const decade = normalize(filters.decade)
  const genre = normalize(filters.genre)
  if (decade) params.decade = decade
  if (genre) params.genre = genre
  return params
}
