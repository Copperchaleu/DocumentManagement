<script setup>
import { computed, onMounted, onBeforeUnmount, nextTick, watch, ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const router = useRouter()

// 根容器与图表实例引用：用于解决 0 宽首次空白与切回缓存态不重绘问题
const wrapRef = ref(null)
const chartRef = ref(null)
// ResizeObserver 句柄（onBeforeUnmount 时需 disconnect）
let ro = null

// 沿用现有靛蓝主题色板（每方块取一基色，同级多分类用不同色区分）
const TREEMAP_PALETTE = [
  '#4f46e5', '#6366f1', '#818cf8', '#a5b4fc', '#0ea5e9',
  '#22d3ee', '#34d399', '#f59e0b', '#fb7185', '#a78bfa',
]

// 下钻路径：从顶级到当前层级的节点链（{id, name}）；空数组 = 显示顶级
const drillPath = ref([])

// 按 drillPath 从完整多级树定位「当前层级」的节点数组
const currentNodes = computed(() => {
  let level = Array.isArray(props.items) ? props.items : []
  for (const { id } of drillPath.value) {
    const found = level.find((n) => n.id === id)
    if (!found || !Array.isArray(found.children) || !found.children.length) return []
    level = found.children
  }
  return level
})

// 当前层级扁平方块（名称只取当前级，不含上级路径）；面积用子树总数
const currentFlat = computed(() =>
  currentNodes.value.map((n) => ({
    id: n.id,
    name: n.name,
    total: Number(n.project_total) || 0,
    hasChildren: Array.isArray(n.children) && n.children.length > 0,
  }))
)

// 单 series：当前层级所有分类作为同级方块，点击逐级下钻（参考官方 treemap-with-drilldown）
const treemapSeries = computed(() => {
  if (!currentFlat.value.length) return []
  return [{ data: currentFlat.value.map((n) => ({ x: n.name, y: n.total })) }]
})

// 当前层级是否至少有一个方块
const hasData = computed(() => currentFlat.value.length > 0)

// 处理 Treemap 方块点击：有子分类仅下钻；叶子才跳转项目列表并筛选
function onTreemapClick(_event, _chartContext, config) {
  // 边界防护：dataPointIndex 可能为 undefined / -1 / 越界
  const idx = config?.dataPointIndex
  if (idx == null || idx < 0 || idx >= currentFlat.value.length) return

  const node = currentFlat.value[idx]
  if (!node) return

  if (node.hasChildren) {
    // 有子分类：仅逐级展开下一级，绝不跳转 projects
    drillPath.value = [...drillPath.value, { id: node.id, name: node.name }]
    return
  }

  // 叶子（最后一级）：跳转项目列表并按该分类筛选
  router.push({ name: 'projects', query: { categoryId: String(node.id) } })
}

const treemapOptions = computed(() => ({
  chart: {
    type: 'treemap',
    fontFamily: 'inherit',
    toolbar: { show: false },
    animations: { enabled: true, speed: 400 },
    events: {
      click: onTreemapClick,
    },
  },
  legend: { show: false },
  plotOptions: {
    treemap: {
      distributed: true, // 同级多分类各取一基色区分
      enableShades: false,
    },
  },
  colors: TREEMAP_PALETTE,
  dataLabels: {
    enabled: true,
    style: { fontSize: '12px', fontWeight: 600, colors: ['#fff'] },
    // 显示 名称 + 数量
    formatter: (text, op) => [text, op.value].join('  '),
  },
  stroke: { width: 2, colors: ['#fff'] },
  tooltip: {
    enabled: true,
    // 按叶子/非叶子给出不同操作暗示
    custom: ({ seriesIndex, dataPointIndex, w }) => {
      const node = currentFlat.value[dataPointIndex]
      const name = node?.name ?? w?.globals?.labels?.[dataPointIndex] ?? ''
      const val = node?.total ?? w?.globals?.series?.[seriesIndex]?.[dataPointIndex] ?? 0
      const hint = node?.hasChildren ? '点击展开下一级' : '点击查看该分类下的项目'
      return (
        `<div class="apexcharts-tooltip-title" style="font-family:inherit;font-size:12px;padding:6px 10px;">` +
        `${name}</div>` +
        `<div style="font-family:inherit;font-size:12px;padding:6px 10px;">` +
        `${val} 个项目<br/><span style="color:#64748b;">${hint}</span></div>`
      )
    },
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

// 面包屑导航：回到顶级 / 跳到第 index 级
function goRoot() {
  drillPath.value = []
}
function goTo(index) {
  // 当前层不可再点回自身
  if (index === drillPath.value.length - 1) return
  drillPath.value = drillPath.value.slice(0, index + 1)
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

// 数据到达/下钻变化时重绘（props.items 异步返回、或 drillPath 切换层级）
watch(
  () => [props.items, drillPath.value.length],
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
    <div class="cat-breadcrumb" v-if="drillPath.length">
      <span class="crumb root" @click="goRoot">全部分类</span>
      <template v-for="(node, i) in drillPath" :key="node.id">
        <span class="crumb-sep">/</span>
        <span
          class="crumb"
          :class="{ current: i === drillPath.length - 1 }"
          @click="goTo(i)"
          >{{ node.name }}</span
        >
      </template>
    </div>
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
.cat-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
  font-size: 13px;
}
.crumb {
  color: #4f46e5;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
  transition: background 0.15s ease;
}
.crumb:hover { background: rgba(79, 70, 229, 0.10); }
.crumb.root { font-weight: 600; }
.crumb.current { color: #172554; cursor: default; font-weight: 600; }
.crumb.current:hover { background: transparent; }
.crumb-sep { color: #94a3b8; }
.cat-empty { padding: 24px; text-align: center; color: #94a3b8; font-size: 13px; }
/* ApexCharts treemap 方块统一 pointer，tooltip 区分叶子/非叶子操作 */
.cat-treemap :deep(.apexcharts-treemap-rect) {
  cursor: pointer;
}
</style>
