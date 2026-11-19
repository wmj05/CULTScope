export const MULTI_GENRE_NOTE =
  '一部电影可属于多个 IMDb 类型，会分别计入各类型，因此类型计数之和可能大于电影总数。'

export const TREND_NOTE =
  '平均评分只使用有效评分样本；样本量较小的年份波动较大，不应视为可靠趋势。'

function asCount(value) {
  return Number.isFinite(Number(value)) ? Number(value) : 0
}

export function toDecadeSeries(perYear = {}) {
  const decades = new Map()
  for (const [yearText, bucket] of Object.entries(perYear ?? {})) {
    const year = Number(yearText)
    if (!Number.isInteger(year)) continue
    const decade = Math.floor(year / 10) * 10
    const current = decades.get(decade) ?? { total: 0, rated: 0 }
    current.total += asCount(bucket?.total_movies)
    current.rated += asCount(bucket?.rated_movies)
    decades.set(decade, current)
  }
  return [...decades.entries()]
    .sort(([left], [right]) => left - right)
    .map(([decade, counts]) => ({ decade: `${decade}s`, ...counts }))
}

export function toGenreSeries(distribution = {}) {
  return Object.entries(distribution ?? {})
    .map(([genre, count]) => ({ genre, count: asCount(count) }))
    .sort((left, right) => right.count - left.count || left.genre.localeCompare(right.genre))
}

export function toRatingSeries(distribution = {}) {
  return Object.entries(distribution ?? {})
    .map(([bucket, count]) => ({ bucket, count: asCount(count) }))
    .sort((left, right) => Number.parseFloat(left.bucket) - Number.parseFloat(right.bucket))
}

export function toVotesSeries(distribution = {}, bucketOrder = []) {
  const order = new Map(bucketOrder.map((bucket, index) => [bucket, index]))
  return Object.entries(distribution ?? {})
    .map(([bucket, count]) => ({ bucket, count: asCount(count) }))
    .sort((left, right) => {
      const leftOrder = order.get(left.bucket) ?? Number.POSITIVE_INFINITY
      const rightOrder = order.get(right.bucket) ?? Number.POSITIVE_INFINITY
      return leftOrder - rightOrder || left.bucket.localeCompare(right.bucket)
    })
}

export function toTrendSeries(trend = {}) {
  return Object.entries(trend ?? {})
    .map(([yearText, entry]) => ({
      year: Number(yearText),
      ratingMean: entry?.rating_mean ?? null,
      validRatingCount: asCount(entry?.valid_rating_count),
      ratedCount: asCount(entry?.rated_count)
    }))
    .filter((entry) => Number.isInteger(entry.year))
    .sort((left, right) => left.year - right.year)
}

export function buildImdbViewModel(payload = {}) {
  const coverage = payload.coverage ?? {}
  const yearDistribution = payload.year_distribution ?? {}
  const decadeDistribution = toDecadeSeries(yearDistribution.per_year)
  const genreDistribution = toGenreSeries(payload.genre_distribution)
  const ratingDistribution = toRatingSeries(payload.rating_distribution)
  const votesDistribution = toVotesSeries(
    payload.votes_distribution,
    payload.aggregate_constraints?.votes_bucket_definition ?? []
  )
  const yearTrend = toTrendSeries(payload.year_rating_trend)
  const total = asCount(coverage.total_movies)

  return {
    coverage: {
      total,
      rated: asCount(coverage.rated_movies),
      unrated: asCount(coverage.unrated_movies),
      ratio: coverage.coverage_ratio,
      orphanRatings: asCount(coverage.orphan_ratings)
    },
    generatedAt: payload.generated_at ?? '',
    scopeNote: payload.scope_note ?? '',
    sources: [payload.basics_input?.label, payload.ratings_input?.label].filter(Boolean),
    multiGenreNote: MULTI_GENRE_NOTE,
    trendNote: TREND_NOTE,
    missingYear: asCount(yearDistribution.missing_year),
    invalidYear: asCount(yearDistribution.invalid_year),
    futureYear: asCount(yearDistribution.future_year),
    qualityFlags: payload.quality_flags ?? {},
    duplicateCounts: payload.duplicate_counts ?? {},
    decadeDistribution,
    genreDistribution,
    ratingDistribution,
    votesDistribution,
    yearTrend,
    isEmpty:
      total === 0 &&
      [decadeDistribution, genreDistribution, ratingDistribution, votesDistribution, yearTrend].every(
        (series) => series.length === 0
      )
  }
}

export function formatSnapshotTime(value) {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

export function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '—'
  const ratio = Number(value)
  return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(2)}%` : '—'
}
