<script setup>
import { echarts } from '../echarts.js'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const chartEl = ref(null)
let chart = null

function buildOption() {
  // 横向条形图从下往上绘制，反转后数量最多的类型位于顶部
  const items = [...props.data].sort((a, b) => b.count - a.count)
  const genres = items.map((item) => item.genre).reverse()
  const counts = items.map((item) => item.count).reverse()

  return {
    grid: { left: 84, right: 48, top: 24, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      confine: true,
      backgroundColor: '#17131c',
      borderColor: '#3a3145',
      textStyle: { color: '#e8e3ee' },
      formatter: (params) => `${params[0].axisValue}<br/>电影数量：<b>${params[0].value}</b> 部`
    },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#a79fae' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    yAxis: {
      type: 'category',
      data: genres,
      axisLine: { lineStyle: { color: '#4a4155' } },
      axisTick: { show: false },
      axisLabel: { color: '#cfc8d6', fontSize: 12 }
    },
    series: [
      {
        type: 'bar',
        data: counts,
        barWidth: '55%',
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#5f4ba8' },
            { offset: 1, color: '#a56bd8' }
          ])
        },
        label: {
          show: true,
          position: 'right',
          color: '#e8e3ee',
          fontSize: 12,
          formatter: '{c} 部'
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
    <div ref="chartEl" class="chart"></div>
    <p v-if="!data.length" class="chart-empty">暂无数据</p>
  </div>
</template>
