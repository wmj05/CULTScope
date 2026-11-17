<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const chartEl = ref(null)
let chart = null

function buildOption() {
  const decades = props.data.map((item) => item.decade)
  const counts = props.data.map((item) => item.count)

  return {
    grid: { left: 52, right: 24, top: 42, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: '#17131c',
      borderColor: '#3a3145',
      textStyle: { color: '#e8e3ee' },
      formatter: (params) => `${params[0].axisValue}<br/>电影数量：<b>${params[0].value}</b> 部`
    },
    xAxis: {
      type: 'category',
      data: decades,
      axisLine: { lineStyle: { color: '#4a4155' } },
      axisTick: { show: false },
      axisLabel: { color: '#a79fae', fontSize: 12 }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#a79fae' },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }
    },
    series: [
      {
        type: 'bar',
        data: counts,
        barWidth: '46%',
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#e35d72' },
            { offset: 1, color: '#7c2738' }
          ])
        },
        label: {
          show: true,
          position: 'top',
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
