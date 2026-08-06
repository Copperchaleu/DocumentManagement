# 数据看板改造 · 联调验收清单（趋势「按周」 + 分类多级 Treemap）

> 对应设计稿：`docs/dashboard_treemap_week_design.md`
> 联调阶段任务：T04（依赖 T03）。本清单用于前端功能（T03）完成后逐项验证。

## A. 后端接口验证

- [ ] `GET /api/stats/projects-trend?range=week` 返回 `ProjectStatsTrend`，`range=="week"`，`labels` 形如 `YYYY-Www`（ISO 周，共 12 个），`labels` 与 `values` 一一对应升序，无数据周补 0。
- [ ] `range` 取非法值（如 `year`）时回退 `day`（行为与现状一致）。
- [ ] `GET /api/stats/category-tree` 返回 `CategoryTreeResponse`，`items` 为顶级分类；每项 `children` 为**直接子分类**（仅一层），`project_total` = 子树（含自身与后代）`status!='draft'` 项目总数。
- [ ] 空库 / 无分类：`category-tree` 返回 `{"items":[]}`；`projects-trend?range=week` 返回 12 个 0。
- [ ] 周标签口径：与 `path_utils.get_iso_week_range` 产出格式一致（`f"{iso.year}-W{iso.week:02d}"`）。
- [ ] 既有接口（`day/month/quarter`、`category-breakdown`）行为无回归。

## B. 前端趋势「按周」

- [ ] 看板「新增趋势」`el-segmented` 出现「周」选项（顺序：日/周/月/季）。
- [ ] 切到「周」：趋势图渲染最近 12 周，横轴 `YYYY-Www` 标签**未拥挤**（抽稀生效，约 6 个可见）。
- [ ] 切回 日/月/季：原有逻辑与标签显隐正常，无回归。
- [ ] 周模式 0 数据：显示「暂无新增项目数据」空态。

## C. 前端分类多级 Treemap

- [ ] 原自绘 SVG 圆环图（donut + legend）已从「按分类统计」区移除；相关 state（`CAT_COLORS`/`catTotal`/`catSegments`）与 CSS（`.donut*`/`.cat-legend*`）已清理。
- [ ] 替换为 ApexCharts treemap：每个顶级分类为一个分组（series），其直接子分类为嵌套矩形（data）。
- [ ] 颜色：每顶级一基色、子分类同色系深浅（`distributed:false`）；色板为靛蓝主题色。
- [ ] Tooltip 显示「名称 + N 个项目」；dataLabels 显示名称与数量。
- [ ] 无子分类的顶级：渲染为单个独立矩形（自身 `project_total`）。
- [ ] 空态：无分类 → 「暂无分类数据」；有分类但全 0 → 「分类下暂无项目」（无怪异 0 值等面积矩形）。

## D. 依赖与构建

- [ ] `web/package.json` 含 `apexcharts`、`vue3-apexcharts`；`npm install` 成功。
- [ ] `web/src/main.js` 已 `app.use(VueApexCharts)`，控制台无插件注册报错。
- [ ] `web` 前端构建/启动无报错，看板 Tab 正常加载。

## E. 待明确项回填（见设计稿 §7）

- [ ] 周数（默认 12）是否确认。
- [ ] 是否显式展示顶级自身数量（series name 拼接）。
- [ ] 叶子顶级呈现方式（独立矩形 / 隐藏）。
- [ ] 旧 `getCategoryBreakdown`/`category_breakdown` 是否清理。
- [ ] 颜色方案是否需调整。
- [ ] 周趋势（saved）与分类（!draft）口径是否维持原状。
