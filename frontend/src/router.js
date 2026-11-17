// 轻量 hash 路由解析：不引入 vue-router
export function parseRoute(hash) {
  const raw = String(hash ?? '').replace(/^#\/?/, '')

  if (raw === 'knowledge' || raw === 'knowledge/') {
    return { name: 'knowledge', seedId: '', invalid: false }
  }

  if (raw.startsWith('knowledge/')) {
    const segment = raw.slice('knowledge/'.length)
    try {
      const seedId = decodeURIComponent(segment).trim()
      if (!seedId) return { name: 'knowledge', seedId: '', invalid: false }
      return { name: 'knowledge-detail', seedId, invalid: false }
    } catch {
      // 非法的 URL 编码（如 %E0%A4%A），交给页面显示友好提示
      return { name: 'invalid-route', seedId: '', invalid: true }
    }
  }

  return { name: 'dashboard', seedId: '', invalid: false }
}
