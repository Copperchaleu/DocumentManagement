<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Search, Fold, Expand } from '@element-plus/icons-vue'
import {
  appState,
  bootstrapApp,
  refreshCategories,
  refreshProjects,
} from '../stores/appState'
import { toElTreeData } from '../utils/tree'
import CategoryDialog from '../components/CategoryDialog.vue'

const route = useRoute()
const router = useRouter()
const categoryDialogRef = ref(null)
const keyword = computed({
  get: () => appState.keyword,
  set: (v) => {
    appState.keyword = v
  },
})

const treeData = computed(() => toElTreeData(appState.categoryTree))
const defaultExpandedCategoryIds = computed(() => {
  const ids = []

  function collect(nodes, depth = 1) {
    for (const node of nodes || []) {
      // 展开上一层以显示第二级；第二级自身保持收起，隐藏更深层级。
      if (depth < 2 && node.children?.length) ids.push(node.id)
      if (depth < 2 && node.children?.length) collect(node.children, depth + 1)
    }
  }

  collect(treeData.value)
  return ids
})
const activeTab = computed(() => route.name || 'compose')
let createRequestSequence = 0

// 左侧边栏折叠状态（默认展开）
const sidebarCollapsed = ref(false)

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try {
    localStorage.setItem('sidebarCollapsed', sidebarCollapsed.value ? '1' : '0')
  } catch {}
}

// 页面加载恢复偏好
try {
  const saved = localStorage.getItem('sidebarCollapsed')
  if (saved === '1') sidebarCollapsed.value = true
} catch {}

const tabs = [
  { name: 'workbench', label: '工作面板' },
  { name: 'compose', label: '项目编辑' },
  { name: 'projects', label: '项目列表' },
  { name: 'period', label: '周期文件' },
  { name: 'categories', label: '分类管理' },
  { name: 'settings', label: '系统设置' },
]

const weekHint = computed(() => {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  const today = `${y}-${m}-${d}`
  const week = appState.timeInfo?.week
  if (!week) return `今天 ${today}`
  return `今天 ${today} · 第${week.iso_week}周`
})

function onTabChange(name) {
  router.push({ name })
}

function onTreeClick(data) {
  appState.selectedCategoryId = data.id
  createRequestSequence += 1
  router.push({
    name: 'compose',
    query: {
      category: String(data.id),
      create: `${Date.now()}-${createRequestSequence}`,
    },
  })
}

function openCreateCategory() {
  categoryDialogRef.value?.open()
}

function onSearch() {
  router.push({ name: 'projects' })
  refreshProjects()
}

onMounted(async () => {
  const ok = await bootstrapApp()
  if (!ok) {
    ElMessage.error('无法连接本地服务，请确认已运行当前平台的启动脚本')
  }
})
</script>

<template>
  <div class="app-layout" :class="{ 'is-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <div
        class="brand"
        :class="{ compact: sidebarCollapsed }"
        @click="sidebarCollapsed && toggleSidebar()"
      >
        <div class="brand-mark">文</div>
        <template v-if="!sidebarCollapsed">
          <div class="brand-meta">
            <div class="brand-title">本地文档库</div>
            <div class="brand-sub">本地 · 分类 · 周期归档</div>
          </div>
        </template>
      </div>

      <div class="side-section">
        <div class="side-head">
          <span v-if="!sidebarCollapsed">分类树</span>
          <div class="side-head-actions">
            <el-button
              v-if="!sidebarCollapsed"
              :icon="Plus"
              circle
              title="新建分类"
              @click="openCreateCategory"
            />
            <el-button
              :icon="sidebarCollapsed ? Expand : Fold"
              circle
              :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
              @click="toggleSidebar"
            />
          </div>
        </div>

        <template v-if="!sidebarCollapsed">
          <el-tree
            class="sidebar-tree"
            :data="treeData"
            node-key="id"
            highlight-current
            :default-expanded-keys="defaultExpandedCategoryIds"
            :expand-on-click-node="false"
            :current-node-key="appState.selectedCategoryId"
            empty-text="暂无分类"
            @node-click="onTreeClick"
          >
            <template #default="{ data }">
              <div class="tree-node-row">
                <span class="tree-node-label">
                  <span class="tree-emoji">{{ data.is_leaf ? '📄' : '📁' }}</span>
                  <span class="tree-text" :title="data.label">{{ data.label }}</span>
                </span>
                <span class="tree-count">{{ data.project_count || 0 }}</span>
              </div>
            </template>
          </el-tree>
        </template>

        <div
          v-else
          class="sidebar-collapsed-hint"
          title="展开分类树"
          @click="toggleSidebar"
        >
          <div class="collapsed-icon">📁</div>
          <div class="collapsed-label">分类</div>
        </div>
      </div>

      <div class="side-footer">
        <div
          class="status-dot"
          :class="{ ok: appState.connected, err: !appState.connected }"
        />
        <span class="status-text">{{ appState.statusText }}</span>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-nav">
          <el-segmented
            :model-value="activeTab"
            :options="tabs.map((t) => ({ label: t.label, value: t.name }))"
            @change="onTabChange"
          />
        </div>
        <div class="topbar-week">
          <span class="week-dot" />
          <span>{{ weekHint }}</span>
        </div>
        <el-input
          v-model="keyword"
          clearable
          class="topbar-search"
          placeholder="搜索项目标题或内容…"
          :prefix-icon="Search"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
      </header>

      <div class="page">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </main>

    <CategoryDialog ref="categoryDialogRef" @saved="refreshCategories" />
  </div>
</template>

<style scoped>
.brand-meta {
  min-width: 0;
}

.tree-node-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 8px;
  padding-right: 6px;
  font-size: 13px;
  min-width: 0;
}

.tree-node-label {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.tree-emoji {
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1;
  opacity: 0.95;
}

.tree-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.tree-count {
  font-size: 11px;
  color: #cbd5e1;
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 7px;
  border-radius: 999px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  min-width: 22px;
  text-align: center;
  line-height: 1.5;
}

.status-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-nav {
  min-width: 0;
}

.topbar-week {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(79, 70, 229, 0.08);
  border: 1px solid rgba(79, 70, 229, 0.18);
  color: #3730a3;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.topbar-week .week-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4f46e5;
  flex-shrink: 0;
}

.topbar-search {
  max-width: 340px;
  width: 100%;
}

.topbar-search :deep(.el-input__wrapper) {
  border-radius: 999px !important;
  background: #f8fafc !important;
  padding-left: 14px;
  padding-right: 12px;
}

@media (max-width: 960px) {
  .topbar-search {
    max-width: none;
  }
}
</style>
