<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { appState, orderedCategories, refreshPeriodFiles } from '../stores/appState'
import { openPeriodFile, periodDownloadUrl } from '../api'
import { toastError } from '../api/http'
import {
  cascaderValueToId,
  getCategoryValuePath,
  getDescendantIdsIncludingSelf,
  toCascaderOptions,
} from '../utils/tree'

const typeCn = { week: '周', month: '月', quarter: '季度' }
const typeTag = { week: 'info', month: 'success', quarter: 'warning' }

// 筛选状态：分类 id（支持中间级，过滤时含子分类）
const catFilter = ref(null)
const catFilterPath = ref([])
const typeFilter = ref('')
const dateFilter = ref(null)

const categoryCascaderOptions = computed(() => toCascaderOptions(appState.categoryTree))

const categoryCascaderProps = {
  expandTrigger: 'hover',
  checkStrictly: true,
  emitPath: true,
  value: 'value',
  label: 'label',
  children: 'children',
}

const typeOptions = [
  { value: '', label: '全部周期' },
  { value: 'week', label: '按周' },
  { value: 'month', label: '按月' },
  { value: 'quarter', label: '按季度' },
]

const filteredPeriodFiles = computed(() => {
  let list = appState.periodFiles || []
  if (catFilter.value != null) {
    const ids = getDescendantIdsIncludingSelf(catFilter.value, orderedCategories())
    list = list.filter((r) => ids.has(Number(r.category_id)))
  }
  if (typeFilter.value) {
    list = list.filter((r) => r.period_type === typeFilter.value)
  }
  const labels = getPeriodLabelsForDate(dateFilter.value)
  if (labels) {
    list = list.filter((r) => {
      if (r.period_type === 'week') return r.period_label === labels.week
      if (r.period_type === 'month') return r.period_label === labels.month
      if (r.period_type === 'quarter') return r.period_label === labels.quarter
      return false
    })
  }
  return list
})

// 根据所选日期反推其所属周/月/季度标签，与后端 path_utils 的 ISO 周规则一致
function getPeriodLabelsForDate(value) {
  if (!value) return null
  const d = value instanceof Date ? new Date(value) : new Date(value)
  if (Number.isNaN(d.getTime())) return null
  const year = d.getFullYear()
  const month = d.getMonth() + 1
  const quarter = Math.floor((month - 1) / 3) + 1

  // ISO 周（周一~周日），周年用 ISO 年，与 Python isocalendar() 对齐
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  utc.setUTCDate(utc.getUTCDate() + 4 - (utc.getUTCDay() || 7))
  const isoYear = utc.getUTCFullYear()
  const yearStart = new Date(Date.UTC(isoYear, 0, 1))
  const isoWeek = Math.ceil((utc - yearStart) / 86400000 / 7 + 1)

  return {
    week: `${isoYear}-W${String(isoWeek).padStart(2, '0')}`,
    month: `${year}-${String(month).padStart(2, '0')}`,
    quarter: `${year}-Q${quarter}`,
  }
}

async function onRefresh() {
  await refreshPeriodFiles()
}

function onCategoryFilterChange(val) {
  catFilterPath.value = Array.isArray(val) ? val : []
  catFilter.value = cascaderValueToId(val)
}

function onFilterChange() {
  // computed 自动更新
}

function clearFilters() {
  catFilter.value = null
  catFilterPath.value = []
  typeFilter.value = ''
  dateFilter.value = null
}

function syncCatPathFromId() {
  catFilterPath.value = getCategoryValuePath(catFilter.value, appState.categoryTree)
}

async function onOpen(row) {
  try {
    await openPeriodFile({
      category_id: row.category_id,
      period_type: row.period_type,
      period_label: row.period_label,
    })
    ElMessage.success('已请求用系统默认程序打开')
  } catch (e) {
    toastError(e)
  }
}
</script>

<template>
  <div class="panel period-panel">
    <div class="panel-head">
      <div class="title-area">
        <div class="title-row">
          <h2>周期 Word 文件</h2>
          <el-tag size="small" effect="plain" round type="info">
            {{ filteredPeriodFiles.length }} 个
          </el-tag>
        </div>
      </div>

      <div class="toolbar-row filter-row">
        <el-cascader
          v-model="catFilterPath"
          :options="categoryCascaderOptions"
          :props="categoryCascaderProps"
          clearable
          filterable
          class="filter-control"
          placeholder="全部分类"
          :show-all-levels="true"
          separator=" / "
          @change="onCategoryFilterChange"
          @visible-change="(v) => v && syncCatPathFromId()"
        />

        <el-select
          v-model="typeFilter"
          clearable
          class="filter-control"
          placeholder="周期类型"
          @change="onFilterChange"
        >
          <el-option
            v-for="opt in typeOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-date-picker
          v-model="dateFilter"
          type="date"
          clearable
          class="filter-control"
          placeholder="选择日期筛选周期"
          @change="onFilterChange"
        />

        <el-button @click="onRefresh" :loading="appState.loadingPeriod">刷新</el-button>
        <el-button
          v-if="catFilter != null || typeFilter || dateFilter"
          plain
          @click="clearFilters"
        >
          清空筛选
        </el-button>
      </div>
    </div>

    <div class="table-wrap">
      <el-table
        class="period-table"
        :data="filteredPeriodFiles"
        v-loading="appState.loadingPeriod"
        stripe
        border
        table-layout="fixed"
        empty-text="暂无周期文件"
      >
        <el-table-column label="分类" min-width="220">
          <template #default="{ row }">
            <span
              class="cat-path"
              :title="row.category_path_label || row.category_name"
            >
              {{ row.category_path_label || row.category_name || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="周期类型" width="108" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="plain"
              :type="typeTag[row.period_type] || 'info'"
              round
            >
              {{ typeCn[row.period_type] || row.period_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="period_label" label="周期标签" min-width="120">
          <template #default="{ row }">
            <span class="label-text">{{ row.period_label }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="project_count" label="项目数" width="90" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.project_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="文件" min-width="190">
          <template #default="{ row }">
            <div class="file-cell">
              <div class="file-name" :title="row.word_filename">{{ row.word_filename }}</div>
              <div class="file-status" :class="{ ok: row.exists, missing: !row.exists }">
                {{ row.exists ? '文件存在' : '文件缺失（可点打开重建）' }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="150">
          <template #default="{ row }">
            <span class="time-text">{{ row.updated_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right" align="center">
          <template #default="{ row }">
            <div class="ops">
              <el-button type="primary" plain @click="onOpen(row)">打开</el-button>
              <a class="download-btn" :href="periodDownloadUrl(row)" target="_blank">下载</a>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.period-panel {
  min-width: 0;
}

.filter-row {
  justify-content: flex-end;
}

.filter-control {
  width: 200px;
  height: 40px;
}

.filter-control :deep(.el-input__wrapper),
.filter-control :deep(.el-select__wrapper),
.filter-control :deep(.el-cascader .el-input__wrapper),
.filter-control :deep(.el-date-editor) {
  height: 40px;
}

.table-wrap {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.cat-path {
  color: #334155;
  font-size: 13px;
  line-height: 1.45;
}

.label-text {
  font-weight: 600;
  color: #1e293b;
  font-variant-numeric: tabular-nums;
}

.num {
  font-weight: 650;
  color: #334155;
  font-variant-numeric: tabular-nums;
}

.file-cell {
  min-width: 0;
}

.file-name {
  font-weight: 560;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-status {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.4;
}
.file-status.ok {
  color: #059669;
}
.file-status.missing {
  color: #b45309;
}

.time-text {
  color: #64748b;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.ops {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.ops :deep(.el-button) {
  min-width: 58px;
  min-height: 36px;
  padding: 8px 12px;
}

.download-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 58px;
  min-height: 36px;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  color: #1e293b;
  background: #fff;
  font-size: 13px;
  font-weight: 650;
  line-height: 1;
  transition: all 0.15s ease;
}
.download-btn:hover,
.download-btn:focus-visible {
  color: #fff;
  background: #3730a3;
  border-color: #3730a3;
  box-shadow: 0 0 0 3px rgba(55, 48, 163, 0.14);
}

:deep(.period-table .el-table__cell) {
  vertical-align: middle;
  padding-top: 12px;
  padding-bottom: 12px;
}
</style>
