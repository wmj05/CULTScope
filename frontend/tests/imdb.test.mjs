import assert from 'node:assert/strict'
import test, { afterEach } from 'node:test'

import http from '../src/api/http.js'
import { describeImdbError, fetchImdbAggregates } from '../src/api/imdb.js'
import {
  makeDecadeOption,
  makeGenreOption,
  makeRatingOption,
  makeTrendOption,
  makeVotesOption
} from '../src/imdb/chartOptions.js'
import {
  MULTI_GENRE_NOTE,
  TREND_NOTE,
  buildImdbViewModel,
  formatPercent,
  toDecadeSeries,
  toGenreSeries,
  toRatingSeries,
  toTrendSeries,
  toVotesSeries
} from '../src/imdb/model.js'
import { parseRoute } from '../src/router.js'

const originalGet = http.get

afterEach(() => {
  http.get = originalGet
})

test('IMDb API 只请求聚合端点并返回正常响应', async () => {
  const payload = { generated_at: '2026-11-19T00:00:00Z', coverage: { total_movies: 2 } }
  let requestedPath = ''
  http.get = async (path) => {
    requestedPath = path
    return { data: payload }
  }

  assert.deepEqual(await fetchImdbAggregates(), payload)
  assert.equal(requestedPath, '/imdb/aggregates')
})

test('503 返回明确且安全的不可用提示', () => {
  const message = describeImdbError({
    response: { status: 503, data: { detail: 'C:\\private\\aggregate.json' } }
  })
  assert.match(message, /暂时不可用/)
  assert.match(message, /聚合数据/)
  assert.doesNotMatch(message, /private|aggregate\.json/)
})

test('网络失败与其他加载失败使用不同提示', () => {
  assert.match(describeImdbError(new Error('Network Error')), /无法连接/)
  assert.match(describeImdbError({ response: { status: 500 } }), /加载失败/)
})

test('空聚合数据被识别为空状态而不是零评分', () => {
  const model = buildImdbViewModel({
    coverage: { total_movies: 0, rated_movies: 0, unrated_movies: 0, coverage_ratio: null }
  })
  assert.equal(model.isEmpty, true)
  assert.equal(model.yearTrend.length, 0)
  assert.equal(formatPercent(model.coverage.ratio), '—')
})

test('正常响应构建概览、来源和后端 scope_note', () => {
  const model = buildImdbViewModel({
    generated_at: '2026-11-19T00:00:00Z',
    scope_note: '当前快照说明',
    basics_input: { label: 'backend/data/basics.csv' },
    ratings_input: { label: 'external:title.ratings.tsv' },
    coverage: {
      total_movies: 10,
      rated_movies: 4,
      unrated_movies: 6,
      coverage_ratio: 0.4,
      orphan_ratings: 0
    }
  })
  assert.equal(model.coverage.total, 10)
  assert.equal(model.coverage.rated, 4)
  assert.equal(model.coverage.unrated, 6)
  assert.equal(formatPercent(model.coverage.ratio), '40.00%')
  assert.equal(model.scopeNote, '当前快照说明')
  assert.deepEqual(model.sources, ['backend/data/basics.csv', 'external:title.ratings.tsv'])
})

test('年份按十年归组并同时保留总量和已评分数', () => {
  const result = toDecadeSeries({
    1999: { total_movies: 2, rated_movies: 1 },
    1990: { total_movies: 3, rated_movies: 2 },
    2001: { total_movies: 4, rated_movies: 4 },
    invalid: { total_movies: 100, rated_movies: 100 }
  })
  assert.deepEqual(result, [
    { decade: '1990s', total: 5, rated: 3 },
    { decade: '2000s', total: 4, rated: 4 }
  ])
  assert.deepEqual(makeDecadeOption(result).series.map((series) => series.data), [[5, 4], [3, 4]])
})

test('评分分布按 0.5 分桶的数值边界排序', () => {
  const result = toRatingSeries({
    '9.5-10.0': 1,
    '8.0-8.5': 3,
    '7.5-8.0': 2
  })
  assert.deepEqual(result.map((entry) => entry.bucket), ['7.5-8.0', '8.0-8.5', '9.5-10.0'])
  assert.deepEqual(makeRatingOption(result).series[0].data, [2, 3, 1])
})

test('投票分布严格沿用后端桶顺序', () => {
  const distribution = { '11-100': 5, invalid: 1, '1-10': 4, other: 2 }
  const order = ['invalid', '1-10', '11-100', '101-1k']
  const result = toVotesSeries(distribution, order)
  assert.deepEqual(result.map((entry) => entry.bucket), ['invalid', '1-10', '11-100', 'other'])
  assert.deepEqual(makeVotesOption(result).xAxis.data, ['invalid', '1-10', '11-100', 'other'])
})

test('多类型电影重复计入说明明确保留', () => {
  const genres = toGenreSeries({ Drama: 2, Comedy: 3, Action: 2 })
  assert.deepEqual(genres.map((entry) => entry.genre), ['Comedy', 'Action', 'Drama'])
  assert.match(MULTI_GENRE_NOTE, /多个 IMDb 类型/)
  assert.match(MULTI_GENRE_NOTE, /大于电影总数/)
  assert.equal(buildImdbViewModel().multiGenreNote, MULTI_GENRE_NOTE)
  assert.equal(makeGenreOption(genres).yAxis.inverse, true)
})

test('无效评分与无效票数被明确标记为不计入分布', () => {
  const model = buildImdbViewModel({
    coverage: { total_movies: 5, rated_movies: 2, unrated_movies: 3, coverage_ratio: 0.4 },
    quality_flags: { invalid_ratings_skipped: 3, invalid_votes_skipped: 2 }
  })
  assert.equal(model.invalidRatingsSkipped, 3)
  assert.equal(model.invalidVotesSkipped, 2)
  assert.match(model.qualityNote, /无效评分记录 3 条/)
  assert.match(model.qualityNote, /无效票数记录 2 条/)
  assert.match(model.qualityNote, /不计入评分分布与投票分布/)
})

test('年代分布只统计有效年份，缺失、异常和未来年份不计入', () => {
  const model = buildImdbViewModel({
    coverage: {
      total_movies: 11,
      rated_movies: 4,
      unrated_movies: 7,
      coverage_ratio: 0.363636
    },
    year_distribution: {
      per_year: {
        1999: { total_movies: 2, rated_movies: 1 },
        2001: { total_movies: 3, rated_movies: 2 }
      },
      missing_year: 4,
      invalid_year: 1,
      future_year: 1
    }
  })
  assert.deepEqual(model.decadeDistribution, [
    { decade: '1990s', total: 2, rated: 1 },
    { decade: '2000s', total: 3, rated: 2 }
  ])
  const decadeTotal = model.decadeDistribution.reduce((sum, entry) => sum + entry.total, 0)
  assert.equal(decadeTotal, 5)
  assert.ok(decadeTotal < model.coverage.total)
  const excludedTotal = model.missingYear + model.invalidYear + model.futureYear
  assert.equal(excludedTotal, 6)
  // 正常年份 + 缺失 + 异常 + 未来年份必须回到电影总数
  assert.equal(decadeTotal + excludedTotal, model.coverage.total)
  // 覆盖率分母一致性
  assert.equal(model.coverage.rated + model.coverage.unrated, model.coverage.total)
})

test('年份趋势保留 null 均值且不在图表中转换为 0', () => {
  const trend = toTrendSeries({
    1901: { rating_mean: 7.5, valid_rating_count: 4, rated_count: 5 },
    1900: { rating_mean: null, valid_rating_count: 0, rated_count: 2 }
  })
  assert.deepEqual(trend, [
    { year: 1900, ratingMean: null, validRatingCount: 0, ratedCount: 2 },
    { year: 1901, ratingMean: 7.5, validRatingCount: 4, ratedCount: 5 }
  ])

  const option = makeTrendOption(trend)
  const ratingSeries = option.series.find((series) => series.name === '平均评分')
  assert.deepEqual(ratingSeries.data, [null, 7.5])
  assert.equal(ratingSeries.connectNulls, false)
  assert.deepEqual(option.series.find((series) => series.name === '有效评分样本数').data, [0, 4])
  assert.equal(option.yAxis.length, 2)
  assert.equal(option.yAxis[0].max, 10)
  assert.deepEqual(option.series.map((series) => series.yAxisIndex), [0, 1])
  assert.deepEqual(option.dataZoom.map((zoom) => zoom.type), ['inside', 'slider'])
  assert.match(TREND_NOTE, /有效样本数/)
  assert.match(TREND_NOTE, /评分无效的样本不计入均值/)
  for (const zoom of option.dataZoom) {
    assert.equal(zoom.xAxisIndex, 0)
    assert.equal(zoom.start, 0)
    assert.equal(zoom.end, 100)
  }
})

test('所有图表配置提供 Tooltip 和图例', () => {
  const options = [
    makeDecadeOption([{ decade: '1990s', total: 1, rated: 1 }]),
    makeGenreOption([{ genre: 'Drama', count: 1 }]),
    makeRatingOption([{ bucket: '7.5-8.0', count: 1 }]),
    makeVotesOption([{ bucket: '1-10', count: 1 }]),
    makeTrendOption([{ year: 2000, ratingMean: 8, validRatingCount: 1 }])
  ]
  for (const option of options) {
    assert.equal(option.tooltip.trigger, 'axis')
    assert.notEqual(option.legend.show, false)
  }
  assert.deepEqual(options[0].series.map((series) => series.name), ['电影总量', '已有 IMDb 评分'])
  assert.equal(options[4].legend.show, undefined)
})

test('IMDb 路由可用且原有路由行为不变', () => {
  assert.deepEqual(parseRoute('#/imdb'), { name: 'imdb', seedId: '', invalid: false })
  assert.deepEqual(parseRoute('#/imdb/'), { name: 'imdb', seedId: '', invalid: false })
  assert.equal(parseRoute('#/').name, 'dashboard')
  assert.equal(parseRoute('#/knowledge').name, 'knowledge')
  assert.deepEqual(parseRoute('#/knowledge/CS-0003'), {
    name: 'knowledge-detail',
    seedId: 'CS-0003',
    invalid: false
  })
  assert.equal(parseRoute('#/unknown').name, 'dashboard')
})
