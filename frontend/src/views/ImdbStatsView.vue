<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  describeCultError,
  fetchCultCriteria,
  fetchCultMovies,
  fetchCultStats,
  fetchCultTagDictionary
} from '../api/cult'

// CULTScope 3.5.8B：以 Cult 知识库为研究主体，不把 IMDb 全库统计冒充 Cult 样本。
const stats = ref(null)
const criteria = ref([])
const culturalTags = ref([])
const featuredMovies = ref([])
const errors = ref({})
const loading = ref(true)
const showAllTags = ref(false)
let requestId = 0
let unmounted = false

const approvedCount = computed(() => stats.value?.approved_scope?.movies ?? null)
const previewTags = computed(() =>
  showAllTags.value ? culturalTags.value : culturalTags.value.slice(0, 12)
)

function countText(value) {
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—'
}

function detailLink(seedId) {
  return `#/knowledge/${encodeURIComponent(seedId)}`
}

async function load() {
  const currentRequest = ++requestId
  loading.value = true
  errors.value = {}
  stats.value = null
  criteria.value = []
  culturalTags.value = []
  featuredMovies.value = []

  const results = await Promise.allSettled([
    fetchCultStats(),
    fetchCultCriteria(),
    fetchCultTagDictionary(),
    fetchCultMovies({ status: 'approved', limit: 6, offset: 0 })
  ])
  if (unmounted || currentRequest !== requestId) return

  const [statsResult, criteriaResult, tagsResult, moviesResult] = results
  if (statsResult.status === 'fulfilled') {
    stats.value = statsResult.value
  } else {
    errors.value.stats = describeCultError(statsResult.reason)
  }

  if (criteriaResult.status === 'fulfilled') {
    criteria.value = criteriaResult.value?.items ?? []
  } else {
    errors.value.criteria = describeCultError(criteriaResult.reason)
  }

  if (tagsResult.status === 'fulfilled') {
    culturalTags.value = tagsResult.value?.items ?? []
  } else {
    errors.value.tags = describeCultError(tagsResult.reason)
  }

  if (moviesResult.status === 'fulfilled') {
    featuredMovies.value = moviesResult.value?.items ?? []
  } else {
    errors.value.movies = describeCultError(moviesResult.reason)
  }
  loading.value = false
}

onMounted(load)
onBeforeUnmount(() => {
  unmounted = true
  requestId += 1
})
</script>

<template>
  <div class="research-view">
    <header class="hero research-hero">
      <p class="kicker">CULTSCOPE · CULT FILM RESEARCH</p>
      <h1>Cult 电影研究</h1>
      <p class="subtitle">什么使一部电影成为 Cult？从认定标准、文化标签与具体作品中寻找答案。</p>
      <div class="research-intro">
        <span>研究导览</span>
        <p>
          CULTScope 不以票房、IMDb 评分或电影类型单独定义 Cult 电影。
          本页以知识库中可核查的认定规则、审核记录和作品信息为研究线索。
        </p>
      </div>
    </header>

    <p v-if="loading" class="card research-state" role="status">正在加载 Cult 研究资料…</p>

    <template v-else>
      <section class="research-section overview-section" aria-labelledby="research-scope">
        <div class="section-heading">
          <div>
            <p class="section-eyebrow">01 / SCOPE</p>
            <h2 id="research-scope">从经过审核的样本开始</h2>
          </div>
          <a class="text-link" href="#/knowledge">查看知识库 →</a>
        </div>

        <div v-if="stats" class="scope-panel">
          <div class="scope-number">
            <strong>{{ countText(approvedCount) }}</strong>
            <span>已批准的研究电影</span>
          </div>
          <p>
            知识库共收录 {{ countText(stats.movies_total) }} 部电影；
            其中已批准电影是本页代表作品的主要来源。
            <span class="scope-note">{{ stats.scope_note }}</span>
          </p>
        </div>
        <div v-else class="research-state card" role="alert">
          <p>研究范围暂时无法加载：{{ errors.stats }}</p>
          <button type="button" class="research-btn" @click="load">重新加载</button>
        </div>
      </section>

      <section class="research-section" aria-labelledby="research-criteria">
        <div class="section-heading">
          <div>
            <p class="section-eyebrow">02 / CRITERIA</p>
            <h2 id="research-criteria">Cult 是如何被认定的？</h2>
          </div>
          <span class="section-count">认定标准 {{ criteria.length }}</span>
        </div>
        <p class="section-desc">
          标准、证据要求和排除条件均来自项目知识库定义。展开条目可以查看判定边界，
          而不是仅凭某部电影“冷门”或“评分极端”做出结论。
        </p>

        <div v-if="errors.criteria" class="research-state card" role="alert">
          {{ errors.criteria }}
          <button type="button" class="research-btn" @click="load">重新加载</button>
        </div>
        <p v-else-if="!criteria.length" class="research-state card">暂无可展示的认定标准。</p>
        <div v-else class="criteria-grid">
          <details v-for="item in criteria" :key="item.criterion_code" class="criterion-card">
            <summary>
              <span class="criterion-code">{{ item.criterion_code }}</span>
              <span class="criterion-title">{{ item.name_zh }}</span>
              <span class="expand-sign" aria-hidden="true">＋</span>
            </summary>
            <p class="criterion-en">{{ item.name_en }}</p>
            <p>{{ item.definition }}</p>
            <p v-if="item.evidence_requirement"><strong>证据要求：</strong>{{ item.evidence_requirement }}</p>
            <p v-if="item.exclusion_note"><strong>排除条件：</strong>{{ item.exclusion_note }}</p>
          </details>
        </div>
      </section>

      <section class="research-section" aria-labelledby="research-tags">
        <div class="section-heading">
          <div>
            <p class="section-eyebrow">03 / CULTURE</p>
            <h2 id="research-tags">文化标签描绘什么？</h2>
          </div>
          <span class="section-count">标签定义 {{ culturalTags.length }}</span>
        </div>
        <p class="section-desc">
          文化标签是一套描述和归档维度，并不意味着每个标签都已在电影样本中被确认。
          具体电影的标签及证据需进入知识库核对。
        </p>

        <div v-if="errors.tags" class="research-state card" role="alert">
          {{ errors.tags }}
          <button type="button" class="research-btn" @click="load">重新加载</button>
        </div>
        <p v-else-if="!culturalTags.length" class="research-state card">暂无文化标签定义。</p>
        <template v-else>
          <div class="tag-grid">
            <details v-for="tag in previewTags" :key="tag.tag_id" class="tag-card">
              <summary>
                <span class="tag-dimension">{{ tag.dimension }}</span>
                <strong>{{ tag.label_zh }}</strong>
                <small>{{ tag.label_en }}</small>
              </summary>
              <p>{{ tag.definition }}</p>
              <p v-if="tag.inclusion_criteria"><strong>纳入：</strong>{{ tag.inclusion_criteria }}</p>
              <p v-if="tag.exclusion_criteria"><strong>排除：</strong>{{ tag.exclusion_criteria }}</p>
            </details>
          </div>
          <button
            v-if="culturalTags.length > 12"
            type="button"
            class="research-btn more-btn"
            :aria-expanded="showAllTags"
            @click="showAllTags = !showAllTags"
          >
            {{ showAllTags ? '收起标签' : `查看全部 ${culturalTags.length} 项标签` }}
          </button>
        </template>
      </section>

      <section class="research-section" aria-labelledby="research-cases">
        <div class="section-heading">
          <div>
            <p class="section-eyebrow">04 / CASE STUDIES</p>
            <h2 id="research-cases">从代表作品走向研究证据</h2>
          </div>
          <a class="text-link" href="#/knowledge">浏览全部作品 →</a>
        </div>
        <p class="section-desc">
          以下展示知识库返回的首批已批准作品，并非按影响力或评分排序的榜单。
          点击电影可查看其认定标准、证据及文化标签。
        </p>

        <div v-if="errors.movies" class="research-state card" role="alert">
          {{ errors.movies }}
          <button type="button" class="research-btn" @click="load">重新加载</button>
        </div>
        <p v-else-if="!featuredMovies.length" class="research-state card">暂无已批准的电影条目。</p>
        <div v-else class="case-grid">
          <a v-for="movie in featuredMovies" :key="movie.seed_id" :href="detailLink(movie.seed_id)" class="case-card">
            <span class="case-id">{{ movie.seed_id }}</span>
            <h3>{{ movie.title }}</h3>
            <p class="case-original">{{ movie.original_title }}</p>
            <div class="case-meta">
              <span>{{ movie.year || '年份待补充' }}</span>
              <span>确认标准 {{ countText(movie.confirmed_criteria_count) }}</span>
              <span>正式标签 {{ countText(movie.formal_tag_count) }}</span>
            </div>
            <span class="case-action">查看研究详情 →</span>
          </a>
        </div>
      </section>

      <footer class="research-footer">
        <strong>关于研究口径</strong>
        <p>
          本页只读取 Cult 知识库的统计、标准、标签字典及已批准电影列表。
          审核状态与文化标签代表知识库当前记录，不等同于学界对 Cult 的唯一界定。
          IMDb 聚合统计能力保留在项目代码中，未将其全量样本混入本页。
        </p>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.research-view { margin-top: 8px; min-width: 0; }
.research-hero { padding-bottom: 8px; }
.research-hero h1 { letter-spacing: .03em; }
.research-intro { margin-top: 24px; padding: 22px 24px; max-width: 760px; border-left: 3px solid #d65b75; border-radius: 0 12px 12px 0; background: rgba(214, 91, 117, .07); }
.research-intro span, .section-eyebrow { color: #ea8da1; font-size: 11px; font-weight: 700; letter-spacing: .16em; }
.research-intro p { margin: 8px 0 0; color: #c9c0cf; line-height: 1.8; font-size: 14px; }
.research-section { margin-top: 44px; min-width: 0; }
.section-heading { display: flex; align-items: end; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
.section-heading h2 { margin: 8px 0 0; color: #f2edf6; font-size: clamp(22px, 3vw, 30px); }
.section-eyebrow { margin: 0; }
.section-count, .section-desc { color: #a79fae; font-size: 13px; }
.section-desc { max-width: 800px; margin: 0 0 20px; line-height: 1.8; }
.text-link { color: #ff9aae; text-decoration: none; font-size: 13px; }
.text-link:hover, .text-link:focus-visible { text-decoration: underline; }
.scope-panel { display: grid; grid-template-columns: minmax(170px, 230px) minmax(0, 1fr); align-items: center; gap: 22px; padding: 26px; border-radius: 14px; border: 1px solid rgba(111,224,168,.24); background: linear-gradient(110deg, rgba(111,224,168,.07), rgba(20,17,24,.94)); }
.scope-number { display: flex; flex-direction: column; gap: 4px; }
.scope-number strong { color: #6fe0a8; font-size: clamp(38px, 5vw, 56px); font-variant-numeric: tabular-nums; }
.scope-number span { color: #dfd9e4; font-size: 13px; }
.scope-panel p { color: #c6bdcc; font-size: 14px; line-height: 1.9; }
.scope-note { display: block; margin-top: 8px; color: #948b9c; font-size: 12px; }
.criteria-grid, .tag-grid, .case-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.criterion-card, .tag-card, .case-card { min-width: 0; padding: 20px; border: 1px solid rgba(255,255,255,.09); border-radius: 13px; background: rgba(20,17,24,.85); overflow-wrap: anywhere; }
.criterion-card summary, .tag-card summary { cursor: pointer; list-style: none; }
.criterion-card summary::-webkit-details-marker, .tag-card summary::-webkit-details-marker { display: none; }
.criterion-card summary { display: flex; align-items: center; gap: 10px; }
.criterion-code { color: #ec94a6; font-size: 11px; font-weight: 700; white-space: nowrap; }
.criterion-title { flex: 1; color: #f2edf6; font-size: 16px; font-weight: 600; }
.expand-sign { color: #f0a0ae; font-size: 22px; }
.criterion-card[open] .expand-sign { transform: rotate(45deg); }
.criterion-card p, .tag-card p { margin: 12px 0 0; color: #c4bbc9; font-size: 13px; line-height: 1.7; }
.criterion-card .criterion-en { color: #9a91a1; font-size: 12px; }
.tag-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.tag-card summary { display: flex; flex-direction: column; gap: 5px; }
.tag-card strong { color: #f2edf6; font-size: 16px; }
.tag-card small { color: #948b9c; font-size: 12px; }
.tag-dimension { align-self: flex-start; color: #c9a6f4; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.case-card { display: flex; flex-direction: column; color: inherit; text-decoration: none; transition: border-color .15s, transform .15s; }
.case-card:hover, .case-card:focus-visible { border-color: rgba(214,91,117,.48); transform: translateY(-2px); }
.case-id { color: #8c8392; font-size: 11px; }
.case-card h3 { margin: 10px 0 4px; color: #f2edf6; font-size: 18px; }
.case-original { margin: 0 0 16px; color: #948b9c; font-size: 12px; }
.case-meta { display: flex; flex-wrap: wrap; gap: 7px 12px; color: #b7acbd; font-size: 12px; }
.case-action { margin-top: auto; padding-top: 20px; color: #ff9aae; font-size: 13px; }
.research-state { padding: 20px; color: #cfc6d5; }
.research-btn { cursor: pointer; margin-top: 12px; padding: 10px 15px; border: 1px solid rgba(214,91,117,.45); border-radius: 8px; background: rgba(214,91,117,.12); color: #ffb1bf; font: inherit; font-size: 13px; }
.research-btn:hover { background: rgba(214,91,117,.23); }
.research-footer { margin: 48px 0 24px; padding: 20px 24px; border-top: 1px solid rgba(255,255,255,.1); background: rgba(255,255,255,.015); }
.research-footer strong { color: #cfc6d5; font-size: 13px; }
.research-footer p { color: #908698; font-size: 12px; line-height: 1.8; }
@media (max-width: 760px) {
  .scope-panel, .tag-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .research-section { margin-top: 32px; }
  .scope-panel, .criteria-grid, .tag-grid, .case-grid { grid-template-columns: minmax(0, 1fr); }
  .scope-panel { padding: 20px; }
  .research-intro { padding: 16px; }
  .criterion-card, .tag-card, .case-card { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  .case-card { transition: none; }
}
</style>
