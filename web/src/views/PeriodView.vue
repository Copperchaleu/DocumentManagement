<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { appState, orderedCategories, refreshPeriodFiles } from '../stores/appState'
import {
  listPeriodFileVersions,
  openPeriodFile,
  periodDownloadUrl,
  periodVersionDownloadUrl,
  restorePeriodFileVersion,
} from '../api'
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
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyPeriodFile = ref(null)
const historyVersions = ref([])

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

// ===== 多选逻辑：用 Set 维护选中行的 id（每次变更都重新赋值新 Set，保证响应式）=====
const selectedIds = ref(new Set())

// 判断某行是否已选中
function isSelected(row) {
  return selectedIds.value.has(row.id)
}

// 切换单行选中状态
function toggleRow(row) {
  const next = new Set(selectedIds.value)
  if (next.has(row.id)) {
    next.delete(row.id)
  } else {
    next.add(row.id)
  }
  selectedIds.value = next
}

// 全选（全部文件，不局限于筛选结果）
function selectAll() {
  const next = new Set()
  for (const r of appState.periodFiles || []) {
    next.add(r.id)
  }
  selectedIds.value = next
}

// 筛选后的全选（仅当前筛选结果）
function selectFilteredAll() {
  const next = new Set(selectedIds.value)
  for (const r of filteredPeriodFiles.value) {
    next.add(r.id)
  }
  selectedIds.value = next
}

// 清空所有选中
function clearSelection() {
  selectedIds.value = new Set()
}

// 已选数量
const selectedCount = computed(() => selectedIds.value.size)

// 当前筛选结果是否全部选中（用于表头复选框状态）
const allFilteredSelected = computed(
  () =>
    filteredPeriodFiles.value.length > 0 &&
    filteredPeriodFiles.value.every((r) => selectedIds.value.has(r.id)),
)

// 表头复选框切换：勾选时筛选后全选，取消时移除筛选结果的选中
function toggleFilteredAll(val) {
  if (val) {
    selectFilteredAll()
  } else {
    const next = new Set(selectedIds.value)
    for (const r of filteredPeriodFiles.value) {
      next.delete(r.id)
    }
    selectedIds.value = next
  }
}

// 已选中的完整行（用于复制路径）
const selectedRows = computed(() =>
  (appState.periodFiles || []).filter((r) => selectedIds.value.has(r.id)),
)

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

function formatBytes(value) {
  const size = Number(value || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function localStatusText(row) {
  if (row.local_sync_status === 'error') return '本地同步失败（打开时自动重试）'
  if (row.local_sync_status === 'pending') return '数据库已更新，等待同步到本地'
  return row.exists ? '本地最新文件存在' : '本地缺失（打开时从数据库恢复）'
}

async function loadHistory(periodFileId) {
  historyLoading.value = true
  try {
    const data = await listPeriodFileVersions(periodFileId)
    historyPeriodFile.value = data.period_file || null
    historyVersions.value = data.items || []
  } finally {
    historyLoading.value = false
  }
}

async function onHistory(row) {
  historyVisible.value = true
  historyVersions.value = []
  historyPeriodFile.value = row
  try {
    await loadHistory(row.id)
    await refreshPeriodFiles()
  } catch (e) {
    toastError(e, '读取历史版本失败')
  }
}

async function onRestoreVersion(version) {
  try {
    await ElMessageBox.confirm(
      `确认把 V${version.version_no} 恢复为当前 Markdown？本次恢复也会记录为一个新版本。`,
      '恢复历史版本',
      { type: 'warning' },
    )
    const data = await restorePeriodFileVersion(version.id)
    ElMessage.success(`已恢复，并记录为 V${data.restored_version_no}`)
    const periodFileId = historyPeriodFile.value?.id
    await Promise.all([
      periodFileId ? loadHistory(periodFileId) : Promise.resolve(),
      refreshPeriodFiles(),
    ])
  } catch (e) {
    if (e !== 'cancel') toastError(e, '恢复历史版本失败')
  }
}

// 复制所选文件的绝对路径（每行一个 abs_path）
async function onCopyPaths() {
  const rows = selectedRows.value
  if (!rows.length) {
    ElMessage.warning('请先勾选要复制路径的文件')
    return
  }
  const lines = rows.map((r) => r.abs_path || '').filter(Boolean)
  if (!lines.length) {
    ElMessage.warning('所选文件缺少绝对路径')
    return
  }
  const text = lines.join('\n')
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // 兜底：旧浏览器/非安全上下文
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success(`已复制 ${lines.length} 个文件的绝对路径`)
  } catch (e) {
    toastError(e, '复制失败')
  }
}
</script>

<template>
  <div class="panel period-panel">
    <div class="panel-head">
      <div class="title-area">
        <div class="title-row">
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

        <el-divider direction="vertical" />
        <el-button @click="selectAll">全选</el-button>
        <el-button @click="selectFilteredAll">筛选后全选</el-button>
        <el-button @click="clearSelection" :disabled="selectedCount === 0">清空所选</el-button>
        <el-button type="primary" @click="onCopyPaths" :disabled="selectedCount === 0">
          复制路径（{{ selectedCount }}）
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
        empty-text="暂无汇总文件"
      >
        <el-table-column label="选择" width="70" align="center">
          <template #header>
            <el-checkbox
              :model-value="allFilteredSelected"
              @change="toggleFilteredAll"
              title="筛选后的全选"
            />
          </template>
          <template #default="{ row }">
            <el-checkbox :model-value="isSelected(row)" @change="() => toggleRow(row)" />
          </template>
        </el-table-column>
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
              <div
                class="file-status"
                :class="{
                  ok: row.exists && row.local_sync_status === 'synced',
                  missing: !row.exists || ['pending', 'error'].includes(row.local_sync_status),
                }"
                :title="row.last_sync_error || ''"
              >
                {{ localStatusText(row) }}
              </div>
              <div class="version-status" :class="{ backed: row.database_backed }">
                <template v-if="row.database_backed">
                  数据库 V{{ row.current_version_no }} · 共 {{ row.version_count }} 版
                </template>
                <template v-else>尚无数据库版本</template>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="150">
          <template #default="{ row }">
            <span class="time-text">{{ row.updated_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right" align="center">
          <template #default="{ row }">
            <div class="ops">
              <el-button plain @click="onHistory(row)">版本</el-button>
              <el-button type="primary" plain @click="onOpen(row)">打开</el-button>
              <a class="download-btn" :href="periodDownloadUrl(row)" target="_blank">下载</a>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="historyVisible"
      title="历史版本"
      width="820px"
      destroy-on-close
      append-to-body
    >
      <div v-if="historyPeriodFile" class="history-summary">
        <div>{{ historyPeriodFile.word_filename }}</div>
        <span>数据库保存全部版本，本地目录只保留当前版本；恢复不会回滚项目数据</span>
      </div>
      <el-table
        :data="historyVersions"
        v-loading="historyLoading"
        border
        stripe
        empty-text="暂无历史版本；首次保存或打开现有文件后会自动入库"
      >
        <el-table-column label="版本" width="92" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_current ? 'success' : 'info'" effect="plain" round>
              V{{ row.version_no }}{{ row.is_current ? ' 当前' : '' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="生成时间" min-width="150" />
        <el-table-column prop="change_reason" label="变化原因" min-width="180" />
        <el-table-column prop="project_count" label="项目数" width="82" align="center" />
        <el-table-column label="大小" width="90" align="right">
          <template #default="{ row }">{{ formatBytes(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="165" align="center" fixed="right">
          <template #default="{ row }">
            <div class="history-ops">
              <a
                class="history-download"
                :href="periodVersionDownloadUrl(row.id)"
                target="_blank"
              >下载</a>
              <el-button
                size="small"
                type="primary"
                plain
                :disabled="row.is_current"
                @click="onRestoreVersion(row)"
              >恢复</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
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

.version-status {
  margin-top: 2px;
  color: #94a3b8;
  font-size: 12px;
}

.version-status.backed {
  color: #4f46e5;
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

.history-summary {
  margin-bottom: 14px;
  color: #1e293b;
  font-weight: 650;
}

.history-summary span {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  font-weight: 400;
}

.history-ops {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.history-download {
  color: #4f46e5;
  font-size: 13px;
  font-weight: 650;
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
