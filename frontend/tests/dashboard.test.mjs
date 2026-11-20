import test from 'node:test'
import assert from 'node:assert/strict'

import { SAFE_SERVER_MESSAGES, describeApiError } from '../src/dashboard/errors.js'
import { buildMovieParams } from '../src/dashboard/query.js'
import { createRequestSequence } from '../src/dashboard/requestSequence.js'

const TECHNICAL_MARKERS = ['Request failed', 'status code', 'AxiosError', 'ECONNABORTED', 'C:\\', '.csv']

function assertNoTechnicalLeak(message) {
  for (const marker of TECHNICAL_MARKERS) {
    assert.ok(!message.includes(marker), `错误文案不应包含技术信息：${marker}`)
  }
}

test('已确认安全的服务端文案原样展示', () => {
  const safe = SAFE_SERVER_MESSAGES[0]
  const error = {
    response: { status: 500, data: { detail: safe } }
  }

  assert.equal(describeApiError(error), safe)
})

test('未知 HTTP 500 返回通用中文提示且不含技术信息', () => {
  const error = {
    message: 'Request failed with status code 500',
    response: { status: 500, data: {} }
  }

  const message = describeApiError(error)

  assert.ok(message.length > 0)
  assert.notEqual(message, error.message)
  assertNoTechnicalLeak(message)
})

test('未经确认的后端 detail（含本地路径）不会展示', () => {
  const error = {
    response: {
      status: 500,
      data: { detail: '清洗数据不存在：C:\\Users\\demo\\backend\\data\\cult_movies_clean.csv' }
    }
  }

  const message = describeApiError(error)

  assert.ok(!message.includes('C:\\'))
  assert.ok(!message.includes('.csv'))
  assertNoTechnicalLeak(message)
})

test('请求超时返回超时提示', () => {
  const message = describeApiError({
    code: 'ECONNABORTED',
    message: 'timeout of 10000ms exceeded'
  })

  assert.ok(message.includes('超时'), message)
  assertNoTechnicalLeak(message)
})

test('ETIMEDOUT 同样识别为超时', () => {
  const message = describeApiError({ code: 'ETIMEDOUT' })

  assert.ok(message.includes('超时'), message)
})

test('ERR_NETWORK 识别为连接失败', () => {
  const message = describeApiError({
    code: 'ERR_NETWORK',
    message: 'Network Error',
    request: {}
  })

  assert.ok(message.includes('连接'), message)
  assert.ok(!message.includes('Network Error'))
})

test('请求已发出但无响应视为连接失败', () => {
  const message = describeApiError({ request: {}, response: undefined })

  assert.ok(message.includes('连接'), message)
})

test('普通未知异常使用兜底文案且不回显原始 message', () => {
  const error = new TypeError('boom: C:\\secret\\token')

  const message = describeApiError(error)

  assert.ok(message.length > 0)
  assert.ok(!message.includes('boom'))
  assert.ok(!message.includes('secret'))
  assertNoTechnicalLeak(message)
})

test('取消请求不产生面向用户的错误文案', () => {
  assert.equal(describeApiError({ code: 'ERR_CANCELED' }), '')
  assert.equal(describeApiError({ __CANCEL__: true }), '')
})

test('空值与非法输入使用兜底文案', () => {
  assert.ok(describeApiError(null).length > 0)
  assert.ok(describeApiError(undefined).length > 0)
})

test('无筛选时返回空参数对象', () => {
  assert.deepEqual(buildMovieParams({ decade: '', genre: '' }), {})
  assert.deepEqual(buildMovieParams({}), {})
  assert.deepEqual(buildMovieParams(), {})
})

test('仅年代筛选', () => {
  assert.deepEqual(buildMovieParams({ decade: '1970s', genre: '' }), { decade: '1970s' })
})

test('仅类型筛选', () => {
  assert.deepEqual(buildMovieParams({ decade: '', genre: '恐怖' }), { genre: '恐怖' })
})

test('年代与类型组合筛选', () => {
  assert.deepEqual(buildMovieParams({ decade: '1980s', genre: '科幻' }), {
    decade: '1980s',
    genre: '科幻'
  })
})

test('纯空白筛选值不作为参数发送', () => {
  assert.deepEqual(buildMovieParams({ decade: '   ', genre: '\t' }), {})
})

test('最近一次请求拥有最终显示权', () => {
  const sequence = createRequestSequence()
  const first = sequence.begin()
  const second = sequence.begin()

  assert.equal(sequence.isLatest(first), false)
  assert.equal(sequence.isLatest(second), true)
})

test('旧请求完成时不会被视为最新请求', () => {
  const sequence = createRequestSequence()
  const stale = sequence.begin()
  sequence.begin()

  // 模拟旧请求晚到：无论成功还是失败，都不应更新页面
  assert.equal(sequence.isLatest(stale), false)
})

test('多个独立序号互不影响', () => {
  const stats = createRequestSequence()
  const list = createRequestSequence()
  const statsToken = stats.begin()
  list.begin()

  assert.equal(stats.isLatest(statsToken), true)
})
