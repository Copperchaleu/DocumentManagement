<script setup>
import { computed, onMounted, onBeforeUnmount, nextTick, watch, ref } from 'vue'

const props = defineProps({
  labels: { type: Array, default: () => [] },
  values: { type: Array, default: () => [] },
  activeRange: { type: String, default: 'day' },
})

const chartRef = ref(null)
let ro = null

// 均匀整数 Y 轴上限：向上取整到 4 的倍数，保证刻度整齐（max=9 → 12 → 0/3/6/9/12；max=5 → 8 → 0/2/4/6/8）
const axisMax = computed(() => {
  const m = Math.max(0, ...props.values)
  if (m <= 0) return 4
  const step = Math.max(1, Math.ceil(m / 4))
  return step * 4
})

const series = computed(() => [
  { name: '新增', data: props.values.map((v) => Number(v) || 0) },
])

const chartOptions = computed(() => ({
  chart: {
    type: 'line',
    fontFamily: 'inherit',
    toolbar: { show: false },
    zoom: { enabled: false },
    animations: { enabled: true, speed: 400 },
  },
  colors: ['#4f46e5'],
  stroke: { curve: 'straight', width: 2.5 },
  markers: { size: 3, strokeWidth: 2, strokeColors: '#fff', hover: { size: 5 } },
  fill: { type: 'solid' },
  dataLabels: { enabled: false },
  grid: {
    borderColor: '#eef2f7',
    strokeDashArray: 0,
    padding: { left: 4, right: 8, top: 0, bottom: 0 },
  },
  xaxis: {
    categories: props.labels,
    labels: {
      style: { colors: '#94a3b8', fontSize: '12px' },
      rotate: props.activeRange === 'day' ? -45 : 0,
      hideOverlappingLabels: true,
      trim: false,
    },
    axisBorder: { show: true, color: '#e2e8f0' },
    axisTicks: { show: false },
    tooltip: { enabled: false },
  },
  yaxis: {
    min: 0,
    max: axisMax.value,
    tickAmount: 4,
    labels: {
      style: { colors: '#94a3b8', fontSize: '12px' },
      formatter: (v) => Math.round(v).toString(),
    },
  },
  tooltip: {
    enabled: true,
    y: { formatter: (v) => `${v} 个` },
  },
}))

const hasData = computed(() => Array.isArray(props.labels) && props.labels.length > 0)

function resizeChart() {
  const inst = chartRef.value
  if (!inst) return
  const apex = inst.chart
  if (apex && typeof apex.resize === 'function') {
    try { apex.resize(); return } catch (e) { /* noop */ }
  }
  if (typeof inst.refresh === 'function') {
    try { inst.refresh() } catch (e) { /* noop */ }
  }
}

onMounted(() => {
  // 容器宽度变化（侧栏展开/列宽变化）时重绘，治理 0 宽或布局未稳导致的渲染异常
  if (chartRef.value && typeof ResizeObserver !== 'undefined') {
    const el = chartRef.value.$el
    ro = new ResizeObserver(() => {
      if (el && el.clientWidth > 0) resizeChart()
    })
    ro.observe(el)
  }
  nextTick(resizeChart)
})

// 数据或区间变化重绘
watch(
  () => [props.labels, props.values, props.activeRange],
  () => nextTick(resizeChart),
  { deep: true }
)

onBeforeUnmount(() => {
  if (ro) { ro.disconnect(); ro = null }
})
</script>

<template>
  <div class="trend-chart">
    <apexchart
      v-if="hasData"
      ref="chartRef"
      type="line"
      height="250"
      :options="chartOptions"
      :series="series"
    />
  </div>
</template>

<style scoped>
.trend-chart { width: 100%; }
</style>
