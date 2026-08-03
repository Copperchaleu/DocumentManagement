/* 本地文档管理系统 v2 - 多级分类 + 项目 + 周期合并 + 定时保存 */

const state = {
  categories: [],
  categoryTree: [],
  leafCategories: [],
  projects: [],
  periodFiles: [],
  selectedCategoryId: null,
  pendingFiles: [],
  activeView: "compose",
  timeInfo: null,
  pathPickedManually: false,
  draftProjectId: null,
  autosaveTimer: null,
  autosaveBusy: false,
  lastAutosaveAt: null,
  dirty: false,
  editingProjectId: null,
  saveBusy: false,
  // 同一编辑会话令牌：失败重试时复用，避免重复创建项目
  clientSaveToken: makeSaveToken(),
};

function makeSaveToken() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---------- API ----------

function extractErrorMessage(data, status) {
  if (!data) {
    if (status === 423) return "Word 文件正在被打开，请先关闭后再保存";
    if (status >= 500) return "服务器内部错误，请稍后重试";
    return `请求失败 ${status || ""}`.trim();
  }
  if (typeof data === "string") {
    // 纯文本 HTML 的 Internal Server Error 也归并
    if (/internal server error/i.test(data)) {
      return "服务器内部错误。若刚打开了 Word，请先关闭对应 Word 文件后再保存。";
    }
    return data;
  }
  const detail = data.detail ?? data.message ?? data.error;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((x) => (typeof x === "string" ? x : x.msg || JSON.stringify(x)))
      .join("；");
  }
  if (detail && typeof detail === "object") {
    return detail.msg || detail.message || JSON.stringify(detail);
  }
  try {
    return JSON.stringify(data);
  } catch {
    return `请求失败 ${status || ""}`.trim();
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const msg = extractErrorMessage(data, res.status);
    const err = new Error(msg);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

// ---------- UI helpers ----------

function toast(message, type = "ok", timeout = 4500) {
  const area = $("#toastArea");
  if (!area) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  area.prepend(el);
  if (timeout > 0) setTimeout(() => el.remove(), timeout);
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function currentTimeModes() {
  return $$("#timeModes input:checked").map((el) => el.value);
}

function markDirty() {
  state.dirty = true;
  updateAutosaveStatus();
}

function updateTimeHint() {
  const modes = currentTimeModes();
  const labels = state.timeInfo?.labels;
  const week = state.timeInfo?.week;
  const weekLabel = labels?.week || week?.label || "";
  const monthLabel = labels?.month || "";
  const quarterLabel = labels?.quarter || "";

  const parts = [];
  if (modes.includes("week") && weekLabel) parts.push(`by_week/${weekLabel}/汇总.docx`);
  if (modes.includes("month") && monthLabel) parts.push(`by_month/${monthLabel}/汇总.docx`);
  if (modes.includes("quarter") && quarterLabel) parts.push(`by_quarter/${quarterLabel}/汇总.docx`);

  $("#timeHint").textContent = parts.length
    ? `本分类本周期所有项目将合并写入：${parts.join("  +  ")}`
    : "请至少选择一个时间周期";

  const ruleEl = $("#weekRuleHint");
  if (ruleEl) {
    if (week) {
      ruleEl.textContent =
        `按周规则：ISO 周，周一至周日（本周 ${week.label}：${week.start} ~ ${week.end}）`;
    } else {
      ruleEl.textContent = "按周规则：ISO 周，周一至周日";
    }
  }
}

async function loadTimeInfo() {
  try {
    state.timeInfo = await api("/api/time-info");
    const sec = state.timeInfo?.autosave_seconds;
    if (sec && $("#autosaveSeconds")) {
      const opt = [...$("#autosaveSeconds").options].find((o) => o.value === String(sec));
      if (opt) $("#autosaveSeconds").value = String(sec);
    }
  } catch {
    state.timeInfo = null;
  }
  updateTimeHint();
}

function switchView(name) {
  state.activeView = name;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  if (name === "projects") loadProjects();
  if (name === "period") loadPeriodFiles();
  if (name === "categories") renderCategoryCards();
  if (name === "compose") restartAutosaveTimer();
}

// ---------- Categories ----------

async function loadCategories() {
  const [flat, tree] = await Promise.all([
    api("/api/categories"),
    api("/api/categories?tree=true"),
  ]);
  state.categories = flat.items || [];
  state.categoryTree = tree.items || [];
  state.leafCategories = state.categories.filter((c) => c.is_leaf);
  renderCategoryList();
  renderCategorySelects();
  renderCategoryCards();
  renderParentSelect();
}

function renderTreeNodes(nodes, depth = 0) {
  return (nodes || [])
    .map((c) => {
      const active = state.selectedCategoryId === c.id ? "active" : "";
      const kind = c.is_leaf ? "leaf" : "folder";
      const count = c.project_count || 0;
      const childrenHtml = renderTreeNodes(c.children || [], depth + 1);
      return `
        <div class="cat-tree-node">
          <button class="cat-item ${kind} ${active}" data-id="${c.id}" style="--depth:${depth}">
            <span class="name" title="${escapeHtml(c.path_label || c.name)}">${escapeHtml(c.name)}</span>
            <span class="count">${count}</span>
          </button>
          ${childrenHtml}
        </div>`;
    })
    .join("");
}

function renderCategoryList() {
  const box = $("#categoryList");
  if (!state.categoryTree.length) {
    box.innerHTML = `<div style="padding:12px;color:#94a3b8;font-size:13px;">暂无分类，点击右上角 ＋ 创建</div>`;
    return;
  }
  box.innerHTML = renderTreeNodes(state.categoryTree);
  $$(".cat-item", box).forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.id);
      state.selectedCategoryId = id;
      const cat = state.categories.find((x) => x.id === id);
      if (cat?.is_leaf) {
        $("#docCategory").value = String(id);
      }
      $("#filterCategory").value = String(id);
      renderCategoryList();
      switchView("projects");
      loadProjects();
    });
  });
}

function renderCategorySelects() {
  // 仅叶子分类可选作项目归属
  const leafOptions = state.leafCategories
    .map(
      (c) =>
        `<option value="${c.id}">${escapeHtml(c.path_label || c.name)}</option>`
    )
    .join("");
  $("#docCategory").innerHTML =
    leafOptions || `<option value="">请先创建叶子分类</option>`;

  // 过滤器：全部 + 所有分类
  const allOptions = state.categories
    .map(
      (c) =>
        `<option value="${c.id}">${escapeHtml(c.path_label || c.name)}${c.is_leaf ? "" : "（目录）"}</option>`
    )
    .join("");
  $("#filterCategory").innerHTML = `<option value="">全部分类</option>` + allOptions;

  if (state.selectedCategoryId) {
    const selLeaf = state.leafCategories.find((c) => c.id === state.selectedCategoryId);
    if (selLeaf) $("#docCategory").value = String(state.selectedCategoryId);
    $("#filterCategory").value = String(state.selectedCategoryId);
  } else if (state.leafCategories[0]) {
    $("#docCategory").value = String(state.leafCategories[0].id);
  }
}

function renderParentSelect(excludeId = null) {
  const opts = [`<option value="">（无，作为顶级）</option>`];
  for (const c of state.categories) {
    if (excludeId && c.id === excludeId) continue;
    // 简单排除：不能选自己；深层环由后端校验
    opts.push(
      `<option value="${c.id}">${escapeHtml(c.path_label || c.name)}</option>`
    );
  }
  $("#catParent").innerHTML = opts.join("");
}

function orderedCategoriesForList() {
  // 按树前序输出，保证父级在子级前，列表层级可读
  const result = [];
  const walk = (nodes) => {
    for (const n of nodes || []) {
      result.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  if (state.categoryTree?.length) {
    walk(state.categoryTree);
    return result;
  }
  return state.categories || [];
}

function renderCategoryCards() {
  // 兼容旧函数名：现为列表渲染
  const tbody = $("#catTableBody");
  if (!tbody) return;

  const list = orderedCategoriesForList();
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">还没有分类。点击右上角新建。</td></tr>`;
    return;
  }

  tbody.innerHTML = list
    .map((c) => {
      const depth = Math.max(0, (c.path_names?.length || 1) - 1);
      const indent = "&nbsp;".repeat(depth * 4);
      const typeBadge = c.is_leaf
        ? `<span class="badge saved">叶子</span>`
        : `<span class="badge">目录</span>`;
      const localPath = c.resolved_path || c.path || "";
      const pathHtml = localPath
        ? `<span class="path-cell" title="${escapeHtml(localPath)}">${escapeHtml(localPath)}</span>`
        : `<span class="hint">未设置</span>`;
      return `
        <tr data-id="${c.id}">
          <td>
            <div class="cat-name-cell" style="padding-left:${depth * 16}px">
              <span class="cat-tree-line">${indent}</span>
              <strong>${c.is_leaf ? "📄" : "📁"} ${escapeHtml(c.name)}</strong>
              ${c.description ? `<div class="hint">${escapeHtml(c.description)}</div>` : ""}
            </div>
          </td>
          <td>${typeBadge}</td>
          <td><span class="path-cell" title="${escapeHtml(c.path_label || c.name)}">${escapeHtml(c.path_label || c.name)}</span></td>
          <td>${pathHtml}</td>
          <td>${c.child_count || 0}</td>
          <td>${c.project_count || 0}</td>
          <td>
            <div class="ops">
              <button class="btn sm ghost" data-act="add-child" data-id="${c.id}">加子类</button>
              ${localPath ? `<button class="btn sm ghost" data-act="open" data-id="${c.id}">打开</button>` : ""}
              <button class="btn sm ghost" data-act="edit" data-id="${c.id}">编辑</button>
              <button class="btn sm danger" data-act="del" data-id="${c.id}">删除</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");

  $$("[data-act]", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      const cat = state.categories.find((x) => x.id === id);
      if (!cat) return;
      if (act === "edit") openCategoryDialog(cat);
      if (act === "add-child") openCategoryDialog(null, id);
      if (act === "open") {
        try {
          await api(`/api/categories/${id}/open-folder`, { method: "POST" });
          toast("已请求打开本地目录", "info");
        } catch (e) {
          toast(e.message, "err");
        }
      }
      if (act === "del") {
        if ((cat.child_count || 0) > 0) {
          toast("请先删除子分类", "err");
          return;
        }
        if (!confirm(`确认删除分类「${cat.path_label || cat.name}」？\n其下项目也会被删除。`)) return;
        try {
          await api(`/api/categories/${id}`, { method: "DELETE" });
          toast("分类已删除", "ok");
          if (state.selectedCategoryId === id) state.selectedCategoryId = null;
          await loadCategories();
          await loadProjects();
        } catch (e) {
          toast(e.message, "err");
        }
      }
    });
  });
}

function openCategoryDialog(cat = null, parentId = null) {
  $("#categoryDialogTitle").textContent = cat ? "编辑分类" : "新建分类";
  $("#catId").value = cat ? cat.id : "";
  $("#catName").value = cat ? cat.name : "";
  $("#catPath").value = cat ? cat.path || "" : "";
  $("#catDesc").value = cat ? cat.description || "" : "";
  state.pathPickedManually = Boolean(cat && cat.path);
  renderParentSelect(cat ? cat.id : null);
  if (cat) {
    $("#catParent").value = cat.parent_id ? String(cat.parent_id) : "";
  } else if (parentId) {
    $("#catParent").value = String(parentId);
  } else {
    $("#catParent").value = "";
  }
  $("#categoryDialog").showModal();

  $("#catName").oninput = () => {
    if (!$("#catId").value && !state.pathPickedManually) {
      // 仅提示性默认值，最终后端会再解析
      const name = $("#catName").value.trim() || "新分类";
      $("#catPath").value = "";
      // 不强制写路径；叶子用户可点浏览
      void name;
    }
  };
}

async function browseCategoryPath() {
  const current = $("#catPath").value.trim();
  const btn = $("#btnBrowsePath");
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "选择中…";
  try {
    const qs = current ? `?initial_path=${encodeURIComponent(current)}` : "";
    const data = await api(`/api/browse-folder${qs}`, { method: "POST" });
    if (data.cancelled) {
      toast("已取消选择", "info", 2000);
      return;
    }
    if (data.path) {
      $("#catPath").value = data.path;
      state.pathPickedManually = true;
      toast("已选择目录", "ok", 2000);
    }
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

async function saveCategory(ev) {
  ev.preventDefault();
  const id = $("#catId").value;
  const parentVal = $("#catParent").value;
  const body = {
    name: $("#catName").value.trim(),
    path: $("#catPath").value.trim(),
    description: $("#catDesc").value.trim(),
    parent_id: parentVal ? Number(parentVal) : null,
  };
  if (!body.name) {
    toast("名称不能为空", "err");
    return;
  }
  try {
    if (id) {
      await api(`/api/categories/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast("分类已更新", "ok");
    } else {
      await api("/api/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast("分类已创建", "ok");
    }
    $("#categoryDialog").close();
    await loadCategories();
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---------- Projects ----------

async function loadProjects() {
  const categoryId = $("#filterCategory")?.value || "";
  const keyword = $("#searchInput")?.value?.trim() || "";
  const includeDraft = $("#includeDraft")?.checked ? "true" : "false";
  const qs = new URLSearchParams();
  if (categoryId) qs.set("category_id", categoryId);
  if (keyword) qs.set("keyword", keyword);
  qs.set("include_draft", includeDraft);
  const data = await api(`/api/projects?${qs.toString()}`);
  state.projects = data.items || [];
  renderProjects();
}

function renderProjects() {
  const tbody = $("#projectTableBody");
  if (!state.projects.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">暂无项目。去「粘贴保存」创建第一个项目吧。</td></tr>`;
    return;
  }
  tbody.innerHTML = state.projects
    .map((p) => {
      const labels = [
        p.week_label ? `<span class="badge">周 ${escapeHtml(p.week_label)}</span>` : "",
        p.month_label ? `<span class="badge">月 ${escapeHtml(p.month_label)}</span>` : "",
        p.quarter_label ? `<span class="badge">季 ${escapeHtml(p.quarter_label)}</span>` : "",
      ].join("");
      const attCount = (p.attachments || []).length;
      const pathLabel = (p.category_path_names || []).join(" / ") || p.category_name || "";
      const status = p.status === "draft"
        ? `<span class="badge draft">草稿</span>`
        : `<span class="badge saved">已保存</span>`;
      return `
        <tr>
          <td>
            <strong>${escapeHtml(p.title)}</strong>
            <div class="hint">${escapeHtml((p.content_preview || "").slice(0, 60))}</div>
          </td>
          <td>${escapeHtml(pathLabel)}</td>
          <td>${status}</td>
          <td>${labels || '<span class="hint">—</span>'}</td>
          <td>${attCount ? `${attCount} 个` : "—"}</td>
          <td>${escapeHtml(p.updated_at || p.created_at || "")}</td>
          <td>
            <div class="ops">
              <button class="btn sm ghost" data-act="edit" data-id="${p.id}">编辑</button>
              <button class="btn sm ghost" data-act="detail" data-id="${p.id}">详情</button>
              <button class="btn sm danger" data-act="del" data-id="${p.id}">删除</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");

  $$("[data-act]", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      if (act === "edit") {
        await editProject(id);
      }
      if (act === "detail") showProjectDetail(id);
      if (act === "del") {
        if (!confirm("确认删除该项目？将从周期合并 Word 中移除。")) return;
        try {
          await api(`/api/projects/${id}`, { method: "DELETE" });
          toast("项目已删除", "ok");
          if (state.editingProjectId === id || state.draftProjectId === id) {
            resetForm(true);
          }
          await loadProjects();
          await loadCategories();
          await loadPeriodFiles();
        } catch (e) {
          toast(e.message, "err");
        }
      }
    });
  });
}

async function editProject(id) {
  try {
    const p = await api(`/api/projects/${id}`);
    state.editingProjectId = p.id;
    state.draftProjectId = p.status === "draft" ? p.id : p.id;
    $("#projectId").value = String(p.id);
    $("#docTitle").value = p.title || "";
    $("#docContent").value = p.content || "";
    $("#charCount").textContent = `${(p.content || "").length} 字`;
    if (p.category_id) $("#docCategory").value = String(p.category_id);
    // 时间模式
    const modes = p.time_modes || [];
    $$("#timeModes input").forEach((el) => {
      el.checked = modes.length ? modes.includes(el.value) : true;
    });
    state.pendingFiles = [];
    renderFileList();
    $("#composeTitle").textContent = p.status === "draft" ? "继续编辑草稿" : "编辑项目";
    state.dirty = false;
    updateTimeHint();
    switchView("compose");
    updateAutosaveStatus();
    toast("已加载项目到编辑区", "info", 2500);
  } catch (e) {
    toast(e.message, "err");
  }
}

async function showProjectDetail(id) {
  try {
    const p = await api(`/api/projects/${id}`);
    $("#docDialogTitle").textContent = p.title;
    const pathLabel = (p.category_path_names || []).join(" / ");
    const atts = (p.attachments || [])
      .map(
        (a) =>
          `<div>• <a href="/api/attachments/${a.id}/download">${escapeHtml(a.original_name)}</a>
           <span class="hint">（${formatSize(a.size)}）</span></div>`
      )
      .join("") || "无附件";
    $("#docDialogBody").innerHTML = `
      <div><div class="label">分类</div>${escapeHtml(pathLabel || p.category_name || "")}</div>
      <div><div class="label">状态</div>${p.status === "draft" ? "草稿" : "已保存"}</div>
      <div><div class="label">时间</div>
        创建 ${escapeHtml(p.created_at || "")}<br/>
        更新 ${escapeHtml(p.updated_at || "")}
      </div>
      <div><div class="label">时间标签</div>
        ${p.week_label ? `<span class="badge">${escapeHtml(p.week_label)}</span>` : ""}
        ${p.month_label ? `<span class="badge">${escapeHtml(p.month_label)}</span>` : ""}
        ${p.quarter_label ? `<span class="badge">${escapeHtml(p.quarter_label)}</span>` : ""}
      </div>
      <div>
        <div class="label">内容</div>
        <div class="block">${escapeHtml(p.content || "")}</div>
      </div>
      <div>
        <div class="label">附件</div>
        <div class="block">${atts}</div>
      </div>
    `;
    $("#docDialog").showModal();
  } catch (e) {
    toast(e.message, "err");
  }
}

// ---------- Period files ----------

async function loadPeriodFiles() {
  const data = await api("/api/period-files");
  state.periodFiles = data.items || [];
  renderPeriodFiles();
}

function renderPeriodFiles() {
  const tbody = $("#periodTableBody");
  if (!state.periodFiles.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">还没有周期文件。正式保存项目后会出现。</td></tr>`;
    return;
  }
  const typeCn = { week: "周", month: "月", quarter: "季度" };
  tbody.innerHTML = state.periodFiles
    .map((f) => {
      return `
        <tr>
          <td>${escapeHtml(f.category_name || "")}</td>
          <td>${typeCn[f.period_type] || f.period_type}</td>
          <td>${escapeHtml(f.period_label || "")}</td>
          <td>${f.project_count || 0}</td>
          <td>
            <div class="hint">${escapeHtml(f.word_filename || "")}</div>
            <div class="hint">${f.exists ? "文件存在" : "文件缺失（可点打开重建）"}</div>
          </td>
          <td>${escapeHtml(f.updated_at || "")}</td>
          <td>
            <div class="ops">
              <button class="btn sm ghost" data-act="open" data-cid="${f.category_id}" data-type="${f.period_type}" data-label="${escapeHtml(f.period_label)}">打开</button>
              <a class="btn sm ghost" href="/api/period-files/download?category_id=${f.category_id}&period_type=${encodeURIComponent(f.period_type)}&period_label=${encodeURIComponent(f.period_label)}" download>下载</a>
            </div>
          </td>
        </tr>`;
    })
    .join("");

  $$("[data-act=open]", tbody).forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const fd = new FormData();
        fd.append("category_id", btn.dataset.cid);
        fd.append("period_type", btn.dataset.type);
        fd.append("period_label", btn.dataset.label);
        await api("/api/period-files/open", { method: "POST", body: fd });
        toast("已用系统默认程序打开", "info");
      } catch (e) {
        toast(e.message, "err");
      }
    });
  });
}

// ---------- Compose / files / autosave ----------

function renderFileList() {
  const list = $("#fileList");
  if (!state.pendingFiles.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = state.pendingFiles
    .map(
      (f, i) => `
      <li>
        <div>
          <strong>${escapeHtml(f.name)}</strong>
          <div class="meta">${formatSize(f.size)}</div>
        </div>
        <button type="button" class="btn sm danger" data-i="${i}">移除</button>
      </li>`
    )
    .join("");
  $$("button[data-i]", list).forEach((btn) => {
    btn.addEventListener("click", () => {
      state.pendingFiles.splice(Number(btn.dataset.i), 1);
      renderFileList();
      markDirty();
    });
  });
}

function addFiles(fileList) {
  for (const f of fileList) {
    if (state.pendingFiles.some((x) => x.name === f.name && x.size === f.size)) continue;
    state.pendingFiles.push(f);
  }
  renderFileList();
  markDirty();
}

function updateAutosaveStatus() {
  const el = $("#autosaveStatus");
  if (!el) return;
  if (!$("#autosaveEnabled")?.checked) {
    el.textContent = "定时保存已关闭";
    return;
  }
  if (state.autosaveBusy) {
    el.textContent = "正在自动保存…";
    return;
  }
  if (state.lastAutosaveAt) {
    el.textContent = `上次草稿：${state.lastAutosaveAt}${state.dirty ? "（有未存改动）" : ""}`;
  } else {
    el.textContent = state.dirty ? "等待自动保存…" : "草稿空闲";
  }
}

async function autosaveNow(force = false) {
  if (state.autosaveBusy) return;
  if (!force && !$("#autosaveEnabled")?.checked) return;

  const content = $("#docContent").value;
  const title = $("#docTitle").value.trim();
  if (!content.trim() && !title) {
    updateAutosaveStatus();
    return;
  }
  // 无脏数据且不是强制，跳过
  if (!force && !state.dirty) {
    updateAutosaveStatus();
    return;
  }

  const categoryId = $("#docCategory").value;
  const modes = currentTimeModes();
  const projectId = $("#projectId").value || state.draftProjectId || null;

  state.autosaveBusy = true;
  updateAutosaveStatus();
  try {
    const body = {
      project_id: projectId ? Number(projectId) : null,
      title,
      category_id: categoryId ? Number(categoryId) : null,
      content,
      time_modes: modes,
    };
    const data = await api("/api/projects/autosave", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (data.skipped) return;
    const p = data.project;
    if (p?.id) {
      state.draftProjectId = p.id;
      state.editingProjectId = p.id;
      $("#projectId").value = String(p.id);
      $("#composeTitle").textContent = "编辑项目（已自动存草稿）";
    }
    state.dirty = false;
    state.lastAutosaveAt = new Date().toLocaleTimeString();
  } catch (e) {
    // 自动保存失败不打扰太多
    console.warn("autosave failed", e);
    const el = $("#autosaveStatus");
    if (el) el.textContent = `自动保存失败：${e.message}`;
    return;
  } finally {
    state.autosaveBusy = false;
    updateAutosaveStatus();
  }
}

function restartAutosaveTimer() {
  if (state.autosaveTimer) {
    clearInterval(state.autosaveTimer);
    state.autosaveTimer = null;
  }
  if (!$("#autosaveEnabled")?.checked) {
    updateAutosaveStatus();
    return;
  }
  const sec = Math.max(10, Number($("#autosaveSeconds").value || 30));
  state.autosaveTimer = setInterval(() => {
    if (state.activeView === "compose") autosaveNow(false);
  }, sec * 1000);
  updateAutosaveStatus();
}

async function saveDocument() {
  if (state.saveBusy) {
    toast("正在保存中，请勿重复点击", "info", 2500);
    return;
  }

  const content = $("#docContent").value;
  const categoryId = $("#docCategory").value;
  const title = $("#docTitle").value.trim();
  const modes = currentTimeModes();
  // 失败重试时优先复用已有项目 id，避免重复入库
  const projectId =
    $("#projectId").value || state.editingProjectId || state.draftProjectId || "";

  if (!content.trim()) {
    toast("请先粘贴或输入项目内容", "err");
    return;
  }
  if (!categoryId) {
    toast("请选择叶子分类", "err");
    return;
  }
  if (!modes.length) {
    toast("请至少选择一个时间周期", "err");
    return;
  }

  const btn = $("#btnSave");
  state.saveBusy = true;
  btn.disabled = true;
  btn.textContent = "保存中…";

  try {
    const fd = new FormData();
    fd.append("content", content);
    fd.append("category_id", categoryId);
    fd.append("title", title);
    fd.append("time_modes", modes.join(","));
    fd.append("client_save_token", state.clientSaveToken || makeSaveToken());
    if (projectId) fd.append("project_id", projectId);
    for (const f of state.pendingFiles) {
      fd.append("files", f, f.name);
    }

    const project = await api("/api/projects", { method: "POST", body: fd });
    // 成功后挂上 id，并轮转 token，下一笔新项目重新计数
    if (project?.id) {
      state.editingProjectId = project.id;
      state.draftProjectId = project.id;
      $("#projectId").value = String(project.id);
    }
    const pfCount = (project.period_files || []).length;
    toast(
      `项目已保存：${project.title}\n已更新 ${pfCount} 个周期 Word` +
        ((project.attachments || []).length ? `，附件 ${(project.attachments || []).length} 个` : ""),
      "ok",
      6000
    );

    // 重置表单（保留分类与时间选项）
    resetForm(false);
    await loadCategories();
    await loadProjects();
    await loadPeriodFiles();
  } catch (e) {
    // 若后端在失败前已创建/更新了项目且错误体含 id，则接住，防止下次再建
    const payload = e.payload;
    const maybeId =
      payload?.id ||
      payload?.project_id ||
      payload?.project?.id ||
      null;
    if (maybeId) {
      state.editingProjectId = Number(maybeId);
      state.draftProjectId = Number(maybeId);
      $("#projectId").value = String(maybeId);
      $("#composeTitle").textContent = "编辑项目（请关闭 Word 后重试保存）";
    } else if ($("#projectId").value || state.draftProjectId) {
      $("#composeTitle").textContent = "编辑项目（请关闭 Word 后重试保存）";
    }

    let msg = e.message || "保存失败";
    if (e.status === 423 || /占用|正在被打开|请先关闭|Word/.test(msg)) {
      msg =
        msg +
        "\n说明：请关闭对应 Word/WPS 文件后，再点一次保存。系统会更新同一项目，不会重复创建。";
    }
    toast(msg, "err", 10000);
  } finally {
    state.saveBusy = false;
    btn.disabled = false;
    btn.textContent = "正式保存到 Word";
  }
}

function resetForm(clearCategory = false) {
  $("#projectId").value = "";
  $("#docTitle").value = "";
  $("#docContent").value = "";
  $("#charCount").textContent = "0 字";
  $("#composeTitle").textContent = "新建项目";
  state.pendingFiles = [];
  state.draftProjectId = null;
  state.editingProjectId = null;
  state.dirty = false;
  state.lastAutosaveAt = null;
  state.saveBusy = false;
  // 新开项目：换 token
  state.clientSaveToken = makeSaveToken();
  renderFileList();
  if (clearCategory) {
    // keep
  }
  $$("#timeModes input").forEach((el) => (el.checked = true));
  updateTimeHint();
  updateAutosaveStatus();
}

// ---------- Bindings ----------

function bindEvents() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });

  $("#btnAddCategory").addEventListener("click", () => openCategoryDialog());
  $("#btnAddCategory2").addEventListener("click", () => openCategoryDialog());
  $("#btnCancelCat").addEventListener("click", () => $("#categoryDialog").close());
  $("#btnBrowsePath").addEventListener("click", () => browseCategoryPath());
  $("#catPath").addEventListener("input", () => {
    state.pathPickedManually = Boolean($("#catPath").value.trim());
  });
  $("#categoryForm").addEventListener("submit", saveCategory);
  $("#btnCloseDoc").addEventListener("click", () => $("#docDialog").close());

  $("#btnSave").addEventListener("click", saveDocument);
  $("#btnSaveDraft").addEventListener("click", () => autosaveNow(true).then(() => toast("草稿已保存", "ok", 2000)));
  $("#btnReset").addEventListener("click", () => resetForm(false));
  $("#btnNewProject").addEventListener("click", () => {
    resetForm(false);
    switchView("compose");
  });
  $("#btnClearContent").addEventListener("click", () => {
    $("#docContent").value = "";
    $("#charCount").textContent = "0 字";
    markDirty();
  });
  $("#docContent").addEventListener("input", () => {
    const n = $("#docContent").value.length;
    $("#charCount").textContent = `${n} 字`;
    markDirty();
  });
  $("#docTitle").addEventListener("input", markDirty);
  $("#docCategory").addEventListener("change", markDirty);

  $$("#timeModes input").forEach((el) =>
    el.addEventListener("change", () => {
      updateTimeHint();
      markDirty();
    })
  );

  $("#autosaveEnabled").addEventListener("change", restartAutosaveTimer);
  $("#autosaveSeconds").addEventListener("change", restartAutosaveTimer);

  $("#btnPickFiles").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", (e) => {
    addFiles(e.target.files);
    e.target.value = "";
  });

  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
    });
  });
  dz.addEventListener("drop", (e) => {
    if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
  });

  $("#btnRefreshProjects").addEventListener("click", () =>
    loadProjects().catch((e) => toast(e.message, "err"))
  );
  $("#btnRefreshPeriod").addEventListener("click", () =>
    loadPeriodFiles().catch((e) => toast(e.message, "err"))
  );
  $("#filterCategory").addEventListener("change", () => {
    state.selectedCategoryId = $("#filterCategory").value
      ? Number($("#filterCategory").value)
      : null;
    renderCategoryList();
    loadProjects().catch((e) => toast(e.message, "err"));
  });
  $("#includeDraft").addEventListener("change", () =>
    loadProjects().catch((e) => toast(e.message, "err"))
  );

  let searchTimer = null;
  $("#searchInput").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      if (state.activeView !== "projects") switchView("projects");
      loadProjects().catch((e) => toast(e.message, "err"));
    }, 280);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && state.activeView === "compose") {
      e.preventDefault();
      saveDocument();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && state.activeView === "compose") {
      e.preventDefault();
      autosaveNow(true).then(() => toast("草稿已保存", "ok", 1500));
    }
  });

  // 离开页前提示
  window.addEventListener("beforeunload", (e) => {
    if (state.dirty && $("#docContent").value.trim()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

async function boot() {
  bindEvents();
  updateTimeHint();
  try {
    await api("/api/health");
    $("#statusDot").classList.add("ok");
    $("#statusText").textContent = "本地服务已连接";
    await loadTimeInfo();
    await loadCategories();
    await loadProjects();
    await loadPeriodFiles();
    restartAutosaveTimer();
  } catch (e) {
    $("#statusDot").classList.add("err");
    $("#statusText").textContent = "服务未连接";
    toast("无法连接本地服务，请确认已运行 start.bat", "err", 8000);
  }
}

boot();
