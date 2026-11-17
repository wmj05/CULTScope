import assert from 'node:assert/strict'
import test from 'node:test'

import { parseRoute } from '../src/router.js'

test('空 hash 与根路径回到数据看板', () => {
  assert.equal(parseRoute('').name, 'dashboard')
  assert.equal(parseRoute('#/').name, 'dashboard')
  assert.equal(parseRoute(undefined).name, 'dashboard')
})

test('未知 hash 不报错，回落到数据看板', () => {
  assert.deepEqual(parseRoute('#/unknown'), {
    name: 'dashboard',
    seedId: '',
    invalid: false
  })
})

test('知识库列表路径', () => {
  assert.equal(parseRoute('#/knowledge').name, 'knowledge')
  assert.equal(parseRoute('#/knowledge/').name, 'knowledge')
})

test('知识库详情路径解析 seedId', () => {
  assert.deepEqual(parseRoute('#/knowledge/CS-0003'), {
    name: 'knowledge-detail',
    seedId: 'CS-0003',
    invalid: false
  })
})

test('详情路径支持 URL 编码', () => {
  const route = parseRoute('#/knowledge/%E6%B4%9B%E5%9F%BA')
  assert.equal(route.name, 'knowledge-detail')
  assert.equal(route.seedId, '洛基')
})

test('非法 URL 编码进入 invalid-route 而不是抛错', () => {
  const route = parseRoute('#/knowledge/%E0%A4%A')
  assert.equal(route.name, 'invalid-route')
  assert.equal(route.invalid, true)
  assert.equal(route.seedId, '')
})

test('编码后的斜杠按原样作为 seedId', () => {
  const route = parseRoute('#/knowledge/%2F')
  assert.equal(route.name, 'knowledge-detail')
  assert.equal(route.seedId, '/')
})
