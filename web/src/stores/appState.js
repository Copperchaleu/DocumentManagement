import { reactive } from 'vue'
import {
  getHealth,
  getTimeInfo,
  listCategories,
  listProjects,
  listPeriodFiles,
} from '../api'
import { flattenTree } from '../utils/tree'

export const appState = reactive({
  connected: false,
  statusText: '连接中…',
  categories: [],
  categoryTree: [],
  leafCategories: [],
  projects: [],
  periodFiles: [],
  selectedCategoryId: null,
  timeInfo: null,
  keyword: '',
  includeDraft: false,
  loadingCategories: false,
  loadingProjects: false,
  loadingPeriod: false,
})

export async function refreshHealth() {
  try {
    await getHealth()
    appState.connected = true
    appState.statusText = '本地服务已连接'
    return true
  } catch {
    appState.connected = false
    appState.statusText = '服务未连接'
    return false
  }
}

export async function refreshTimeInfo() {
  try {
    appState.timeInfo = await getTimeInfo()
  } catch {
    appState.timeInfo = null
  }
}

export async function refreshCategories() {
  appState.loadingCategories = true
  try {
    const [flat, tree] = await Promise.all([
      listCategories(),
      listCategories({ tree: true }),
    ])
    appState.categories = flat.items || []
    appState.categoryTree = tree.items || []
    appState.leafCategories = (appState.categories || []).filter((c) => c.is_leaf)
  } finally {
    appState.loadingCategories = false
  }
}

export async function refreshProjects(extra = {}) {
  appState.loadingProjects = true
  try {
    const params = {
      include_draft: appState.includeDraft,
      ...extra,
    }
    if (appState.selectedCategoryId) params.category_id = appState.selectedCategoryId
    if (appState.keyword?.trim()) params.keyword = appState.keyword.trim()
    const data = await listProjects(params)
    appState.projects = data.items || []
  } finally {
    appState.loadingProjects = false
  }
}

export async function refreshPeriodFiles() {
  appState.loadingPeriod = true
  try {
    const data = await listPeriodFiles()
    appState.periodFiles = data.items || []
  } finally {
    appState.loadingPeriod = false
  }
}

export async function bootstrapApp() {
  const ok = await refreshHealth()
  if (!ok) return false
  await Promise.all([refreshTimeInfo(), refreshCategories()])
  await Promise.all([refreshProjects(), refreshPeriodFiles()])
  return true
}

export function orderedCategories() {
  // 树前序展开；按 id 去重，防止异常树结构导致前端重复显示
  if (appState.categoryTree?.length) return flattenTree(appState.categoryTree)
  const seen = new Set()
  return (appState.categories || []).filter((c) => {
    if (c?.id == null) return true
    if (seen.has(c.id)) return false
    seen.add(c.id)
    return true
  })
}
