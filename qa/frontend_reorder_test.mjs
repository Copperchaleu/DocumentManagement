#!/usr/bin/env node
// 前端拖拽逻辑单测 + CategoriesView.vue 静态走查。
// 使用受管 node（纯 JS，无需框架）。覆盖：
//   1) allowDrop 核心判定（跨层级/跨父级拦截，同父/根级允许）
//   2) 兄弟顺序计算（onNodeDrop 口径，与后端全覆盖校验一致）
//   3) CategoriesView.vue 静态走查（el-tree 绑定、@click.stop、回滚、无遗留 el-table/row.）

import assert from 'node:assert'
import fs from 'node:fs'

const VUE_PATH = '/Users/graypaul/Projects/DocumentManagement/web/src/views/CategoriesView.vue'

let pass = 0
let fail = 0
const lines = []

function check(name, fn) {
  try {
    fn()
    pass++
    lines.push('[PASS] ' + name)
  } catch (e) {
    fail++
    lines.push('[FAIL] ' + name + ' :: ' + e.message)
  }
}

// ---- 复刻 CategoriesView.vue 的 allowDrop 核心判定（纯函数）----
function allowDrop(draggingNode, dropNode, type) {
  if (type === 'inner') return false
  const dp = draggingNode.parent?.key ?? null
  const tp = dropNode.parent?.key ?? null
  if (dp !== tp) return false
  return true
}

// 1. type==='inner' -> false（跨层级拦截）
check('allowDrop inner 拦截', () => {
  assert.strictEqual(allowDrop({ parent: { key: 1 } }, { parent: { key: 1 } }, 'inner'), false)
  assert.strictEqual(allowDrop({ parent: { key: null } }, { parent: { key: null } }, 'inner'), false)
})

// 2. 跨父级 (dragging.parent.key=1, drop.parent.key=2) -> false
check('allowDrop 跨父级 拦截', () => {
  assert.strictEqual(allowDrop({ parent: { key: 1 } }, { parent: { key: 2 } }, 'prev'), false)
  assert.strictEqual(allowDrop({ parent: { key: 1 } }, { parent: { key: 2 } }, 'next'), false)
})

// 3. 同父（都为 1）prev/next -> true
check('allowDrop 同父 允许', () => {
  assert.strictEqual(allowDrop({ parent: { key: 1 } }, { parent: { key: 1 } }, 'prev'), true)
  assert.strictEqual(allowDrop({ parent: { key: 1 } }, { parent: { key: 1 } }, 'next'), true)
})

// 4. 根级（都为 null/undefined）-> true
check('allowDrop 根级 允许', () => {
  assert.strictEqual(allowDrop({ parent: { key: null } }, { parent: { key: null } }, 'prev'), true)
  assert.strictEqual(allowDrop({ parent: {} }, { parent: {} }, 'prev'), true)
  assert.strictEqual(allowDrop({}, {}, 'next'), true)
})

// ---- 兄弟顺序计算（onNodeDrop 口径）----
// 与 CategoriesView.collectSiblingIds 一致：优先 childNodes，兜底 data/children
function collectSiblingIds(parentNode) {
  if (!parentNode) return []
  const fromNodes = (parentNode.childNodes || [])
    .map((n) => n.data?.id)
    .filter((id) => id != null)
  if (fromNodes.length) return fromNodes
  const dataKids = Array.isArray(parentNode.data)
    ? parentNode.data
    : parentNode.data?.children
  return (dataKids || []).map((d) => d?.id).filter((id) => id != null)
}

check('兄弟顺序计算 orderedIds=[3,1,2]', () => {
  const parentNode = { childNodes: [{ data: { id: 3 } }, { data: { id: 1 } }, { data: { id: 2 } }] }
  const orderedIds = collectSiblingIds(parentNode)
  assert.deepStrictEqual(orderedIds, [3, 1, 2])
  // 与后端全覆盖校验口径一致：given 集合 == sibling 集合
  const siblingSet = new Set([1, 2, 3])
  const given = new Set(orderedIds)
  assert.strictEqual(given.size, siblingSet.size)
  assert.ok([...siblingSet].every((id) => given.has(id)))
})

// Element Plus 关键行为：drop 后 draggingNode.parent 被置 null，必须用 dropNode.parent
check('onNodeDrop 必须用 dropNode.parent（draggingNode.parent 已 null）', () => {
  const sharedParent = {
    key: null,
    childNodes: [{ data: { id: 3 } }, { data: { id: 1 } }, { data: { id: 2 } }],
  }
  const draggingNode = { parent: null, data: { id: 1 } } // remove() 后 parent 被清空
  const dropNode = { parent: sharedParent, data: { id: 3 } }
  // 错误写法：读 draggingNode.parent → 直接跳过保存
  assert.strictEqual(draggingNode.parent, null, '模拟 EP remove 后 parent=null')
  // 正确写法：读 dropNode.parent
  const orderedIds = collectSiblingIds(dropNode.parent)
  assert.deepStrictEqual(orderedIds, [3, 1, 2])
})

check('collectSiblingIds 兜底 data 数组（根级）', () => {
  const rootParent = {
    key: undefined,
    childNodes: [],
    data: [{ id: 9 }, { id: 7 }, { id: 8 }],
  }
  assert.deepStrictEqual(collectSiblingIds(rootParent), [9, 7, 8])
})

// ---- CategoriesView.vue 静态走查 ----
let vue = ''
try {
  vue = fs.readFileSync(VUE_PATH, 'utf8')
} catch (e) {
  check('读取 CategoriesView.vue', () => { throw new Error(e.message) })
}

if (vue) {
  check('静态- el-tree 绑定 categoryTree + node-key=id', () => {
    assert.ok(vue.includes(':data="appState.categoryTree"'), '缺少 :data="appState.categoryTree"')
    assert.ok(vue.includes('node-key="id"'), '缺少 node-key="id"')
  })
  check('静态- allow-drop + draggable=!saving', () => {
    assert.ok(vue.includes(':allow-drop="allowDrop"'), '缺少 :allow-drop="allowDrop"')
    assert.ok(vue.includes(':draggable="!saving"'), '缺少 :draggable="!saving"')
  })
  check('静态- 节点插槽四枚按钮均 @click.stop', () => {
    const stops = (vue.match(/@click\.stop/g) || []).length
    assert.ok(stops >= 4, `仅找到 ${stops} 处 @click.stop，期望 >=4`)
  })
  check('静态- 失败回滚 toastError(e)+refreshCategories(), saving 在 finally 复位', () => {
    assert.ok(vue.includes('toastError(e)'), '缺少 toastError(e)')
    assert.ok(vue.includes('await refreshCategories()'), '缺少 await refreshCategories()')
    assert.ok(vue.includes('saving.value = false'), '缺少 saving.value = false 复位')
  })
  check('静态- onNodeDrop 用 dropNode.parent + collectSiblingIds，避免 draggingNode.parent=null', () => {
    assert.ok(vue.includes('function collectSiblingIds'), '缺少 collectSiblingIds')
    assert.ok(
      /async function onNodeDrop\s*\(\s*draggingNode\s*,\s*dropNode/.test(vue),
      'onNodeDrop 未接收 dropNode 参数',
    )
    assert.ok(vue.includes('const parentNode = dropNode.parent'), '未用 dropNode.parent 读兄弟')
    assert.ok(!/const parentNode = draggingNode\?\.parent/.test(vue), '仍在用 draggingNode.parent（会永久丢序）')
    assert.ok(vue.includes('await nextTick()'), '缺少 await nextTick()')
  })
  // 去除 CSS/HTML 注释后再做“遗留组件”检查：
  // 避免设计意图说明（如 CSS 注释里提到 el-table 观感）被当成遗留组件误报。
  const vueClean = vue
    .replace(/\/\*[\s\S]*?\*\//g, '') // 去 CSS 注释
    .replace(/<!--[\s\S]*?-->/g, '') // 去 HTML 注释
  check('静态- 无遗留 el-table / tableData / row.', () => {
    assert.ok(!/el-table/.test(vueClean), '仍存在 el-table 引用')
    assert.ok(!/tableData/.test(vueClean), '仍存在 tableData 引用')
    assert.ok(!/\brow\./.test(vueClean), '仍存在 row. 引用')
  })
}

console.log(lines.join('\n'))
console.log(`\n=== FRONTEND SUMMARY: PASS=${pass} FAIL=${fail} ===`)
process.exit(fail ? 1 : 0)
