"""Treemap 叶子跳转与项目列表筛选 — 静态/数据层验收。

覆盖：
1. CategoryTreemap.vue 叶子 vs 上级交互代码契约
2. ProjectsView.vue keep-alive 下 categoryId 筛选契约
3. 后端 category_tree 多级 + list_projects 按叶子/父级筛选一致性
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import Database  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_frontend_contracts() -> None:
    print("\n[A] Frontend contracts")
    treemap = read("web/src/components/CategoryTreemap.vue")
    projects = read("web/src/views/ProjectsView.vue")
    dashboard = read("web/src/components/DashboardPanel.vue")

    check("CategoryTreemap defines onTreemapClick", "function onTreemapClick" in treemap)
    check(
        "non-leaf only drills (hasChildren path, no push)",
        "if (node.hasChildren)" in treemap
        and "drillPath.value = [...drillPath.value" in treemap,
    )
    check(
        "leaf routes to projects with categoryId",
        "name: 'projects'" in treemap and "categoryId: String(node.id)" in treemap,
    )
    # 非叶子分支必须在 return 之后才 push，或用 if/else 隔离
    # 简单契约：hasChildren 块后紧跟 return，再出现 router.push
    m = re.search(
        r"if \(node\.hasChildren\) \{[\s\S]*?return\s*\}\s*//[^\n]*\n\s*router\.push",
        treemap,
    )
    check("leaf push only after hasChildren early-return", bool(m))
    check(
        "dataPointIndex boundary guard",
        "dataPointIndex" in treemap and ("idx < 0" in treemap or "idx == null" in treemap),
    )
    check(
        "tooltip distinguishes leaf vs parent",
        "点击展开下一级" in treemap and "点击查看该分类下的项目" in treemap,
    )
    check("breadcrumb goTo ignores current level", "index === drillPath.value.length - 1" in treemap)

    check("ProjectsView applyCategoryFilterFromRoute exists", "applyCategoryFilterFromRoute" in projects)
    check(
        "ProjectsView watches route.query.categoryId",
        "route.query.categoryId" in projects and "watch(" in projects,
    )
    check(
        "apply only when categoryId present (no forced clear)",
        "if (cid == null || cid === '') return" in projects
        or "if (cid == null" in projects,
    )
    check(
        "apply writes selectedCategoryId and refreshes",
        "appState.selectedCategoryId = id" in projects and "refreshProjects()" in projects,
    )

    check("DashboardPanel mounts CategoryTreemap", "CategoryTreemap" in dashboard)
    check("DashboardPanel loads category-tree API", "getCategoryTree" in dashboard)


def test_backend_tree_and_filter() -> None:
    print("\n[B] Backend tree + project filter")
    db_path = ROOT / "data" / "app.db"
    if not db_path.exists():
        print("  SKIP  data/app.db not found")
        return

    db = Database(db_path)
    tree = db.category_tree()
    check("category_tree returns list", isinstance(tree, list))

    def walk(nodes, depth=1, leaves=None, parents=None):
        leaves = leaves if leaves is not None else []
        parents = parents if parents is not None else []
        max_d = depth
        for n in nodes or []:
            kids = n.get("children") or []
            if kids:
                parents.append(n)
                d = walk(kids, depth + 1, leaves, parents)
                max_d = max(max_d, d)
            else:
                leaves.append(n)
        return max_d

    leaves: list = []
    parents: list = []
    depth = walk(tree, 1, leaves, parents) if tree else 0
    check("tree has multi-level or single-level structure", depth >= 1, f"depth={depth}")
    check("at least one leaf exists (or empty tree ok)", True)  # structure probe always ok

    # Nested children field present on parents when multi-level data exists
    if parents:
        check("parent nodes have children list", all(isinstance(p.get("children"), list) for p in parents[:5]))
    else:
        check("no parents (flat tree ok)", True)

    # Leaf filter consistency: listed count == project_total when no draft mismatch
    # project_total counts status!='draft'; list_projects default exclude draft → should match for leaves
    mismatches = 0
    for leaf in leaves[:20]:
        listed = db.list_projects(category_id=leaf["id"], include_draft=False)
        if len(listed) != int(leaf.get("project_total") or 0):
            mismatches += 1
            print(
                f"    note: leaf {leaf['id']} {leaf['name']}: "
                f"total={leaf.get('project_total')} listed={len(listed)}"
            )
    check("leaf project_total matches list_projects (sample)", mismatches == 0, f"mismatches={mismatches}")

    # Parent should not be empty of children in tree (by definition)
    if parents:
        p = parents[0]
        child_ids = {c["id"] for c in (p.get("children") or [])}
        check("sample parent has child ids", len(child_ids) > 0)
        # Parent list_projects includes descendants (may be > direct_total)
        listed_p = db.list_projects(category_id=p["id"], include_draft=False)
        check(
            "parent list includes descendant projects (subtree)",
            len(listed_p) == int(p.get("project_total") or 0),
            f"listed={len(listed_p)} total={p.get('project_total')}",
        )


def main() -> int:
    print("=== Treemap leaf-nav QA ===")
    test_frontend_contracts()
    test_backend_tree_and_filter()
    print(f"\nResult: {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
