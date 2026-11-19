<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { describeImdbError, fetchImdbAggregates } from '../api/imdb'
import EChart from '../components/EChart.vue'
import {
  makeDecadeOption,
  makeGenreOption,
  makeRatingOption,
  makeTrendOption,
  makeVotesOption
} from '../imdb/chartOptions'
import { buildImdbViewModel, formatPercent, formatSnapshotTime } from '../imdb/model'

const model = ref(null)
const loading = ref(true)
const error = ref('')
let requestId = 0
let unmounted = false

const decadeOption = computed(() => makeDecadeOption(model.value?.decadeDistribution ?? []))
const genreOption = computed(() => makeGenreOption(model.value?.genreDistribution ?? []))
const ratingOption = computed(() => makeRatingOption(model.value?.ratingDistribution ?? []))
const votesOption = computed(() => makeVotesOption(model.value?.votesDistribution ?? []))
const trendOption = computed(() => makeTrendOption(model.value?.yearTrend ?? []))
const genreChartHeight = computed(
  () => `${Math.max(360, (model.value?.genreDistribution.length ?? 0) * 22 + 60)}px`
)

function formatNumber(value) {
  return Number(value ?? 0).toLocaleString('zh-CN')
}

async function load() {
  const currentRequest = ++requestId
  loading.value = true
  error.value = ''
  model.value = null

  try {
    const payload = await fetchImdbAggregates()
    if (unmounted || currentRequest !== requestId) return
    model.value = buildImdbViewModel(payload)
  } catch (requestError) {
    if (unmounted || currentRequest !== requestId) return
    model.value = null
    error.value = describeImdbError(requestError)
  } finally {
    if (!unmounted && currentRequest === requestId) loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  unmounted = true
  requestId += 1
})
</script>

<template>
  <div class="imdb-view">
    <header class="hero">
      <p class="kicker">PHASE 03 · IMDB ANALYTICS</p>
      <h1>IMDb 统计</h1>
      <p class="subtitle">基于当前 IMDb 标准化数据快照的真实聚合结果。</p>
    </header>

    <p v-if="loading" class="card loading-text" role="status">正在加载 IMDb 聚合统计 ...</p>

    <section v-else-if="error" class="card imdb-error" role="alert">
      <h2>暂时无法显示 IMDb 统计</h2>
      <p>{{ error }}</p>
      <button type="button" class="retry-btn" @click="load">重新加载</button>
    </section>

    <section v-else-if="model?.isEmpty" class="card empty-state" role="status">
      <h2>暂无 IMDb 统计数据</h2>
      <p class="empty-text">当前聚合结果为空，没有可展示的电影、评分或投票统计。</p>
      <button type="button" class="retry-btn" @click="load">重新加载</button>
    </section>

    <template v-else-if="model">
      <section class="sample-banner imdb-snapshot">
        <span class="sample-badge">IMDb SNAPSHOT</span>
        <div>
          <h2>数据快照与统计来源</h2>
          <p class="snapshot-meta">快照生成时间：{{ formatSnapshotTime(model.generatedAt) }}</p>
          <ul class="source-list" aria-label="统计输入来源">
            <li v-for="source in model.sources" :key="source">{{ source }}</li>
          </ul>
          <p class="scope-note">{{ model.scopeNote }}</p>
        </div>
      </section>

      <section class="imdb-stat-grid" aria-label="IMDb 统计概览">
        <article class="imdb-stat-card">
          <span class="stat-label">电影总量</span>
          <strong>{{ formatNumber(model.coverage.total) }}</strong>
          <span class="stat-help">标准化主表中的唯一电影</span>
        </article>
        <article class="imdb-stat-card">
          <span class="stat-label">已评分电影</span>
          <strong class="rated">{{ formatNumber(model.coverage.rated) }}</strong>
          <span class="stat-help">已关联 IMDb 评分记录</span>
        </article>
        <article class="imdb-stat-card">
          <span class="stat-label">评分覆盖率</span>
          <strong>{{ formatPercent(model.coverage.ratio) }}</strong>
          <span class="stat-help">已评分电影 / 电影总量</span>
        </article>
        <article class="imdb-stat-card">
          <span class="stat-label">未评分电影</span>
          <strong>{{ formatNumber(model.coverage.unrated) }}</strong>
          <span class="stat-help">缺失评分不按 0 分处理</span>
        </article>
      </section>

      <p class="year-note">
        年份统计补充：缺失年份 {{ formatNumber(model.missingYear) }} 部，异常年份
        {{ formatNumber(model.invalidYear) }} 部，未来年份 {{ formatNumber(model.futureYear) }} 部。
      </p>

      <p class="year-note">{{ model.qualityNote }}</p>

      <section class="charts-grid">
        <article class="chart-card wide">
          <header class="chart-head">
            <h2>年代分布</h2>
            <p class="chart-sub">
              按聚合数据中的上映年份每十年归组，对比电影总量与已评分电影数；缺失、异常和未来年份不计入本图，见上方年份补充说明。
            </p>
          </header>
          <EChart
            :option="decadeOption"
            :empty="!model.decadeDistribution.length"
            height="340px"
            label="IMDb 电影年代分布柱状图"
          />
        </article>

        <article class="chart-card wide">
          <header class="chart-head">
            <h2>类型分布</h2>
            <p class="chart-sub">{{ model.multiGenreNote }}</p>
          </header>
          <EChart
            :option="genreOption"
            :empty="!model.genreDistribution.length"
            :height="genreChartHeight"
            label="IMDb 类型分布横向柱状图"
          />
        </article>

        <article class="chart-card">
          <header class="chart-head">
            <h2>评分分布</h2>
            <p class="chart-sub">仅统计有效 IMDb 评分，按 0.5 分区间分桶；缺失评分不以 0 代替。</p>
          </header>
          <EChart
            :option="ratingOption"
            :empty="!model.ratingDistribution.length"
            height="360px"
            label="IMDb 有效评分区间分布柱状图"
          />
        </article>

        <article class="chart-card">
          <header class="chart-head">
            <h2>投票分布</h2>
            <p class="chart-sub">
              投票桶及顺序沿用后端聚合定义，不改变原始统计口径；无效或缺失票数不计入本图。
            </p>
          </header>
          <EChart
            :option="votesOption"
            :empty="!model.votesDistribution.length"
            height="360px"
            label="IMDb 投票数区间分布柱状图"
          />
        </article>

        <article class="chart-card wide">
          <header class="chart-head">
            <h2>年份评分趋势</h2>
            <p class="chart-sub">{{ model.trendNote }}</p>
            <p class="chart-sub">默认展示全部年份；可在图内滚轮缩放、拖动平移，或使用下方滑块选择局部范围。</p>
          </header>
          <EChart
            :option="trendOption"
            :empty="!model.yearTrend.length"
            height="400px"
            label="各年份 IMDb 平均评分与有效评分样本数趋势图"
          />
        </article>
      </section>

      <footer class="footer-note">
        <p>本页仅通过 GET /api/imdb/aggregates 读取现有聚合结果，不读取大型 CSV，也不触发重新聚合。</p>
        <p>IMDb 评分反映平台用户投票情况，不是评价电影质量的唯一标准。</p>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.imdb-snapshot > div {
  min-width: 0;
}

.snapshot-meta {
  margin-bottom: 4px !important;
}

.source-list {
  margin: 4px 0 10px;
  padding-left: 18px;
  color: #8a8291;
  font-size: 12px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.scope-note {
  margin-top: 10px !important;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}

.imdb-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-top: 24px;
}

.imdb-stat-card {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  padding: 20px 22px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: rgba(20, 17, 24, 0.85);
}

.imdb-stat-card strong {
  color: #f2edf6;
  font-size: clamp(25px, 3vw, 34px);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.imdb-stat-card strong.rated {
  color: #6fe0a8;
}

.stat-label {
  color: #cfc8d6;
  font-size: 13px;
}

.stat-help {
  color: #6f6878;
  font-size: 11px;
  line-height: 1.5;
}

.year-note {
  margin: 16px 2px 0;
  color: #8a8291;
  font-size: 12px;
  line-height: 1.7;
}

.imdb-error h2,
.empty-state h2 {
  margin: 0 0 8px;
  color: #f2edf6;
  font-size: 18px;
}

.retry-btn {
  margin-top: 12px;
  padding: 8px 16px;
  border: 1px solid rgba(210, 69, 90, 0.5);
  border-radius: 8px;
  background: rgba(210, 69, 90, 0.12);
  color: #ff9aa8;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.retry-btn:hover {
  background: rgba(210, 69, 90, 0.22);
}

@media (max-width: 900px) {
  .imdb-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .imdb-stat-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .imdb-snapshot {
    flex-direction: column;
  }
}
</style>
