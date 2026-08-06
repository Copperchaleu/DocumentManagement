<script setup>
import { computed, onMounted, onBeforeUnmount, nextTick, watch, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

// 根容器与图表实例引用：用于解决 0 宽渲染空白与切回缓存态不重绘问题
const wrapRef = ref(null)
const chartRef = ref(null)
// ResizeObserver 句柄（onBeforeUnmount 时需 disconnect）
let ro = null

// 沿用现有靛蓝主题色板（team-lead 拍板：每顶级一基色，子分类同色系深浅）
const TREEMAP_PALETTE = [
  '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc', '#0ea5e9',
  '#22d3ee', '#34d399', '#f59e0b', '#fb7185', '#a78bfa',
]

// 每个顶级分类 => 一个 series（外层分组）
const treemapSeries = computed(() => {
  if (!Array.isArray(props.items) || !props.items.length) return []
  return props.items.map((top) => {
    const children = Array.isArray(top.children) ? top.children : []
    // 有子分类：子分类为嵌套矩形；无子分类（叶子顶级）：自身成独立矩形（不隐藏）
    const data = children.length
      ? children.map((c) => ({ x: c.name, y: Number(c.project_total) || 0 }))
      : [{ x: top.name, y: Number(top.project_total) || 0 }]
    // 顶级自身数量显式展示（team-lead 拍板：series name 拼接顶级总数）
    return { name: `${top.name}(${top.project_total})`, data }
  })
})

// 是否存在任意有效数据（规避 ApexCharts 全 0 等面积怪异）
const hasData = computed(
  () =>
    Array.isArray(props.items) &&
    props.items.some((it) => (Number(it.project_total) || 0) > 0)
)

const treemapOptions = computed(() => ({
  chart: {
    type: 'treemap',
    fontFamily: 'inherit',
    toolbar: { show: false },
    animations: { enabled: true, speed: 400 },
  },
  legend: { show: false },
  plotOptions: {
    treemap: {
      distributed: false, // 按 series（顶级）分组上色
      enableShades: true, // 子分类用同色系深浅区分
      shadeIntensity: 0.45,
    },
  },
  colors: TREEMAP_PALETTE, // 每个 series（顶级）取一个基色
  dataLabels: {
    enabled: true,
    style: { fontSize: '12px', fontWeight: 600, colors: ['#fff'] },
    // 显示 名称 + 数量
    formatter: (text, op) => [text, op.value].join('  '),
  },
  stroke: { width: 2, colors: ['#fff'] },
  tooltip: {
    enabled: true,
    y: { formatter: (val) => `${val} 个项目` },
  },
}))

// 强制重绘图表：优先 resize()，失败则 refresh()（销毁重建）
function refreshChart() {
  const inst = chartRef.value
  if (!inst) return
  const apex = inst.chart
  if (apex && typeof apex.resize === 'function') {
    try {
      apex.resize()
      return
    } catch (e) {
      /* fallthrough */
    }
  }
  if (typeof inst.refresh === 'function') {
    try {
      inst.refresh()
    } catch (e) {
      /* noop */
    }
  }
}

onMounted(() => {
  // 容器宽度一旦变为 > 0 即重绘，治理首访时布局未稳导致 0 宽空白且不自愈
  if (wrapRef.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => {
      if (wrapRef.value && wrapRef.value.clientWidth > 0) {
        refreshChart()
      }
    })
    ro.observe(wrapRef.value)
  }
  // 兜底：挂载后下一帧尝试重绘一次
  nextTick(refreshChart)
})

// 数据到达/变化时重绘（props.items 异步返回或父级 key 强制重挂载后）
watch(
  () => props.items,
  () => nextTick(refreshChart),
  { deep: true }
)

onBeforeUnmount(() => {
  if (ro) {
    ro.disconnect()
    ro = null
  }
})
</script>

<template>
  <div class="cat-treemap" ref="wrapRef">
    <apexchart
      v-if="hasData"
      ref="chartRef"
      type="treemap"
      height="280"
      :options="treemapOptions"
      :series="treemapSeries"
    />
    <div v-else class="cat-empty">分类下暂无项目</div>
  </div>
</template>

<style scoped>
.cat-treemap { width: 100%; }
.cat-empty { padding: 24px; text-align: center; color: #94a3b8; font-size: 13px; }
</style>
