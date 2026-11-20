<script setup>
import { computed, defineAsyncComponent, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import http from './api/http'
import { describeApiError } from './dashboard/errors'
import { buildMovieParams } from './dashboard/query'
import { createRequestSequence } from './dashboard/requestSequence'
import DecadeBarChart from './components/DecadeBarChart.vue'
import GenreBarChart from './components/GenreBarChart.vue'
import RatingScatterChart from './components/RatingScatterChart.vue'
import { parseRoute } from './router'

const ImdbStatsView = defineAsyncComponent(
  () => import('./views/ImdbStatsView.vue')
)

const KnowledgeDetailView = defineAsyncComponent(
  () => import('./views/KnowledgeDetailView.vue')
)

const KnowledgeView = defineAsyncComponent(
  () => import('./views/KnowledgeView.vue')
)

const route = ref(parseRoute(window.location.hash))

function handleHashChange() {
  route.value = parseRoute(window.location.hash)
  window.scrollTo({ top: 0 })
  if (route.value.name === 'dashboard') loadDashboard()
}

const stats = ref(null)
const movies = ref([])
const filters = reactive({ decade: '', genre: '' })

const loadingStats = ref(false)
const loadingMovies = ref(false)
const statsError = ref('')
const listError = ref('')

// 请求序号：只有最新一次请求可以更新对应状态，避免旧响应覆盖新结果
const statsRequests = createRequestSequence()
const listRequests = createRequestSequence()

const hasFilter = computed(() => Boolean(filters.decade || filters.genre))
const totalSample = computed(() => stats.value?.sample_size ?? movies.value.length)

async function loadStats() {
  if (loadingStats.value) return
  const requestId = statsRequests.begin()
  loadingStats.value = true
  statsError.value = ''
  try {
    const { data } = await http.get('/movies/stats')
    if (!statsRequests.isLatest(requestId)) return
    stats.value = data
  } catch (err) {
    if (!statsRequests.isLatest(requestId)) return
    statsError.value = describeApiError(err)
  } finally {
    if (statsRequests.isLatest(requestId)) loadingStats.value = false
  }
}

async function loadMovies() {
  const requestId = listRequests.begin()
  loadingMovies.value = true
  listError.value = ''
  try {
    const { data } = await http.get('/movies', { params: buildMovieParams(filters) })
    if (!listRequests.isLatest(requestId)) return
    movies.value = data.movies
  } catch (err) {
    if (!listRequests.isLatest(requestId)) return
    listError.value = describeApiError(err)
  } finally {
    if (listRequests.isLatest(requestId)) loadingMovies.value = false
  }
}

function resetFilters() {
  filters.decade = ''
  filters.genre = ''
}

// 数据看板按需加载：直接进入知识库时不再提前请求仪表盘接口
async function loadDashboard() {
  if (!stats.value && !loadingStats.value) await loadStats()
  if (!loadingMovies.value) await loadMovies()
}

function formatMoney(value, known) {
  if (!known || value === null || value === undefined) return '未公开'
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${Math.round(value / 1000)}K`
}

watch(() => [filters.decade, filters.genre], loadMovies)

onMounted(async () => {
  window.addEventListener('hashchange', handleHashChange)
  if (route.value.name === 'dashboard') await loadDashboard()
})

onUnmounted(() => window.removeEventListener('hashchange', handleHashChange))
</script>

<template>
  <main class="page">
    <nav class="site-nav">
      <a class="site-brand" href="#/">CULT<span>Scope</span></a>
      <div class="nav-links">
        <a href="#/" :class="{ active: route.name === 'dashboard' }">数据看板</a>
        <a href="#/imdb" :class="{ active: route.name === 'imdb' }">IMDb 统计</a>
        <a
          href="#/knowledge"
          :class="{ active: ['knowledge', 'knowledge-detail', 'invalid-route'].includes(route.name) }"
        >Cult 知识库</a>
      </div>
    </nav>

    <template v-if="route.name === 'dashboard'">
      <header class="hero">
      <p class="kicker">DATA SCIENCE · PHASE 02</p>
      <h1>CULTScope</h1>
      <p class="subtitle">邪典电影文化观察站 · 数据清洗与探索性可视化</p>
    </header>

    <p v-if="loadingStats" class="card loading-text">正在加载样本统计 ...</p>
    <div v-else-if="statsError" class="card err">
      统计接口加载失败：{{ statsError }}
      <button type="button" class="reset-btn" :disabled="loadingStats" @click="loadStats">
        重新加载
      </button>
      <span v-if="stats">（以下图表为上次成功加载的数据，可能不是最新结果）</span>
    </div>

    <section v-if="stats" class="sample-banner">
      <span class="sample-badge">SAMPLE N={{ stats.sample_size }}</span>
      <div>
        <h2>{{ stats.sample_label }}</h2>
        <p>{{ stats.note }}</p>
      </div>
    </section>

    <section v-if="stats" class="charts-grid">
      <article class="chart-card">
        <header class="chart-head">
          <h2>电影年代分布</h2>
          <p class="chart-sub">由 release_date 提取上映年份后按十年归组</p>
        </header>
        <DecadeBarChart :data="stats.decade_distribution" />
      </article>

      <article class="chart-card">
        <header class="chart-head">
          <h2>电影类型分布</h2>
          <p class="chart-sub">一部电影可属于多个类型，按出现次数统计</p>
        </header>
        <GenreBarChart :data="stats.genre_distribution" />
      </article>

      <article class="chart-card wide">
        <header class="chart-head">
          <h2>评分与投票数量</h2>
          <p class="chart-sub">横轴为投票数（对数刻度），纵轴为 TMDb 平均评分</p>
        </header>
        <RatingScatterChart :data="stats.rating_scatter" />
      </article>
    </section>

    <section class="card list-card">
      <div class="list-head">
        <div>
          <h2>样本电影列表</h2>
          <p class="chart-sub">按年代、类型筛选，列表数据来自 FastAPI 接口</p>
        </div>
        <div class="controls">
          <label class="control">
            <span>年代</span>
            <select v-model="filters.decade">
              <option value="">全部年代</option>
              <option v-for="decade in stats?.filters.decades ?? []" :key="decade" :value="decade">
                {{ decade }}
              </option>
            </select>
          </label>
          <label class="control">
            <span>类型</span>
            <select v-model="filters.genre">
              <option value="">全部类型</option>
              <option v-for="genre in stats?.filters.genres ?? []" :key="genre" :value="genre">
                {{ genre }}
              </option>
            </select>
          </label>
          <button v-if="hasFilter" type="button" class="reset-btn" @click="resetFilters">
            重置
          </button>
        </div>
      </div>

      <p v-if="!loadingMovies && !listError" class="result-count">
        当前显示 {{ movies.length }} / {{ totalSample }} 部
        <span v-if="hasFilter">（已按筛选条件过滤）</span>
      </p>

      <p v-if="loadingMovies" class="loading-text">正在加载电影列表 ...</p>
      <div v-else-if="listError" class="err">
        列表接口加载失败：{{ listError }}
        <button type="button" class="reset-btn" :disabled="loadingMovies" @click="loadMovies">
          重新加载
        </button>
      </div>
      <p v-else-if="!movies.length" class="empty-text">没有符合当前筛选条件的电影。</p>

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>年份</th>
              <th>片名</th>
              <th>类型</th>
              <th>导演</th>
              <th class="num">片长</th>
              <th class="num">评分</th>
              <th class="num">投票数</th>
              <th class="num">预算</th>
              <th class="num">票房</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="movie in movies" :key="movie.tmdb_id">
              <td class="year">{{ movie.release_year }}</td>
              <td class="title-cell">
                <strong>{{ movie.title }}</strong>
                <span v-if="movie.title !== movie.seed_title" class="sub-title">
                  {{ movie.seed_title }}
                </span>
              </td>
              <td>
                <span v-for="genre in movie.genres" :key="genre" class="chip">{{ genre }}</span>
              </td>
              <td class="muted">{{ movie.directors.join(' / ') || '—' }}</td>
              <td class="num">{{ movie.runtime ? `${movie.runtime} 分` : '—' }}</td>
              <td class="num">
                <span :class="['score', { high: movie.vote_average >= 7.5 }]">
                  {{ movie.vote_average?.toFixed(2) ?? '—' }}
                </span>
              </td>
              <td class="num">{{ movie.vote_count?.toLocaleString() ?? '—' }}</td>
              <td
                class="num"
                :class="{ 'money-unknown': !movie.budget_known }"
                :title="movie.budget_known ? '' : 'TMDb budget 为 0 或缺失，按未知值处理'"
              >
                {{ formatMoney(movie.budget, movie.budget_known) }}
              </td>
              <td
                class="num"
                :class="{ 'money-unknown': !movie.revenue_known }"
                :title="movie.revenue_known ? '' : 'TMDb revenue 为 0 或缺失，按未知值处理'"
              >
                {{ formatMoney(movie.revenue, movie.revenue_known) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer v-if="stats" class="footer-note">
      <p>{{ stats.sample_label }} · 样本统计仅描述这批影片，不代表整体趋势。</p>
      <p>所有图表与列表均通过 FastAPI 接口读取真实 TMDb 数据，无硬编码或模拟数据。</p>
    </footer>
    </template>

    <ImdbStatsView v-else-if="route.name === 'imdb'" />
    <KnowledgeView v-else-if="route.name === 'knowledge'" />
    <KnowledgeDetailView v-else-if="route.name === 'knowledge-detail'" :seed-id="route.seedId" />
    <section v-else class="card state-card">
      <h2>链接无效</h2>
      <p class="muted">该知识库地址的编码不合法，请返回列表重新选择电影。</p>
      <a class="back-link" href="#/knowledge">返回知识库列表</a>
    </section>
  </main>
</template>
