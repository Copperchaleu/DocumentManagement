export function flattenTree(nodes, result = [], seen = new Set()) {
  for (const n of nodes || []) {
    // 按 id 去重，避免树数据异常时同一分类重复入列表
    if (n?.id != null) {
      if (seen.has(n.id)) continue
      seen.add(n.id)
    }
    // 去掉 children，避免 el-table 因 row-key + children 自动进入树形展开，
    // 导致末级分类既作为子行展开出现，又出现在扁平列表中（看起来重复）
    const { children, ...rest } = n || {}
    result.push(rest)
    if (children?.length) flattenTree(children, result, seen)
  }
  return result
}

export function toTreeSelectOptions(nodes, excludeId = null) {
  const walk = (list) =>
    (list || [])
      .filter((n) => n.id !== excludeId)
      .map((n) => ({
        value: n.id,
        label: n.path_label || n.name,
        children: n.children?.length ? walk(n.children) : undefined,
      }))
  return walk(nodes)
}

/**
 * Build data for <el-tree-select> .
 * - value/label/children standard
 * - carries is_leaf for disabling non-leaves when needed
 * - onlyLeafSelectable=true 时，非叶子节点 disabled
 */
export function buildCategoryTreeSelectData(nodes, { onlyLeafSelectable = false } = {}) {
  const walk = (list) =>
    (list || []).map((n) => {
      const isLeaf = !!n.is_leaf
      const item = {
        value: n.id,
        label: n.path_label || n.name,
        is_leaf: isLeaf,
        disabled: onlyLeafSelectable ? !isLeaf : false,
        children: n.children?.length ? walk(n.children) : undefined,
      }
      return item
    })
  return walk(nodes)
}

/** 给定分类 id，返回该节点及其所有后代叶子节点的 id 集合（用于前端子树过滤） */
export function getLeafDescendantIds(targetId, flatList) {
  if (!targetId) return new Set()
  const idToNode = new Map()
  for (const c of flatList || []) idToNode.set(c.id, c)

  const result = new Set()
  function walk(cid) {
    const node = idToNode.get(cid)
    if (!node) return
    if (node.is_leaf) result.add(cid)
    const children = (flatList || []).filter((c) => c.parent_id === cid)
    for (const ch of children) walk(ch.id)
  }
  walk(targetId)
  return result
}

export function toElTreeData(nodes) {
  const walk = (list) => {
    if (!list || !list.length) return []
    return list.map((n) => {
      const children = n.children?.length ? walk(n.children) : undefined
      const own = Number(n.project_count) || 0
      const childrenSum = children
        ? children.reduce((s, c) => s + (Number(c.project_count) || 0), 0)
        : 0
      return {
        id: n.id,
        label: n.name,
        is_leaf: n.is_leaf,
        project_count: own + childrenSum,
        path_label: n.path_label,
        raw: n,
        children,
      }
    })
  }
  return walk(nodes)
}

/**
 * el-cascader options：每级用 name 展示，保留 is_leaf
 * expandTrigger=hover 由组件 props 控制
 */
export function toCascaderOptions(nodes) {
  const walk = (list) =>
    (list || []).map((n) => {
      const hasChildren = !!(n.children && n.children.length)
      return {
        value: n.id,
        label: n.name,
        is_leaf: n.is_leaf ?? !hasChildren,
        children: hasChildren ? walk(n.children) : undefined,
      }
    })
  return walk(nodes)
}

/** 分类 id → 从根到该节点的 value 路径数组（供 cascader v-model 回显） */
export function getCategoryValuePath(categoryId, tree) {
  if (categoryId == null) return []
  const target = Number(categoryId)
  function walk(list, path) {
    for (const n of list || []) {
      const next = [...path, n.id]
      if (Number(n.id) === target) return next
      if (n.children?.length) {
        const found = walk(n.children, next)
        if (found) return found
      }
    }
    return null
  }
  return walk(tree, []) || []
}

/** cascader 选中值（数组或单值）→ 当前节点 id */
export function cascaderValueToId(val) {
  if (val == null || val === '') return null
  if (Array.isArray(val)) {
    if (!val.length) return null
    return val[val.length - 1] ?? null
  }
  return val
}

/** 节点及其所有后代 id（含自身），用于中间级筛选「含子分类」 */
export function getDescendantIdsIncludingSelf(targetId, flatList) {
  if (targetId == null) return new Set()
  const tid = Number(targetId)
  const childrenMap = new Map()
  for (const c of flatList || []) {
    const pid = c.parent_id == null ? null : Number(c.parent_id)
    if (!childrenMap.has(pid)) childrenMap.set(pid, [])
    childrenMap.get(pid).push(Number(c.id))
  }
  const result = new Set()
  function walk(cid) {
    result.add(cid)
    for (const child of childrenMap.get(cid) || []) walk(child)
  }
  walk(tid)
  return result
}

export function makeSaveToken() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}
