<script setup>
import { computed } from 'vue'

const props = defineProps({
  labels: { type: Array, default: () => [] },
  values: { type: Array, default: () => [] },
  activeRange: { type: String, default: 'day' },
})

const COLOR = '#4f46e5'
const VB_W = 760
const VB_H = 280
const PAD = { top: 22, right: 22, bottom: 34, left: 38 }

const innerW = computed(() => VB_W - PAD.left - PAD.right)
const innerH = computed(() => VB_H - PAD.top - PAD.bottom)

const maxValue = computed(() => {
  const max = Math.max(0, ...props.values)
  return max <= 0 ? 1 : max
})

// 折线模式（日）：连续折线 + 渐变面积
const isBar = computed(() => props.activeRange !== 'day')

const points = computed(() => {
  const n = props.values.length
  if (!n) return []
  const stepX = n > 1 ? innerW.value / (n - 1) : 0
  return props.values.map((v, i) => {
    const x = PAD.left + (n > 1 ? stepX * i : innerW.value / 2)
    const y = PAD.top + innerH.value * (1 - v / maxValue.value)
    return { x, y, v, label: props.labels[i] }
  })
})

const linePath = computed(() => {
  if (!points.value.length) return ''
  return points.value
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ')
})

const areaPath = computed(() => {
  if (!points.value.length) return ''
  const baseY = PAD.top + innerH.value
  const first = points.value[0]
  const last = points.value[points.value.length - 1]
  return (
    `M ${first.x.toFixed(1)} ${baseY} ` +
    points.value.map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ') +
    ` L ${last.x.toFixed(1)} ${baseY} Z`
  )
})

// 柱状模式（月/季）
const bars = computed(() => {
  const n = props.values.length
  if (!n) return []
  const gap = 14
  const barW = Math.max(10, (innerW.value - gap * (n - 1)) / n)
  return props.values.map((v, i) => {
    const x = PAD.left + i * (barW + gap)
    const h = innerH.value * (v / maxValue.value)
    const y = PAD.top + innerH.value - h
    return { x, y, w: barW, h, v, label: props.labels[i] }
  })
})

const yTicks = computed(() => {
  const ticks = []
  const steps = 4
  for (let i = 0; i <= steps; i++) {
    const val = Math.round((maxValue.value / steps) * i)
    const y = PAD.top + innerH.value * (1 - i / steps)
    ticks.push({ y, val })
  }
  return ticks
})

// 统一各模式下的 x 轴标签横坐标
const labelPositions = computed(() => {
  const n = props.labels.length
  if (!n) return []
  if (isBar.value) return bars.value.map((b) => b.x + b.w / 2)
  return points.value.map((p) => p.x)
})

// 日模式标签较多，做抽稀以保证不拥挤
const visibleLabelIdx = computed(() => {
  const n = props.labels.length
  if (props.activeRange === 'day') {
    const step = Math.max(1, Math.ceil(n / 7))
    const set = new Set()
    for (let i = 0; i < n; i += step) set.add(i)
    set.add(n - 1)
    return set
  }
  return new Set(props.labels.map((_, i) => i))
})
</script>

<template>
  <div class="trend-chart">
    <svg
      :viewBox="`0 0 ${VB_W} ${VB_H}`"
      class="trend-svg"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id="trendArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#4f46e5" stop-opacity="0.28" />
          <stop offset="100%" stop-color="#4f46e5" stop-opacity="0" />
        </linearGradient>
      </defs>

      <!-- 横向网格 + Y 轴刻度 -->
      <g class="trend-grid">
        <line
          v-for="(t, i) in yTicks"
          :key="`y${i}`"
          :x1="PAD.left"
          :x2="VB_W - PAD.right"
          :y1="t.y"
          :y2="t.y"
        />
        <text
          v-for="(t, i) in yTicks"
          :key="`yt${i}`"
          :x="PAD.left - 8"
          :y="t.y + 4"
          class="trend-axis-y"
        >{{ t.val }}</text>
      </g>

      <!-- 柱状模式 -->
      <g v-if="isBar">
        <rect
          v-for="(b, i) in bars"
          :key="`b${i}`"
          :x="b.x"
          :y="b.y"
          :width="b.w"
          :height="Math.max(0, b.h)"
          :rx="4"
          :fill="COLOR"
        />
      </g>

      <!-- 折线 + 面积模式 -->
      <g v-else>
        <path :d="areaPath" fill="url(#trendArea)" />
        <path
          :d="linePath"
          fill="none"
          :stroke="COLOR"
          stroke-width="2.5"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
        <circle
          v-for="(p, i) in points"
          :key="`p${i}`"
          :cx="p.x"
          :cy="p.y"
          r="3.5"
          fill="#fff"
          :stroke="COLOR"
          stroke-width="2"
        />
      </g>

      <!-- X 轴标签 -->
      <text
        v-for="(lab, i) in labels"
        v-show="visibleLabelIdx.has(i)"
        :key="`x${i}`"
        :x="labelPositions[i]"
        :y="VB_H - 12"
        class="trend-axis-x"
        text-anchor="middle"
      >{{ lab }}</text>
    </svg>
  </div>
</template>

<style scoped>
.trend-chart { width: 100%; }
.trend-svg { width: 100%; height: auto; display: block; }
.trend-grid line { stroke: #eef2f7; stroke-width: 1; }
.trend-axis-y { fill: #94a3b8; font-size: 11px; text-anchor: end; }
.trend-axis-x { fill: #94a3b8; font-size: 11px; }
</style>
