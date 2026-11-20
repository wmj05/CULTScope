<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const chartEl = ref(null)
let chart = null

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
    return map[char]
  })
}

function buildOption() {
  const points = props.data.map((item) => ({
    name: item.title,
    value: [item.vote_count, item.vote_average],
    decade: item.decade,
    genres: item.genres
  }))

  return {
    grid: { left: 56, right: 28, top: 36, bottom: 52 },
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: '#17131c',
      borderColor: '#3a3145',
      textStyle: { color: '#e8e3ee', fontSize: 12 },
      formatter: (params) => {
        const [votes, rating] = params.data.value
        return [
          `<b>${escapeHtml(params.data.name)}</b>`,
          `年代：${escapeHtml(params.data.decade)}`,
          `类型：${escapeHtml(params.data.genres.join(' / '))}`,
          `评分：${rating.toFixed(2)}`,
          `投票数：${votes.toLocaleString()}`
        ].join('<br/>')
      }
    },
    xAxis: {
      type: 'log',
      name: '投票数（对数轴）',
      nameLocation: 'middle',
      nameGap: 32,
      nameTextStyle: { color: '#8a8291', fontSize: 12 },
      axisLine: { lineStyle: { color: '#4a4155' } },
      axisLabel: {
        color: '#a79fae',
        formatter: (value) => (value >= 1000 ? `${value / 1000}k` : value)
      },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    yAxis: {
      type: 'value',
      name: '评分',
      min: (value) => Math.max(0, Math.floor((value.min - 0.3) * 10) / 10),
      max: (value) => Math.min(10, Math.ceil((value.max + 0.3) * 10) / 10),
      nameTextStyle: { color: '#8a8291', fontSize: 12 },
      axisLine: { show: false },
      axisLabel: { color: '#a79fae' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    series: [
      {
        type: 'scatter',
        data: points,
        symbolSize: 16,
        itemStyle: {
          color: '#4fb6c9',
          borderColor: 'rgba(255, 255, 255, 0.35)',
          borderWidth: 1
        },
        emphasis: {
          scale: 1.5,
          itemStyle: { color: '#e35d72' }
        }
      }
    ]
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(), true)
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    render()
  }
  window.addEventListener('resize', resize)
})

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="chart-wrap">
    <div ref="chartEl" class="chart chart-tall"></div>
    <p v-if="!data.length" class="chart-empty">暂无数据</p>
  </div>
</template>
