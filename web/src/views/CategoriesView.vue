<script setup>
import { computed, ref, nextTick } from 'vue'
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
  refreshCategories,
  refreshProjects,
} from '../stores/appState'
import { deleteCategory, openCategoryFolder, reorderCategories } from '../api'
import { toastError } from '../api/http'
import CategoryDialog from '../components/CategoryDialog.vue'

/** 是否正在保存（拖拽松手后回调 reorder）：期间禁用拖拽防重入。 */
const saving = ref(false)
/** 当前正在拖拽的节点 id：用于源节点半透明高亮。 */
const draggingId = ref(null)

const dialogRef = ref(null)

/** 全部分类 id：用于 el-tree 默认展开全部节点（回滚刷新后仍能保持展开）。 */
const allIds = computed(() => (appState.categories || []).map((c) => c.id))

/** 层级：1=一级分类，2=二级分类 ...（node.level 从 1 开始） */
function levelLabel(level) {
  const n = Number(level) || 1
  const cn = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
  if (n <= cn.length) return `${cn[n - 1]}级分类`
  return `${n}级分类`
}

function levelTagType(node) {
  // node: el-tree Node；末级（可挂项目）用 success，其它层级用 info/primary 区分
  if (node?.data?.is_leaf) return 'success'
  if (node?.level === 1) return 'primary'
  return 'info'
}

function openCreate() {
  dialogRef.value?.open()
}

function openEdit(data) {
  dialogRef.value?.open(data)
}

function openAddChild(data) {
  dialogRef.value?.open(null, data.id)
}

async function onOpenFolder(data) {
  try {
    await openCategoryFolder(data.id)
    ElMessage.success('已请求打开本地目录')
  } catch (e) {
    toastError(e)
  }
}

async function onDelete(data) {
  if ((data.child_count || 0) > 0) {
    ElMessage.error('请先删除子分类')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除分类「${data.path_label || data.name}」？\n其下项目也会被删除。`,
      '删除确认',
      { type: 'warning' },
    )
    await deleteCategory(data.id)
    ElMessage.success('分类已删除')
    if (appState.selectedCategoryId === data.id) appState.selectedCategoryId = null
    await Promise.all([refreshCategories(), refreshProjects()])
  } catch (e) {
    if (e !== 'cancel') toastError(e)
  }
}

// ---------- 拖拽排序 ----------

let lastWarnAt = 0
/** 对“最近一次非法 hover”做节流（≥1s），避免 dragover 刷屏。 */
function maybeWarnIllegralDrop() {
  const now = Date.now()
  if (now - lastWarnAt > 1000) {
    lastWarnAt = now
    ElMessage.warning('只能在同一父分类下、同级之间调整顺序')
  }
}

/**
 * 仅允许同父同级兄弟之间重排：
 * - type==='inner'（拖成他人子节点 = 跨层级）→ 拦截；
 * - 拖拽节点与落点节点的父级不同（跨父级）→ 拦截。
 * 返回 false 时 el-tree 不响应 drop，松手自动回弹（内置 not-allowed 光标）。
 */
function allowDrop(draggingNode, dropNode, type) {
  if (type === 'inner') {
    maybeWarnIllegralDrop()
    return false
  }
  const dp = draggingNode.parent?.key ?? null
  const tp = dropNode.parent?.key ?? null
  if (dp !== tp) {
    maybeWarnIllegralDrop()
    return false
  }
  return true
}

function onDragStart(draggingNode) {
  draggingId.value = draggingNode?.key ?? null
}

function onDragEnd() {
  draggingId.value = null
}

/**
 * 松手于合法位置：el-tree 已就地移动节点（子树整体随动，乐观更新）。
 * 读取新兄弟顺序 → 调用 reorder；失败则提示并 refreshCategories() 回滚。
 */
async function onNodeDrop(draggingNode) {
  if (saving.value) return
  // 等 el-tree 内部完成节点移动，确保接下来读到的兄弟顺序是最新的（修复 childNodes 时序问题）
  await nextTick()
  const parentNode = draggingNode?.parent
  if (!parentNode) return
  const parentKey = parentNode.key ?? null
  const orderedIds = (parentNode.childNodes || [])
    .map((n) => n.data?.id)
    .filter(Boolean)
  if (orderedIds.length < 2) return // 单个或无子节点无需排序
  saving.value = true
  try {
    await reorderCategories({ parent_id: parentKey, ordered_ids: orderedIds })
    // 成功后主动同步 appState.categoryTree 到后端真实顺序，
    // 消除"el-tree 乐观更新 vs 前端状态"的脱节，确保后续新建/刷新顺序一致
    await refreshCategories()
  } catch (e) {
    toastError(e)
    await refreshCategories() // 失败回滚到服务端顺序
  } finally {
    saving.value = false
    draggingId.value = null
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
            {{ appState.categories.length }} 个
          </el-tag>
          <el-tag v-if="saving" size="small" effect="plain" round type="warning">
            保存中…
          </el-tag>
        </div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建分类</el-button>
    </div>

    <div class="table-wrap" v-loading="appState.loadingCategories">
      <el-tree
        ref="treeRef"
        class="cat-tree"
        :data="appState.categoryTree"
        node-key="id"
        :props="{ label: 'name', children: 'children' }"
        :draggable="!saving"
        :allow-drop="allowDrop"
        :expand-on-click-node="false"
        :default-expanded-keys="allIds"
        @node-drag-start="onDragStart"
        @node-drag-end="onDragEnd"
        @node-drop="onNodeDrop"
      >
        <template #default="{ node, data }">
          <div class="cat-node" :class="{ 'is-source': draggingId && data.id === draggingId }">
            <el-icon class="type-icon" :class="{ leaf: data.is_leaf }">
              <Document v-if="data.is_leaf" />
              <Folder v-else />
            </el-icon>
            <span class="name-text" :title="data.name">{{ data.name }}</span>
            <el-tag
              size="small"
              :type="levelTagType(node)"
              effect="plain"
              round
              class="level-tag"
            >
              {{ levelLabel(node.level) }}
            </el-tag>
            <span class="cat-meta">
              子类 {{ data.child_count || 0 }} · 项目 {{ data.project_count || 0 }}
            </span>
            <div class="ops">
              <el-tooltip content="添加子分类" :show-after="300">
                <el-button circle :icon="Plus" @click.stop="openAddChild(data)" />
              </el-tooltip>
              <el-tooltip v-if="data.path" content="打开本地目录" :show-after="300">
                <el-button
                  circle
                  :icon="FolderOpened"
                  @click.stop="onOpenFolder(data)"
                />
              </el-tooltip>
              <el-tooltip content="编辑" :show-after="300">
                <el-button
                  circle
                  type="primary"
                  plain
                  :icon="EditPen"
                  @click.stop="openEdit(data)"
                />
              </el-tooltip>
              <el-tooltip content="删除" :show-after="300">
                <el-button
                  circle
                  type="danger"
                  plain
                  :icon="Delete"
                  @click.stop="onDelete(data)"
                />
              </el-tooltip>
            </div>
          </div>
        </template>
      </el-tree>

      <div v-if="!appState.loadingCategories && !(appState.categoryTree || []).length" class="empty-hint">
        还没有分类，点击右上角新建
      </div>
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

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.table-wrap {
  width: 100%;
  min-width: 0;
}

.cat-tree {
  width: 100%;
  background: transparent;
  border: 1px solid var(--el-border-color-lighter, #e5e7eb);
  border-radius: 10px;
  overflow: hidden;
}

/* 每行最小高度 + 行分割线 + 圆角 hover（恢复 el-table 的列表分隔观感） */
.cat-tree :deep(.el-tree-node__content) {
  min-height: 44px;
  height: auto;
  padding: 0 12px;
  border-bottom: 1px solid var(--el-border-color-lighter, #e5e7eb);
  border-radius: 6px;
  transition: background-color 0.15s ease;
}

.cat-tree :deep(.el-tree-node__content):hover {
  background-color: var(--el-fill-color-light, #f1f5f9);
}

/* 末行去掉多余分割线 */
.cat-tree :deep(.el-tree-node:last-child > .el-tree-node__content) {
  border-bottom: none;
}

/* 拖拽经过时不要让内置 inner 高亮干扰视觉（本项目禁止 inner 落点） */
.cat-tree :deep(.el-tree-node.is-drop-inner > .el-tree-node__content) {
  background-color: transparent;
}

.cat-node {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  width: 100%;
  flex: 1;
  padding: 4px 0;
}

.type-icon {
  margin-top: 1px;
  color: #f59e0b;
  flex-shrink: 0;
  font-size: 16px;
}

.type-icon.leaf {
  color: #4f46e5;
}

.name-text {
  font-weight: 650;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
  letter-spacing: 0.01em;
}

.level-tag {
  flex-shrink: 0;
}

.cat-meta {
  color: #94a3b8;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.ops {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: nowrap;
  margin-left: auto;
  flex-shrink: 0;
}

.ops :deep(.el-button + .el-button) {
  margin-left: 0;
}

.empty-hint {
  padding: 28px 0;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}

/* 拖拽中源节点半透明（.el-tree.is-dragging 由组件在拖拽期自动加在根） */
.cat-tree.is-dragging .cat-node.is-source {
  opacity: 0.45;
}

/* 插入指示线加粗主色（Element Plus 内置 .el-tree__drop-indicator，仅合法 prev/next 出现） */
.cat-tree :deep(.el-tree__drop-indicator) {
  background-color: var(--el-color-primary);
  height: 2px;
}

/* 非法位置禁止态：Element Plus 内置 .el-tree.is-dragging.is-drop-not-allow 自动 not-allowed 光标 */
</style>
