<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Folder,
  Document,
  Plus,
  EditPen,
  FolderOpened,
  Delete,
} from '@element-plus/icons-vue'
import {
  appState,
  orderedCategories,
  refreshCategories,
  refreshProjects,
} from '../stores/appState'
import { deleteCategory, openCategoryFolder } from '../api'
import { toastError } from '../api/http'
import CategoryDialog from '../components/CategoryDialog.vue'

const dialogRef = ref(null)
const tableData = computed(() => orderedCategories())

function depthOf(row) {
  return Math.max(0, (row.path_names?.length || 1) - 1)
}

/** 层级：1=一级分类，2=二级分类 ... */
function levelOf(row) {
  return Math.max(1, (row.path_names?.length || depthOf(row) + 1 || 1))
}

function levelLabel(row) {
  const n = levelOf(row)
  const cn = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
  if (n <= cn.length) return `${cn[n - 1]}级分类`
  return `${n}级分类`
}

function levelTagType(row) {
  // 末级（可挂项目）用 success，其它层级用 info/primary 区分
  if (row.is_leaf) return 'success'
  if (levelOf(row) === 1) return 'primary'
  return 'info'
}

function localPathOf(row) {
  return row.resolved_path || row.path || ''
}

function openCreate() {
  dialogRef.value?.open()
}

function openEdit(row) {
  dialogRef.value?.open(row)
}

function openAddChild(row) {
  dialogRef.value?.open(null, row.id)
}

async function onOpenFolder(row) {
  try {
    await openCategoryFolder(row.id)
    ElMessage.success('已请求打开本地目录')
  } catch (e) {
    toastError(e)
  }
}

async function onDelete(row) {
  if ((row.child_count || 0) > 0) {
    ElMessage.error('请先删除子分类')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除分类「${row.path_label || row.name}」？\n其下项目也会被删除。`,
      '删除确认',
      { type: 'warning' },
    )
    await deleteCategory(row.id)
    ElMessage.success('分类已删除')
    if (appState.selectedCategoryId === row.id) appState.selectedCategoryId = null
    await Promise.all([refreshCategories(), refreshProjects()])
  } catch (e) {
    if (e !== 'cancel') toastError(e)
  }
}
</script>

<template>
  <div class="panel cat-panel">
    <div class="panel-head cat-head">
      <div class="head-text">
        <div class="title-row">
          <h2>分类管理</h2>
          <el-tag size="small" effect="plain" round type="info">
            {{ tableData.length }} 个
          </el-tag>
        </div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建分类</el-button>
    </div>

    <div class="table-wrap">
      <el-table
        class="cat-table"
        :data="tableData"
        v-loading="appState.loadingCategories"
        stripe
        border
        table-layout="fixed"
        empty-text="还没有分类，点击右上角新建"
      >
        <el-table-column label="分类" min-width="280">
          <template #default="{ row }">
            <div class="name-cell" :style="{ paddingLeft: `${depthOf(row) * 18}px` }">
              <el-icon class="type-icon" :class="{ leaf: row.is_leaf }">
                <Document v-if="row.is_leaf" />
                <Folder v-else />
              </el-icon>
              <div class="name-main">
                <div class="name-line">
                  <span class="name-text" :title="row.name">{{ row.name }}</span>
                  <el-tag size="small" :type="levelTagType(row)" effect="plain" round>
                    {{ levelLabel(row) }}
                  </el-tag>
                </div>
                <div
                  v-if="row.description && row.description.trim()"
                  class="desc-line"
                  :title="row.description"
                >
                  {{ row.description }}
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="上级路径" min-width="180">
          <template #default="{ row }">
            <template v-if="(row.path_names?.length || 1) > 1">
              <el-tooltip
                :content="(row.path_names || []).slice(0, -1).join(' / ')"
                placement="top"
                :show-after="400"
              >
                <span class="ellipsis">
                  {{ (row.path_names || []).slice(0, -1).join(' / ') }}
                </span>
              </el-tooltip>
            </template>
            <span v-else class="empty-path">—</span>
          </template>
        </el-table-column>

        <el-table-column label="本地目录" min-width="200">
          <template #default="{ row }">
            <template v-if="localPathOf(row)">
              <el-tooltip :content="localPathOf(row)" placement="top" :show-after="400">
                <span class="ellipsis path-text">{{ localPathOf(row) }}</span>
              </el-tooltip>
            </template>
            <span v-else class="empty-path">未设置</span>
          </template>
        </el-table-column>

        <el-table-column label="子类" width="72" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.child_count || 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="项目" width="72" align="center">
          <template #default="{ row }">
            <span class="num">{{ row.project_count || 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="206" align="center" fixed="right">
          <template #default="{ row }">
            <div class="ops">
              <el-tooltip content="添加子分类" :show-after="300">
                <el-button circle :icon="Plus" @click="openAddChild(row)" />
              </el-tooltip>
              <el-tooltip v-if="localPathOf(row)" content="打开本地目录" :show-after="300">
                <el-button
                  circle
                  :icon="FolderOpened"
                  @click="onOpenFolder(row)"
                />
              </el-tooltip>
              <el-tooltip content="编辑" :show-after="300">
                <el-button
                  circle
                  type="primary"
                  plain
                  :icon="EditPen"
                  @click="openEdit(row)"
                />
              </el-tooltip>
              <el-tooltip content="删除" :show-after="300">
                <el-button
                  circle
                  type="danger"
                  plain
                  :icon="Delete"
                  @click="onDelete(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <CategoryDialog ref="dialogRef" @saved="refreshCategories" />
  </div>
</template>

<style scoped>
.cat-panel {
  min-width: 0;
}

.cat-head {
  align-items: center;
}

.head-text {
  min-width: 0;
  flex: 1;
}

.table-wrap {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.cat-table {
  width: 100%;
}

.name-cell {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.type-icon {
  margin-top: 3px;
  color: #f59e0b;
  flex-shrink: 0;
  font-size: 16px;
}

.type-icon.leaf {
  color: #4f46e5;
}

.name-main {
  min-width: 0;
  flex: 1;
}

.name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.name-text {
  font-weight: 650;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  letter-spacing: 0.01em;
}

.desc-line {
  margin-top: 3px;
  color: #94a3b8;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.path-text {
  font-family: var(--font-mono, Consolas, 'Courier New', monospace);
  font-size: 11.5px;
}

.empty-path {
  color: #94a3b8;
  font-size: 12px;
}

.num {
  color: #334155;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.ops {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: nowrap;
}

.ops :deep(.el-button + .el-button) {
  margin-left: 0;
}

:deep(.cat-table .el-table__cell) {
  vertical-align: middle;
  padding-top: 11px;
  padding-bottom: 11px;
}

:deep(.cat-table .cell) {
  overflow: hidden;
}
</style>
