<script setup>
import { computed, onMounted, onActivated, ref } from 'vue'
import { Calendar, TrendCharts } from '@element-plus/icons-vue'
import TrendChart from './TrendChart.vue'
import CategoryTreemap from './CategoryTreemap.vue'
import { getProjectStatsSummary, getProjectStatsTrend, getCategoryTree } from '../api/index.js'
import { toastError } from '../api/http.js'

const summary = ref({ today: 0, month: 0, quarter: 0 })
const trendLabels = ref([])
const trendValues = ref([])
const activeRange = ref('day')
const loading = ref(false)
const trendLoading = ref(false)
const catTree = ref([])
const catLoading = ref(false)
// 切回看板时强制造 CategoryTreemap 重挂载，避免 keep-alive 缓存态下图表停在空白态
const catTreeKey = ref(0)

const rangeOptions = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
]

async function loadSummary() {
  try {
    const data = await getProjectStatsSummary()
    summary.value = {
      today: Number(data?.today) || 0,
      month: Number(data?.month) || 0,
      quarter: Number(data?.quarter) || 0,
    }
  } catch (error) {
    toastError(error, '加载统计概览失败')
  }
}

async function loadTrend(range = activeRange.value) {
  trendLoading.value = true
  try {
    const data = await getProjectStatsTrend(range)
    trendLabels.value = Array.isArray(data?.labels) ? data.labels : []
    trendValues.value = Array.isArray(data?.values)
      ? data.values.map((v) => Number(v) || 0)
      : []
  } catch (error) {
    toastError(error, '加载趋势数据失败')
    trendLabels.value = []
    trendValues.value = []
  } finally {
    trendLoading.value = false
  }
}

async function loadCategoryTree() {
  catLoading.value = true
  try {
    const data = await getCategoryTree()
    catTree.value = Array.isArray(data?.items) ? data.items : []
  } catch (error) {
    toastError(error, '加载分类统计失败')
    catTree.value = []
  } finally {
    catLoading.value = false
  }
}

async function loadStats() {
  loading.value = true
  try {
    await Promise.all([
      loadSummary(),
      loadTrend(activeRange.value),
      loadCategoryTree(),
    ])
  } finally {
    loading.value = false
  }
}

function changeRange(range) {
  activeRange.value = range
  loadTrend(range)
}

// 供外壳 WorkbenchView 在切到看板 Tab 时刷新
function refresh() {
  loadStats()
}

onMounted(() => {
  loadStats()
})

// keep-alive 缓存：切回看板时面板可见、容器尺寸已正确，强制 treemap 重挂载并重新拉数据
onActivated(() => {
  catTreeKey.value++
  loadStats()
})

defineExpose({ refresh })
</script>

<template>
  <div class="dashboard-panel">
    <section class="dashboard-metrics" aria-label="新增概览">
      <article class="metric-card metric-indigo">
        <div class="metric-icon"><Calendar /></div>
        <div class="metric-inline">
          <div class="metric-stat">
            <div class="metric-stat-main"><span>当日新增</span><strong>{{ summary.today }}</strong></div>
            <small>今天新保存的项目</small>
          </div>
          <div class="metric-stat">
            <div class="metric-stat-main"><span>当月新增</span><strong>{{ summary.month }}</strong></div>
            <small>本月累计新增</small>
          </div>
          <div class="metric-stat">
            <div class="metric-stat-main"><span>当季新增</span><strong>{{ summary.quarter }}</strong></div>
            <small>本季度累计新增</small>
          </div>
        </div>
      </article>
    </section>

    <section class="workbench-card dashboard-trend">
      <header class="workbench-card-head">
        <div class="section-title">
          <span class="section-kicker">TREND</span>
          <h2>新增趋势</h2>
        </div>
        <el-segmented v-model="activeRange" :options="rangeOptions" @change="changeRange" />
      </header>

      <div class="trend-body">
        <div v-if="trendLoading" class="trend-loading"><span>加载中…</span></div>
        <div v-else-if="trendLabels.length" class="trend-canvas">
          <TrendChart :labels="trendLabels" :values="trendValues" :active-range="activeRange" />
        </div>
        <div v-else class="trend-empty">
          <div class="empty-illustration"><TrendCharts /></div>
          <h3>暂无新增项目数据</h3>
          <p>保存项目后，这里会展示新增趋势</p>
        </div>
      </div>
    </section>

    <section class="workbench-card dashboard-cat">
      <header class="workbench-card-head">
        <div class="section-title">
          <span class="section-kicker">CATEGORIES</span>
          <h2>按分类统计</h2>
        </div>
      </header>
      <div class="cat-body">
        <div v-if="catLoading" class="cat-loading">加载中…</div>
        <div v-else-if="!catTree.length" class="cat-empty">暂无分类数据</div>
        <CategoryTreemap v-else :items="catTree" :key="catTreeKey" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-panel { --wb-indigo: #4f46e5; --wb-navy: #172554; }
.dashboard-metrics { display: grid; grid-template-columns: 1fr; gap: 14px; }
.metric-card { position: relative; overflow: hidden; min-height: 98px; padding: 14px 16px; border: 1px solid #e2e8f0; border-radius: 15px; background: rgba(255,255,255,.92); box-shadow: 0 5px 16px rgba(15, 23, 42, .045); }
.metric-card .metric-icon { margin-bottom: 8px; }
.metric-inline { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.metric-stat { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.metric-stat-main { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.metric-stat span { color: #475569; font-size: 13px; font-weight: 650; }
.metric-stat strong { color: #0f172a; font-size: 25px; line-height: 1; }
.metric-stat small { color: #94a3b8; font-size: 11px; }
.metric-icon { display: grid; place-items: center; width: 28px; height: 28px; margin-bottom: 8px; border-radius: 9px; }
.metric-icon svg { width: 16px; }
.metric-indigo .metric-icon { color: #4f46e5; background: #eef2ff; }
.workbench-card { border: 1px solid #dde5ef; border-radius: 19px; background: rgba(255,255,255,.96); box-shadow: 0 10px 30px rgba(15, 23, 42, .055); }
.dashboard-trend { margin-top: 16px; padding: 21px; }
.dashboard-cat { margin-top: 16px; padding: 21px; }
.workbench-card-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.workbench-card h2 { margin: 3px 0 0; color: #172554; font-size: 19px; letter-spacing: -.02em; }
.section-kicker { color: #6366f1; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.cat-body { margin-top: 12px; }
.cat-loading, .cat-empty { padding: 24px; text-align: center; color: #94a3b8; font-size: 13px; }
.trend-body { margin-top: 14px; }
.trend-canvas { }
.section-title { display: flex; align-items: baseline; gap: 10px; }
.section-title h2 { margin: 0; }
.trend-loading, .trend-empty { display: grid; place-items: center; align-content: center; gap: 4px; min-height: 250px; color: #94a3b8; font-size: 13px; text-align: center; }
.empty-illustration { display: grid; place-items: center; width: 60px; height: 60px; border-radius: 20px; background: linear-gradient(135deg,#eef2ff,#e0e7ff); color: #6366f1; }
.empty-illustration svg { width: 26px; }
.trend-empty h3 { margin: 14px 0 6px; font-size: 15px; color: #334155; }
.trend-empty p { margin: 0; color: #94a3b8; font-size: 12px; }
@media (max-width: 860px) { .dashboard-metrics { grid-template-columns: 1fr; } }
</style>
