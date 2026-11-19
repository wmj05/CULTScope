<script setup>
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '320px' },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无可展示的数据' },
  label: { type: String, default: '统计图表' }
})

const chartEl = ref(null)
let chart = null
let resizeObserver = null

function resize() {
  chart?.resize()
}

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption(props.option, true)
  nextTick(resize)
}

watch(() => props.option, render, { deep: true })

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="chart-wrap">
    <div
      ref="chartEl"
      class="imdb-echart"
      :style="{ height: props.height }"
      role="img"
      :aria-label="label"
    ></div>
    <p v-if="empty" class="chart-empty">{{ emptyText }}</p>
  </div>
</template>

<style scoped>
.imdb-echart {
  width: 100%;
}
</style>
