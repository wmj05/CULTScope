<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  describeCultError,
  fetchCultCriteria,
  fetchCultMovies,
  fetchCultStats,
  fetchCultTagDictionary
} from '../api/cult'

const STATUS_TABS = [
  { value: 'approved', label: '正式批准' },
  { value: 'pending', label: '待审核' },
  { value: 'all', label: '全部' }
]

const STATUS_LABELS = {
  approved: '已批准',
  pending: '待审核',
  draft: '草稿',
  rejected: '已驳回',
  needs_fix: '需修正'
}

const PAGE_SIZE = 6

const status = ref('approved')
const query = ref('')
const movies = ref([])
const total = ref(0)
const offset = ref(0)
const loading = ref(true)
const listError = ref('')

const stats = ref(null)
const statsLoading = ref(true)
const statsError = ref('')

const criteria = ref([])
const tagDictionary = ref([])
const dictionaryError = ref('')

let searchTimer = null
// 请求序号：只允许最新一次请求写入状态，避免快速切换时旧响应覆盖新结果
let moviesRequestId = 0
let statsRequestId = 0
let dictionaryRequestId = 0
let unmounted = false

const rangeStart = computed(() => (total.value ? offset.value + 1 : 0))
const rangeEnd = computed(() => offset.value + movies.value.length)
const canPrev = computed(() => offset.value > 0)
const canNext = computed(() => offset.value + movies.value.length < total.value)

function statusLabel(value) {
  return STATUS_LABELS[value] ?? value
}

async function loadMovies() {
  const requestId = ++moviesRequestId
  loading.value = true
  listError.value = ''
  try {
    const params = { status: status.value, limit: PAGE_SIZE, offset: offset.value }
    if (query.value.trim()) params.q = query.value.trim()
    const data = await fetchCultMovies(params)
    if (unmounted || requestId !== moviesRequestId) return

    // 数据变化导致当前页越界时，回退到最后一页
    if (!data.items.length && offset.value > 0 && data.total > 0) {
      offset.value = Math.floor((data.total - 1) / PAGE_SIZE) * PAGE_SIZE
      await loadMovies()
      return
    }

    movies.value = data.items
    total.value = data.total
  } catch (error) {
    if (unmounted || requestId !== moviesRequestId) return
    movies.value = []
    total.value = 0
    listError.value = describeCultError(error)
  } finally {
    if (!unmounted && requestId === moviesRequestId) loading.value = false
  }
}

function goToPrevPage() {
  if (!canPrev.value) return
  offset.value = Math.max(0, offset.value - PAGE_SIZE)
  loadMovies()
}

function goToNextPage() {
  if (!canNext.value) return
  offset.value += PAGE_SIZE
  loadMovies()
}

async function loadStats() {
  const requestId = ++statsRequestId
  statsLoading.value = true
  statsError.value = ''
  try {
    const data = await fetchCultStats()
    if (unmounted || requestId !== statsRequestId) return
    stats.value = data
  } catch (error) {
    if (unmounted || requestId !== statsRequestId) return
    statsError.value = describeCultError(error)
  } finally {
    if (!unmounted && requestId === statsRequestId) statsLoading.value = false
  }
}

async function loadDictionaries() {
  const requestId = ++dictionaryRequestId
  dictionaryError.value = ''
  try {
    const [criteriaData, tagsData] = await Promise.all([
      fetchCultCriteria(),
      fetchCultTagDictionary()
    ])
    if (unmounted || requestId !== dictionaryRequestId) return
    criteria.value = criteriaData.items
    tagDictionary.value = tagsData.items
  } catch (error) {
    if (unmounted || requestId !== dictionaryRequestId) return
    dictionaryError.value = describeCultError(error)
  }
}

watch(status, () => {
  offset.value = 0
  loadMovies()
})

watch(query, () => {
  window.clearTimeout(searchTimer)
  // 立即作废在途请求并进入加载态，避免防抖等待期间展示旧关键词的空结果
  moviesRequestId += 1
  loading.value = true
  listError.value = ''
  searchTimer = window.setTimeout(() => {
    offset.value = 0
    loadMovies()
  }, 300)
})

onMounted(() => {
  loadMovies()
  loadStats()
  loadDictionaries()
})

onBeforeUnmount(() => {
  unmounted = true
  window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="knowledge-view">
    <header class="kb-hero">
      <p class="kicker">PHASE 03 · CULT KNOWLEDGE</p>
      <h1>Cult 知识库</h1>
      <p class="subtitle">审核状态、认定标准、证据来源与文化标签，全部来自真实 CSV 知识库。</p>
    </header>

    <section class="kb-stats">
      <p v-if="statsLoading" class="card loading-text">正在加载知识库统计 ...</p>
      <p v-else-if="statsError" class="card err">{{ statsError }}</p>

      <template v-else-if="stats">
        <div class="scope-block">
          <div class="scope-head">
            <h2>全库建设统计</h2>
            <span class="scope-tag">含待审核数据</span>
          </div>
          <p class="scope-note">{{ stats.scope_note }}</p>
          <div class="stat-grid">
            <div class="stat-cell">
              <span class="stat-value">{{ stats.movies_total }}</span>
              <span class="stat-label">电影总数</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value approved">{{ stats.review_status_counts.approved }}</span>
              <span class="stat-label">已批准</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value pending">{{ stats.review_status_counts.pending }}</span>
              <span class="stat-label">待审核</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.review_status_counts.draft }}</span>
              <span class="stat-label">草稿</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.review_status_counts.rejected }}</span>
              <span class="stat-label">已驳回</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.review_status_counts.needs_fix }}</span>
              <span class="stat-label">需修正</span>
            </div>
          </div>
          <div class="stat-columns">
            <div>
              <h3>证据人工状态</h3>
              <p>共 {{ stats.evidence.total }} 条</p>
              <ul>
                <li><span>人工确认</span><strong>{{ stats.evidence.confirmed }}</strong></li>
                <li><span>待人工</span><strong>{{ stats.evidence.pending }}</strong></li>
                <li><span>人工驳回</span><strong>{{ stats.evidence.rejected }}</strong></li>
              </ul>
            </div>
            <div>
              <h3>正式标签映射</h3>
              <p>共 {{ stats.formal_tags.total }} 条</p>
              <ul>
                <li><span>人工标注</span><strong>{{ stats.formal_tags.manual }}</strong></li>
                <li><span>规则推断</span><strong>{{ stats.formal_tags.inferred }}</strong></li>
              </ul>
            </div>
            <div>
              <h3>候选标签</h3>
              <p>共 {{ stats.candidate_tags.total }} 条</p>
              <ul>
                <li><span>已确认</span><strong>{{ stats.candidate_tags.confirmed }}</strong></li>
                <li><span>待定</span><strong>{{ stats.candidate_tags.pending }}</strong></li>
                <li><span>已驳回</span><strong>{{ stats.candidate_tags.rejected }}</strong></li>
              </ul>
            </div>
          </div>
        </div>

        <div class="scope-block approved-scope">
          <div class="scope-head">
            <h2>仅已批准电影</h2>
            <span class="scope-tag approved">approved_scope</span>
          </div>
          <div class="stat-grid compact">
            <div class="stat-cell">
              <span class="stat-value">{{ stats.approved_scope.movies }}</span>
              <span class="stat-label">已批准电影</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.approved_scope.evidence_confirmed }}</span>
              <span class="stat-label">人工确认证据</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.approved_scope.formal_tags }}</span>
              <span class="stat-label">正式标签</span>
            </div>
            <div class="stat-cell">
              <span class="stat-value">{{ stats.approved_scope.candidate_tags_confirmed }}</span>
              <span class="stat-label">已确认候选标签</span>
            </div>
          </div>
        </div>
      </template>
    </section>

    <section class="kb-toolbar card">
      <div class="status-tabs" role="group" aria-label="审核状态筛选">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value"
          type="button"
          :class="['status-tab', { active: status === tab.value }]"
          @click="status = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
      <label class="search-box">
        <span>搜索</span>
        <input
          v-model="query"
          type="search"
          placeholder="中文名、英文名或 ID"
          autocomplete="off"
        />
      </label>
    </section>

    <section class="kb-list">
      <p v-if="!loading && !listError" class="result-count">
        当前状态：{{ STATUS_TABS.find((tab) => tab.value === status)?.label }} ·
        共 {{ total }} 部
        <span v-if="query.trim()">（关键词：{{ query.trim() }}）</span>
      </p>

      <p v-if="loading" class="loading-text">正在加载电影 ...</p>
      <p v-else-if="listError" class="err">{{ listError }}</p>
      <p v-else-if="!movies.length" class="empty-text">
        没有符合条件的电影。可切换状态或清空搜索关键词。
      </p>

      <div v-else class="movie-grid">
        <a
          v-for="movie in movies"
          :key="movie.seed_id"
          class="movie-card"
          :href="`#/knowledge/${movie.seed_id}`"
        >
          <div class="movie-card-head">
            <span class="seed-id">{{ movie.seed_id }}</span>
            <span :class="['status-badge', `status-${movie.review_status}`]">
              {{ statusLabel(movie.review_status) }}
            </span>
          </div>
          <h2>{{ movie.title }}</h2>
          <p class="original-title">{{ movie.original_title }}</p>
          <div class="movie-meta">
            <span>{{ movie.year }}</span>
            <span>门槛合格标准 {{ movie.confirmed_criteria_count }}</span>
            <span>正式标签 {{ movie.formal_tag_count }}</span>
          </div>
          <span class="detail-link">查看详情 →</span>
        </a>
      </div>

      <nav
        v-if="!loading && !listError && total > 0"
        class="pager"
        aria-label="列表分页"
      >
        <button type="button" class="pager-btn" :disabled="!canPrev" @click="goToPrevPage">
          上一页
        </button>
        <span class="pager-info">第 {{ rangeStart }}–{{ rangeEnd }} 部 / 共 {{ total }} 部</span>
        <button type="button" class="pager-btn" :disabled="!canNext" @click="goToNextPage">
          下一页
        </button>
      </nav>
    </section>

    <section class="kb-dictionaries card">
      <header class="dict-head">
        <h2>知识库字典</h2>
        <p class="chart-sub">标准与标签定义来自 CSV，不由前端生成。</p>
      </header>
      <p v-if="dictionaryError" class="err">{{ dictionaryError }}</p>

      <details class="dict-panel">
        <summary>认定标准（{{ criteria.length }}）</summary>
        <div class="dict-list">
          <article v-for="item in criteria" :key="item.criterion_code" class="dict-item">
            <h3>{{ item.criterion_code }} · {{ item.name_zh }}</h3>
            <p class="dict-en">{{ item.name_en }}</p>
            <p>{{ item.definition }}</p>
            <p class="dict-rule"><strong>证据要求：</strong>{{ item.evidence_requirement }}</p>
            <p class="dict-rule"><strong>排除条件：</strong>{{ item.exclusion_note }}</p>
          </article>
        </div>
      </details>

      <details class="dict-panel">
        <summary>文化标签（{{ tagDictionary.length }}）</summary>
        <div class="dict-list">
          <article v-for="item in tagDictionary" :key="item.tag_id" class="dict-item">
            <h3>{{ item.label_zh }} <span class="tag-id">{{ item.tag_id }}</span></h3>
            <p class="dict-en">{{ item.label_en }} · {{ item.dimension }}</p>
            <p>{{ item.definition }}</p>
            <p class="dict-rule"><strong>纳入：</strong>{{ item.inclusion_criteria }}</p>
            <p class="dict-rule"><strong>排除：</strong>{{ item.exclusion_criteria }}</p>
          </article>
        </div>
      </details>
    </section>
  </div>
</template>

<style scoped>
.knowledge-view {
  margin-top: 8px;
}

.kb-hero h1 {
  margin: 0;
  font-size: clamp(34px, 6vw, 56px);
  letter-spacing: 0.04em;
}

.kb-hero .subtitle {
  margin: 10px 0 0;
  font-size: 15px;
  color: #a79fae;
}

.kb-stats {
  margin-top: 26px;
}

.scope-block {
  padding: 22px 24px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: rgba(20, 17, 24, 0.85);
}

.scope-block + .scope-block {
  margin-top: 16px;
}

.scope-block.approved-scope {
  border-color: rgba(111, 224, 168, 0.28);
  background: linear-gradient(120deg, rgba(111, 224, 168, 0.08), rgba(20, 17, 24, 0.9));
}

.scope-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.scope-head h2 {
  margin: 0;
  font-size: 16px;
  color: #e8e3ee;
}

.scope-tag {
  padding: 3px 9px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 999px;
  font-size: 11px;
  color: #a79fae;
}

.scope-tag.approved {
  border-color: rgba(111, 224, 168, 0.4);
  color: #6fe0a8;
}

.scope-note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: #8a8291;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.stat-grid.compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat-cell {
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
}

.stat-value {
  display: block;
  font-size: 22px;
  font-variant-numeric: tabular-nums;
  color: #f2edf6;
}

.stat-value.approved {
  color: #6fe0a8;
}

.stat-value.pending {
  color: #ffc46b;
}

.stat-label {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #8a8291;
}

.stat-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}

.stat-columns h3 {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: #cfc8d6;
}

.stat-columns p {
  margin: 0 0 6px;
  font-size: 11px;
  color: #8a8291;
}

.stat-columns ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.stat-columns li {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 12px;
  color: #a79fae;
}

.stat-columns strong {
  color: #e8e3ee;
  font-variant-numeric: tabular-nums;
}

.kb-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.status-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.status-tab {
  padding: 8px 16px;
  border: 1px solid #3a3145;
  border-radius: 999px;
  background: transparent;
  color: #a79fae;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
}

.status-tab:hover {
  border-color: #8b6fe8;
  color: #e8e3ee;
}

.status-tab.active {
  border-color: #d2455a;
  background: rgba(210, 69, 90, 0.16);
  color: #ff9aa8;
}

.search-box {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: #8a8291;
}

.search-box input {
  width: 260px;
  padding: 9px 12px;
  border: 1px solid #3a3145;
  border-radius: 8px;
  background: #17131c;
  color: #e8e3ee;
  font-size: 13px;
  font-family: inherit;
  outline: none;
}

.search-box input:focus {
  border-color: #8b6fe8;
}

.kb-list {
  margin-top: 20px;
}

.result-count {
  margin: 0 0 10px;
  font-size: 12px;
  color: #8a8291;
}

.result-count span {
  color: #6f6878;
}

.movie-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.movie-card {
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: rgba(20, 17, 24, 0.85);
  color: inherit;
  text-decoration: none;
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.movie-card:hover {
  border-color: rgba(210, 69, 90, 0.5);
  transform: translateY(-2px);
}

.movie-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.seed-id {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: #8a8291;
}

.status-badge {
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  font-size: 11px;
  white-space: nowrap;
}

.status-approved {
  border-color: rgba(111, 224, 168, 0.4);
  background: rgba(111, 224, 168, 0.12);
  color: #6fe0a8;
}

.status-pending {
  border-color: rgba(255, 196, 107, 0.4);
  background: rgba(255, 196, 107, 0.12);
  color: #ffc46b;
}

.status-draft,
.status-rejected,
.status-needs_fix {
  border-color: rgba(255, 123, 138, 0.34);
  background: rgba(255, 123, 138, 0.1);
  color: #ff9aa8;
}

.movie-card h2 {
  margin: 12px 0 2px;
  font-size: 19px;
  color: #f2edf6;
}

.original-title {
  margin: 0;
  font-size: 12px;
  color: #8a8291;
}

.movie-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 14px;
  font-size: 11px;
  color: #a79fae;
}

.detail-link {
  margin-top: 16px;
  font-size: 12px;
  color: #ff9aa8;
}

.kb-dictionaries {
  margin-top: 24px;
}

.dict-head h2 {
  margin: 0 0 4px;
}

.dict-panel {
  margin-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  padding-top: 12px;
}

.dict-panel summary {
  cursor: pointer;
  font-size: 13px;
  color: #cfc8d6;
}

.dict-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.dict-item {
  padding: 14px 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
}

.dict-item h3 {
  margin: 0 0 2px;
  font-size: 13px;
  color: #e8e3ee;
}

.dict-en {
  margin: 0 0 8px !important;
  font-size: 11px;
  color: #8a8291;
}

.dict-item p {
  margin: 4px 0;
  font-size: 12px;
  line-height: 1.65;
  color: #a79fae;
}

.dict-rule {
  color: #8a8291 !important;
}

.tag-id {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 400;
  color: #6f6878;
}

@media (max-width: 980px) {
  .stat-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .stat-columns {
    grid-template-columns: minmax(0, 1fr);
  }

  .movie-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dict-list {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 620px) {
  .stat-grid,
  .stat-grid.compact {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .movie-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .search-box,
  .search-box input {
    width: 100%;
  }

  .kb-toolbar {
    align-items: stretch;
  }
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 22px;
}

.pager-btn {
  padding: 7px 15px;
  border: 1px solid #4a4155;
  border-radius: 8px;
  background: transparent;
  color: #cfc8d6;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}

.pager-btn:hover:not(:disabled) {
  border-color: #8b6fe8;
  color: #e8e3ee;
}

.pager-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pager-info {
  font-size: 12px;
  color: #8a8291;
  font-variant-numeric: tabular-nums;
}
</style>
