<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

import {
  describeCultError,
  fetchCultEvidence,
  fetchCultMovie,
  fetchCultTags
} from '../api/cult'

const props = defineProps({
  seedId: {
    type: String,
    required: true
  }
})

const STATUS_LABELS = {
  approved: '已批准',
  pending: '待审核',
  draft: '草稿',
  rejected: '已驳回',
  needs_fix: '需修正'
}

const VERIFICATION_LABELS = {
  verified: '来源正文已核对',
  unverified: '来源正文未核对',
  disputed: '来源内容有争议'
}

const HUMAN_LABELS = {
  confirmed: '人工确认',
  pending: '待人工确认',
  rejected: '人工驳回'
}

const detail = ref(null)
const evidence = ref([])
const evidenceTotal = ref(0)
const formalTags = ref([])
const candidates = ref([])
const candidatesTotal = ref(0)

const loading = ref(true)
const error = ref('')
const notFound = ref(false)

const includePending = ref(false)
const loadingEvidence = ref(false)
const evidenceError = ref('')

const candidatesLoaded = ref(false)
const loadingCandidates = ref(false)
const candidateError = ref('')

// 请求序号：快速切换电影或反复展开/收起时，只保留最新一次请求的结果
let detailRequestId = 0
let evidenceRequestId = 0
let candidateRequestId = 0
let unmounted = false

const statusLabel = computed(() => STATUS_LABELS[detail.value?.review_status] ?? '')
const isApproved = computed(() => detail.value?.review_status === 'approved')

function verificationLabel(value) {
  return VERIFICATION_LABELS[value] ?? value
}

function humanLabel(value) {
  return HUMAN_LABELS[value] ?? value
}

function criterionNotice(item) {
  if (item.tier_eligible_confirmed) {
    return { tone: 'ok', text: '有人工确认的 T1/T2 证据，计入批准门槛' }
  }
  if (item.human_confirmed) {
    return {
      tone: 'warn',
      text: '已有 T3 人工确认证据，但来源层级不足，不计入批准门槛'
    }
  }
  return { tone: 'muted', text: '尚无人工确认证据' }
}

function evidenceNotice(item) {
  if (item.approved_threshold_eligible) {
    return { tone: 'ok', text: '批准门槛合格证据' }
  }
  if (item.source_tier === 'T3') {
    return { tone: 'muted', text: 'T3 补充来源，不计入批准门槛' }
  }
  return { tone: 'muted', text: '尚未人工确认，不计入批准门槛' }
}

async function loadAll() {
  const requestId = ++detailRequestId
  // 切换电影时作废仍在途的证据/候选请求
  evidenceRequestId += 1
  candidateRequestId += 1

  loading.value = true
  error.value = ''
  notFound.value = false
  detail.value = null
  evidence.value = []
  evidenceTotal.value = 0
  formalTags.value = []
  candidates.value = []
  candidatesLoaded.value = false
  includePending.value = false
  loadingEvidence.value = false
  evidenceError.value = ''
  loadingCandidates.value = false
  candidateError.value = ''

  try {
    const [detailData, evidenceData, tagsData] = await Promise.all([
      fetchCultMovie(props.seedId),
      fetchCultEvidence(props.seedId, false),
      fetchCultTags(props.seedId, false)
    ])
    if (unmounted || requestId !== detailRequestId) return
    detail.value = detailData
    evidence.value = evidenceData.items
    evidenceTotal.value = evidenceData.total
    formalTags.value = tagsData.formal
    candidatesTotal.value = tagsData.candidates_total
  } catch (err) {
    if (unmounted || requestId !== detailRequestId) return
    if (err?.response?.status === 404) {
      notFound.value = true
    } else {
      error.value = describeCultError(err)
    }
  } finally {
    if (!unmounted && requestId === detailRequestId) loading.value = false
  }
}

async function togglePendingEvidence() {
  const requestId = ++evidenceRequestId
  const next = !includePending.value
  loadingEvidence.value = true
  evidenceError.value = ''
  try {
    const data = await fetchCultEvidence(props.seedId, next)
    if (unmounted || requestId !== evidenceRequestId) return
    evidence.value = data.items
    evidenceTotal.value = data.total
    includePending.value = next
  } catch (err) {
    if (unmounted || requestId !== evidenceRequestId) return
    evidenceError.value = describeCultError(err)
  } finally {
    if (!unmounted && requestId === evidenceRequestId) loadingEvidence.value = false
  }
}

async function toggleCandidates() {
  if (candidatesLoaded.value) {
    candidatesLoaded.value = false
    candidates.value = []
    return
  }
  const requestId = ++candidateRequestId
  loadingCandidates.value = true
  candidateError.value = ''
  try {
    const data = await fetchCultTags(props.seedId, true)
    if (unmounted || requestId !== candidateRequestId) return
    formalTags.value = data.formal
    candidates.value = data.candidates
    candidatesTotal.value = data.candidates_total
    candidatesLoaded.value = true
  } catch (err) {
    if (unmounted || requestId !== candidateRequestId) return
    candidateError.value = describeCultError(err)
  } finally {
    if (!unmounted && requestId === candidateRequestId) loadingCandidates.value = false
  }
}

watch(
  () => props.seedId,
  () => loadAll(),
  { immediate: true }
)

onUnmounted(() => {
  unmounted = true
})
</script>

<template>
  <div class="detail-view">
    <a class="back-link" href="#/knowledge">← 返回知识库列表</a>

    <p v-if="loading" class="card loading-text">正在加载电影审核详情 ...</p>

    <section v-else-if="notFound" class="card state-card">
      <h1>未找到该电影</h1>
      <p class="muted">请检查电影 ID 是否正确，或返回列表重新选择。</p>
      <a class="back-link inline" href="#/knowledge">返回知识库列表</a>
    </section>

    <section v-else-if="error" class="card state-card">
      <h1>详情暂时无法加载</h1>
      <p class="err">{{ error }}</p>
      <a class="back-link inline" href="#/knowledge">返回知识库列表</a>
    </section>

    <template v-else-if="detail">
      <header class="detail-hero">
        <p class="kicker">{{ detail.seed_id }} · CULT REVIEW</p>
        <div class="title-row">
          <div>
            <h1>{{ detail.title }}</h1>
            <p class="original-title">{{ detail.original_title }} · {{ detail.year }}</p>
          </div>
          <span :class="['status-badge', `status-${detail.review_status}`]">
            {{ statusLabel }}
          </span>
        </div>
        <p class="hero-meta">
          TMDb {{ detail.tmdb_id ?? '—' }} · IMDb {{ detail.imdb_id ?? '—' }}
          <span v-if="detail.reviewer">· 审核人 {{ detail.reviewer }}</span>
          <span v-else>· 审核人尚未记录</span>
          <span v-if="detail.reviewed_at">· 审核时间 {{ detail.reviewed_at }}</span>
        </p>

        <p v-if="!isApproved" class="status-notice">
          该电影当前为「{{ statusLabel }}」，尚未获得正式批准。下方“门槛合格标准数”只表示
          已有人工确认的 T1/T2 证据支撑，不代表最终审核结论。
        </p>
        <p v-else class="status-notice approved">
          该电影已通过人工审核，状态为 approved；批准门槛为至少两条人工确认的 T1/T2 标准。
        </p>

        <div class="summary-grid">
          <div class="summary-cell">
            <span class="summary-value">{{ detail.declared_criteria_codes.length }}</span>
            <span class="summary-label">声明候选标准</span>
          </div>
          <div class="summary-cell">
            <span class="summary-value">{{ detail.confirmed_criteria_count }}</span>
            <span class="summary-label">门槛合格标准</span>
          </div>
          <div class="summary-cell">
            <span class="summary-value">{{ detail.formal_tag_count }}</span>
            <span class="summary-label">正式标签</span>
          </div>
          <div class="summary-cell">
            <span class="summary-value">{{ detail.candidate_tag_count }}</span>
            <span class="summary-label">候选标签</span>
          </div>
        </div>
      </header>

      <section class="card">
        <header class="section-head">
          <div>
            <h2>Cult 认定标准与证据数量</h2>
            <p class="chart-sub">
              “人工确认”与“来源正文已核对”是两件事；只有已声明、人工确认且来源为
              T1/T2 的证据才计入批准门槛。
            </p>
          </div>
        </header>

        <p v-if="!detail.criteria.length" class="empty-text">暂无已声明的认定标准。</p>

        <div v-else class="criteria-list">
          <article
            v-for="item in detail.criteria"
            :key="item.criterion_code"
            class="criterion-card"
          >
            <div class="criterion-head">
              <h3>{{ item.criterion_code }} · {{ item.name_zh }}</h3>
              <span :class="['tone-badge', `tone-${criterionNotice(item).tone}`]">
                {{ criterionNotice(item).text }}
              </span>
            </div>
            <p class="criterion-en">{{ item.name_en }}</p>
            <p>{{ item.definition }}</p>
            <p class="rule-line"><strong>证据要求：</strong>{{ item.evidence_requirement }}</p>
            <p class="rule-line"><strong>排除条件：</strong>{{ item.exclusion_note }}</p>
            <div class="criterion-counts">
              <span>人工确认证据 {{ item.confirmed_evidence_count }}</span>
              <span>其中 T1/T2 {{ item.tier_eligible_evidence_count }}</span>
              <span>待人工 {{ item.pending_evidence_count }}</span>
              <span>已驳回 {{ item.rejected_evidence_count }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="card">
        <header class="section-head evidence-head">
          <div>
            <h2>证据与来源</h2>
            <p class="chart-sub">
              默认只显示已人工确认的证据。verified 表示来源正文已核对，不等于人工确认。
            </p>
          </div>
          <button type="button" class="ghost-btn" :disabled="loadingEvidence" @click="togglePendingEvidence">
            {{ includePending ? '仅看人工确认' : '显示待审核/已驳回证据' }}
          </button>
        </header>

        <p v-if="loadingEvidence" class="loading-text">正在加载证据 ...</p>
        <p v-if="evidenceError" class="err">{{ evidenceError }}</p>
        <p v-else-if="!evidence.length" class="empty-text">
          当前筛选下没有证据记录。
        </p>

        <div v-else class="evidence-list">
          <article v-for="item in evidence" :key="`${item.criterion_code}-${item.source_id}`" class="evidence-item">
            <div class="evidence-head">
              <div>
                <h3>{{ item.criterion_code }} · {{ item.criterion_name_zh }}</h3>
                <p class="source-title">
                  <span class="tier-badge" :class="`tier-${item.source_tier.toLowerCase()}`">
                    {{ item.source_tier }}
                  </span>
                  {{ item.source_title }}
                  <span class="muted">· {{ item.publisher }}</span>
                </p>
              </div>
              <span :class="['tone-badge', `tone-${evidenceNotice(item).tone}`]">
                {{ evidenceNotice(item).text }}
              </span>
            </div>

            <p class="evidence-summary">{{ item.evidence_summary }}</p>
            <p class="locator"><strong>原文定位：</strong>{{ item.locator }}</p>
            <p class="source-link-line">
              <a :href="item.source_url" target="_blank" rel="noopener noreferrer">
                查看原始来源 ↗
              </a>
            </p>

            <div class="evidence-status">
              <span class="status-chip verification">
                来源核对：{{ verificationLabel(item.verification_status) }}
              </span>
              <span :class="['status-chip', `human-${item.human_status}`]">
                人工结论：{{ humanLabel(item.human_status) }}
              </span>
              <span v-if="item.confirmed_by" class="status-chip neutral">
                确认人：{{ item.confirmed_by }}
              </span>
              <span v-if="item.confirmed_at" class="status-chip neutral">
                确认时间：{{ item.confirmed_at }}
              </span>
            </div>
          </article>
        </div>
      </section>

      <section class="card">
        <header class="section-head">
          <div>
            <h2>正式文化标签</h2>
            <p class="chart-sub">来自 movie_cult_tags.csv 的正式分析集合，不包含候选标签。</p>
          </div>
        </header>

        <p v-if="!formalTags.length" class="empty-text">暂无正式文化标签。</p>
        <div v-else class="tag-grid">
          <article v-for="tag in formalTags" :key="tag.tag_id" class="tag-card">
            <div class="tag-head">
              <h3>{{ tag.label_zh }}</h3>
              <span class="tag-dimension">{{ tag.dimension }}</span>
            </div>
            <p class="tag-en">{{ tag.label_en }} · {{ tag.tag_id }}</p>
            <p>{{ tag.definition }}</p>
            <p class="rule-line"><strong>证据：</strong>{{ tag.evidence }}</p>
            <p class="rule-line">
              <strong>来源：</strong>{{ tag.source_ids.join(' / ') || '—' }}
              <span v-if="tag.annotator"> · 标注人 {{ tag.annotator }}</span>
            </p>
          </article>
        </div>

        <div class="candidate-block">
          <div class="candidate-head">
            <div>
              <h2>研究中：候选标签</h2>
              <p class="chart-sub">
                候选标签独立于正式集合，默认不加载；pending/rejected 不会进入正式分析。
              </p>
            </div>
            <button type="button" class="ghost-btn" :disabled="loadingCandidates" @click="toggleCandidates">
              {{ candidatesLoaded ? '隐藏候选标签' : `查看候选标签（${candidatesTotal}）` }}
            </button>
          </div>

          <p v-if="loadingCandidates" class="loading-text">正在加载候选标签 ...</p>
          <p v-if="candidateError" class="err">{{ candidateError }}</p>

          <template v-else-if="candidatesLoaded">
            <p v-if="!candidates.length" class="empty-text">该电影暂无候选标签。</p>
            <div v-else class="tag-grid candidate-grid">
              <article v-for="tag in candidates" :key="`${tag.seed_id}-${tag.tag_id}`" class="tag-card candidate">
                <div class="tag-head">
                  <h3>{{ tag.label_zh }}</h3>
                  <span :class="['status-badge', `status-${tag.human_status === 'confirmed' ? 'approved' : tag.human_status === 'rejected' ? 'rejected' : 'pending'}`]">
                    {{ humanLabel(tag.human_status) }}
                  </span>
                </div>
                <p class="tag-en">{{ tag.label_en }} · {{ tag.tag_id }}</p>
                <p>{{ tag.definition }}</p>
                <p class="rule-line"><strong>证据：</strong>{{ tag.evidence }}</p>
                <p class="rule-line">
                  <strong>来源：</strong>{{ tag.source_ids.join(' / ') || '—' }} ·
                  提出：{{ tag.proposed_by }}
                </p>
              </article>
            </div>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.detail-view {
  margin-top: 12px;
}

.back-link {
  display: inline-block;
  margin-bottom: 18px;
  font-size: 13px;
  color: #ff9aa8;
  text-decoration: none;
}

.back-link:hover {
  text-decoration: underline;
}

.back-link.inline {
  margin: 8px 0 0;
}

.state-card h1 {
  margin: 0 0 8px;
  font-size: 22px;
}

.detail-hero h1 {
  margin: 0;
  font-size: clamp(32px, 6vw, 52px);
  letter-spacing: 0.03em;
}

.title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.original-title {
  margin: 6px 0 0;
  font-size: 14px;
  color: #a79fae;
}

.hero-meta {
  margin: 12px 0 0;
  font-size: 12px;
  color: #8a8291;
}

.status-notice {
  margin: 18px 0 0;
  padding: 12px 16px;
  border: 1px solid rgba(255, 196, 107, 0.32);
  border-left: 3px solid #ffc46b;
  border-radius: 8px;
  background: rgba(255, 196, 107, 0.08);
  font-size: 13px;
  line-height: 1.7;
  color: #e8d5b5;
}

.status-notice.approved {
  border-color: rgba(111, 224, 168, 0.32);
  border-left-color: #6fe0a8;
  background: rgba(111, 224, 168, 0.08);
  color: #c6efd9;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.summary-cell {
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
}

.summary-value {
  display: block;
  font-size: 24px;
  color: #f2edf6;
  font-variant-numeric: tabular-nums;
}

.summary-label {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #8a8291;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.section-head h2 {
  margin: 0 0 4px;
  font-size: 16px;
  color: #e8e3ee;
}

.evidence-head {
  align-items: center;
}

.ghost-btn {
  padding: 8px 14px;
  border: 1px solid #4a4155;
  border-radius: 8px;
  background: transparent;
  color: #cfc8d6;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
}

.ghost-btn:hover {
  border-color: #8b6fe8;
  color: #e8e3ee;
}

.ghost-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.criteria-list,
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.criterion-card,
.evidence-item,
.tag-card {
  padding: 15px 17px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
}

.criterion-head,
.evidence-head,
.tag-head,
.candidate-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.criterion-head h3,
.evidence-head h3,
.tag-head h3,
.candidate-head h2 {
  margin: 0;
  font-size: 14px;
  color: #f2edf6;
}

.criterion-en,
.tag-en,
.source-title {
  margin: 4px 0 8px;
  font-size: 12px;
  color: #8a8291;
}

.criterion-card p,
.evidence-item p,
.tag-card p {
  margin: 5px 0;
  font-size: 12px;
  line-height: 1.7;
  color: #a79fae;
}

.rule-line {
  color: #8a8291 !important;
}

.criterion-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 10px;
  font-size: 11px;
  color: #8a8291;
}

.tone-badge {
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  font-size: 11px;
  white-space: nowrap;
}

.tone-ok {
  border-color: rgba(111, 224, 168, 0.4);
  background: rgba(111, 224, 168, 0.1);
  color: #6fe0a8;
}

.tone-warn {
  border-color: rgba(255, 196, 107, 0.4);
  background: rgba(255, 196, 107, 0.1);
  color: #ffc46b;
}

.tone-muted {
  color: #8a8291;
}

.tier-badge {
  display: inline-block;
  margin-right: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 10px;
  letter-spacing: 0.06em;
}

.tier-t1 {
  border-color: rgba(111, 224, 168, 0.45);
  color: #6fe0a8;
}

.tier-t2 {
  border-color: rgba(139, 111, 232, 0.5);
  color: #c9b3e6;
}

.tier-t3 {
  border-color: rgba(255, 196, 107, 0.4);
  color: #ffc46b;
}

.evidence-summary {
  color: #cfc8d6 !important;
}

.source-link-line a {
  font-size: 12px;
  color: #ff9aa8;
  text-decoration: none;
}

.source-link-line a:hover {
  text-decoration: underline;
}

.evidence-status {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.status-chip {
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-size: 10px;
  color: #a79fae;
}

.status-chip.verification {
  border-color: rgba(139, 111, 232, 0.36);
  color: #c9b3e6;
}

.status-chip.human-confirmed {
  border-color: rgba(111, 224, 168, 0.4);
  color: #6fe0a8;
}

.status-chip.human-pending {
  border-color: rgba(255, 196, 107, 0.4);
  color: #ffc46b;
}

.status-chip.human-rejected {
  border-color: rgba(255, 123, 138, 0.4);
  color: #ff9aa8;
}

.tag-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tag-dimension {
  font-size: 10px;
  letter-spacing: 0.06em;
  color: #8a8291;
}

.candidate-block {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px dashed rgba(255, 255, 255, 0.12);
}

.candidate-head {
  margin-bottom: 12px;
}

.tag-card.candidate {
  border-style: dashed;
  border-color: rgba(255, 196, 107, 0.22);
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

.status-rejected,
.status-draft,
.status-needs_fix {
  border-color: rgba(255, 123, 138, 0.34);
  background: rgba(255, 123, 138, 0.1);
  color: #ff9aa8;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .tag-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 560px) {
  .summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
