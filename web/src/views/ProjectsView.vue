<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  appState,
  refreshCategories,
  refreshPeriodFiles,
  refreshProjects,
} from '../stores/appState'
import {
  attachmentDownloadUrl,
  deleteProject,
  getProject,
  openPeriodFile,
} from '../api'
import { toastError } from '../api/http'
import {
  cascaderValueToId,
  getCategoryValuePath,
  toCascaderOptions,
} from '../utils/tree'

const router = useRouter()
const detailVisible = ref(false)
const detail = ref(null)
const tableRef = ref(null)
const tableWrapRef = ref(null)
let tableResizeObserver = null

// 侧边栏展开/折叠、窗口缩放会改变表格容器宽度；固定列需重新布局，否则“操作”列会与相邻列重叠
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !tableWrapRef.value) return
  tableResizeObserver = new ResizeObserver(() => {
    tableRef.value?.doLayout?.()
  })
  tableResizeObserver.observe(tableWrapRef.value)
})

onUnmounted(() => {
  tableResizeObserver?.disconnect()
  tableResizeObserver = null
})

const categoryCascaderOptions = computed(() => toCascaderOptions(appState.categoryTree))

const categoryCascaderProps = {
  expandTrigger: 'hover',
  checkStrictly: true,
  emitPath: true,
  value: 'value',
  label: 'label',
  children: 'children',
}

const selectedCategoryPath = computed({
  get: () => getCategoryValuePath(appState.selectedCategoryId, appState.categoryTree),
  set: (val) => {
    appState.selectedCategoryId = cascaderValueToId(val)
  },
})

function onCategoryFilterChange() {
  onRefresh()
}

function periodTags(row) {
  const tags = []
  if (row.week_label) {
    tags.push({ type: '', periodType: 'week', periodLabel: row.week_label, text: `周 ${row.week_label}` })
  }
  if (row.month_label) {
    tags.push({ type: 'success', periodType: 'month', periodLabel: row.month_label, text: `月 ${row.month_label}` })
  }
  if (row.quarter_label) {
    tags.push({ type: 'warning', periodType: 'quarter', periodLabel: row.quarter_label, text: `季 ${row.quarter_label}` })
  }
  return tags
}

async function onOpenProjectPeriod(row, tag) {
  try {
    await openPeriodFile({
      category_id: row.category_id,
      period_type: tag.periodType,
      period_label: tag.periodLabel,
    })
    ElMessage.success(`已请求打开${tag.text}周期 Word`)
  } catch (e) {
    toastError(e, '打开周期 Word 失败')
  }
}

async function onRefresh() {
  await refreshProjects()
}

async function onShowDetail(row) {
  try {
    detail.value = await getProject(row.id)
    detailVisible.value = true
  } catch (e) {
    toastError(e)
  }
}

async function onEdit(row) {
  try {
    const p = await getProject(row.id)
    sessionStorage.setItem('edit_project_payload', JSON.stringify(p))
    router.push({ name: 'compose', query: { edit: String(row.id) } })
  } catch (e) {
    toastError(e)
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm('确认删除该项目？将从周期合并 Word 中移除。', '删除确认', {
      type: 'warning',
    })
    await deleteProject(row.id)
    ElMessage.success('项目已删除')
    await Promise.all([refreshProjects(), refreshCategories(), refreshPeriodFiles()])
  } catch (e) {
    if (e !== 'cancel') toastError(e)
  }
}
</script>

<template>
  <div class="panel projects-panel">
    <div class="panel-head">
      <div class="title-area">
        <div class="title-row">
          <h2>项目列表</h2>
          <el-tag size="small" effect="plain" round type="info">
            {{ appState.projects?.length || 0 }} 条
          </el-tag>
        </div>
      </div>
      <div class="toolbar-row">
        <el-cascader
          v-model="selectedCategoryPath"
          :options="categoryCascaderOptions"
          :props="categoryCascaderProps"
          clearable
          filterable
          style="width: 260px"
          placeholder="全部分类（支持中间级）"
          :show-all-levels="true"
          separator=" / "
          @change="onCategoryFilterChange"
        />
        <el-checkbox v-model="appState.includeDraft" border @change="onRefresh">
          含草稿
        </el-checkbox>
        <el-button @click="onRefresh" :loading="appState.loadingProjects">刷新</el-button>
        <el-button type="primary" @click="$router.push({ name: 'compose', query: { create: String(Date.now()) } })">新建项目</el-button>
      </div>
    </div>

    <div ref="tableWrapRef" class="table-wrap">
      <el-table
        ref="tableRef"
        class="projects-table"
        :data="appState.projects"
        v-loading="appState.loadingProjects"
        stripe
        border
        table-layout="fixed"
        empty-text="暂无项目"
      >
        <el-table-column label="项目标题" min-width="220">
          <template #default="{ row }">
            <div class="title-cell">
              <div class="title-text" :title="row.title">{{ row.title }}</div>
              <div class="preview-text" :title="row.content_preview || ''">
                {{ (row.content_preview || '').slice(0, 72) || '无内容预览' }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分类路径" min-width="160">
          <template #default="{ row }">
            <span class="path-text" :title="(row.category_path_names || []).join(' / ')">
              {{ (row.category_path_names || []).join(' / ') || row.category_name || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'draft' ? 'warning' : 'success'"
              size="small"
              effect="light"
              round
            >
              {{ row.status === 'draft' ? '草稿' : '已保存' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间周期" min-width="190">
          <template #default="{ row }">
            <div class="tag-wrap">
              <button
                v-for="t in periodTags(row)"
                :key="t.text"
                type="button"
                class="period-link"
                :title="`打开对应的${t.text}周期 Word`"
                @click="onOpenProjectPeriod(row, t)"
              >
                <el-tag size="small" :type="t.type || 'info'" effect="plain">
                  {{ t.text }}
                </el-tag>
              </button>
              <span v-if="!periodTags(row).length" class="hint">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="附件" width="72" align="center">
          <template #default="{ row }">
            <span class="num">{{ (row.attachments || []).length || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="150">
          <template #default="{ row }">
            <span class="time-text">{{ row.updated_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right" align="center">
          <template #default="{ row }">
            <div class="ops">
              <el-button type="primary" plain @click="onEdit(row)">编辑</el-button>
              <el-button @click="onShowDetail(row)">详情</el-button>
              <el-button type="danger" plain @click="onDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="detailVisible"
      title="项目详情"
      width="680px"
      class="detail-dialog"
      destroy-on-close
      append-to-body
    >
      <template v-if="detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="分类">
            {{ (detail.category_path_names || []).join(' / ') || detail.category_name }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag
              size="small"
              :type="detail.status === 'draft' ? 'warning' : 'success'"
              effect="light"
              round
            >
              {{ detail.status === 'draft' ? '草稿' : '已保存' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="时间">
            创建 {{ detail.created_at }} / 更新 {{ detail.updated_at }}
          </el-descriptions-item>
          <el-descriptions-item label="内容">
            <pre class="detail-content">{{ detail.content }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="附件">
            <div v-if="(detail.attachments || []).length" class="attach-list">
              <a
                v-for="a in detail.attachments"
                :key="a.id"
                class="attach-link"
                :href="attachmentDownloadUrl(a.id)"
                target="_blank"
              >
                {{ a.original_name }}
              </a>
            </div>
            <span v-else class="hint">无附件</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.projects-panel {
  min-width: 0;
}

.table-wrap {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.title-cell {
  min-width: 0;
}

.title-text {
  font-weight: 650;
  color: var(--text, #0f172a);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-text {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-text {
  color: #475569;
  font-size: 12.5px;
  line-height: 1.45;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.period-link {
  display: inline-flex;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font: inherit;
  text-decoration: none;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.15s ease;
}

.period-link:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(55, 48, 163, 0.16);
}

.period-link:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(55, 48, 163, 0.2);
}

.period-link :deep(.el-tag) {
  cursor: pointer;
}

.period-link:hover :deep(.el-tag) {
  border-color: #3730a3 !important;
  color: #312e81 !important;
}

.num {
  font-variant-numeric: tabular-nums;
  color: #334155;
  font-weight: 600;
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

.ops :deep(.el-button + .el-button) {
  margin-left: 0;
}

.detail-content {
  white-space: pre-wrap;
  margin: 0;
  font-family: inherit;
  line-height: 1.65;
  color: #1e293b;
  max-height: 320px;
  overflow: auto;
  padding: 4px 0;
}

.attach-list {
  display: grid;
  gap: 6px;
}

.attach-link {
  display: inline-flex;
  align-items: center;
  font-weight: 560;
}

:deep(.projects-table .el-table__cell) {
  vertical-align: middle;
  padding-top: 12px;
  padding-bottom: 12px;
}
</style>
