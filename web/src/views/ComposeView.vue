<script setup>
import { computed, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import {
  appState,
  refreshCategories,
  refreshPeriodFiles,
  refreshProjects,
  refreshTimeInfo,
} from '../stores/appState'
import { autosaveProject, saveProject } from '../api'
import { toastError } from '../api/http'
import {
  cascaderValueToId,
  getCategoryValuePath,
  makeSaveToken,
  toCascaderOptions,
} from '../utils/tree'

const route = useRoute()
const editorRef = shallowRef()
const editorMode = 'simple'
const toolbarConfig = {
  toolbarKeys: [
    'headerSelect',
    '|',
    'bold',
    'italic',
    'underline',
    'through',
    'color',
    '|',
    'bulletedList',
    'numberedList',
    'blockquote',
    '|',
    'justifyLeft',
    'justifyCenter',
    'justifyRight',
    '|',
    'insertLink',
    'undo',
    'redo',
  ],
}
const editorConfig = {
  placeholder: '在此粘贴或输入该项目的相关信息…',
  scroll: true,
  MENU_CONF: {},
}

const form = reactive({
  projectId: null,
  title: '',
  categoryId: null,
  content: '',
  timeModes: ['week', 'month', 'quarter'],
})

const fileList = ref([])
const saveBusy = ref(false)
const autosaveEnabled = ref(true)
const autosaveSeconds = ref(30)
const autosaveStatus = ref('草稿空闲')
const dirty = ref(false)
const lastAutosaveAt = ref('')
const clientSaveToken = ref(makeSaveToken())
let autosaveTimer = null
let autosaveBusy = false

function htmlToPlainText(html = '') {
  const source = String(html || '')
  if (!source) return ''
  const div = document.createElement('div')
  div.innerHTML = source
  return (div.textContent || div.innerText || '')
    .replace(/\u00a0/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

const contentText = computed(() => htmlToPlainText(form.content))
const contentLength = computed(() => contentText.value.length)

function handleEditorCreated(editor) {
  editorRef.value = editor
}

function handleEditorChange() {
  markDirty()
}

onBeforeUnmount(() => {
  const editor = editorRef.value
  if (editor == null) return
  editor.destroy()
})

// 弹出式多级级联：悬停展开，任意中间级/末级均可选（checkStrictly）
const categoryCascaderOptions = computed(() => toCascaderOptions(appState.categoryTree))
const categoryCascaderProps = {
  expandTrigger: 'hover',
  checkStrictly: true,
  emitPath: true,
  value: 'value',
  label: 'label',
  children: 'children',
}
const categoryPath = computed({
  get: () => getCategoryValuePath(form.categoryId, appState.categoryTree),
  set: (val) => {
    form.categoryId = cascaderValueToId(val)
  },
})

const weekHint = computed(() => {
  const week = appState.timeInfo?.week
  if (!week) return '按周规则：ISO 周，周一至周日'
  return `按周规则：ISO 周，周一至周日（本周 ${week.label}：${week.start} ~ ${week.end}）`
})

const timeHint = computed(() => {
  const labels = appState.timeInfo?.labels || {}
  const modes = form.timeModes || []
  const parts = []
  if (modes.includes('week') && labels.week) parts.push(`by_week/${labels.week}/汇总.docx`)
  if (modes.includes('month') && labels.month) parts.push(`by_month/${labels.month}/汇总.docx`)
  if (modes.includes('quarter') && labels.quarter) parts.push(`by_quarter/${labels.quarter}/汇总.docx`)
  return parts.length
    ? `本分类本周期所有项目将合并写入：${parts.join('  +  ')}`
    : '请至少选择一个时间周期'
})

function markDirty() {
  dirty.value = true
  updateAutosaveStatus()
}

function updateAutosaveStatus() {
  if (!autosaveEnabled.value) {
    autosaveStatus.value = '定时保存已关闭'
    return
  }
  if (autosaveBusy) {
    autosaveStatus.value = '正在自动保存…'
    return
  }
  if (lastAutosaveAt.value) {
    autosaveStatus.value = `上次草稿：${lastAutosaveAt.value}${dirty.value ? '（有未存改动）' : ''}`
  } else {
    autosaveStatus.value = dirty.value ? '等待自动保存…' : '草稿空闲'
  }
}

function resetForm() {
  form.projectId = null
  form.title = ''
  form.content = ''
  form.timeModes = ['week', 'month', 'quarter']
  fileList.value = []
  dirty.value = false
  lastAutosaveAt.value = ''
  clientSaveToken.value = makeSaveToken()
  // 保留当前分类选择；若为空则尝试沿用侧边栏选中，否则默认第一个叶子
  if (!form.categoryId) {
    if (appState.selectedCategoryId) {
      form.categoryId = appState.selectedCategoryId
    } else if (appState.leafCategories?.[0]) {
      form.categoryId = appState.leafCategories[0].id
    }
  }
  updateAutosaveStatus()
}

function onCategoryCascaderChange(val) {
  form.categoryId = cascaderValueToId(val)
  markDirty()
}

async function doAutosave(force = false) {
  if (autosaveBusy) return
  if (!force && !autosaveEnabled.value) return
  if (!contentText.value && !form.title.trim()) return
  if (!force && !dirty.value) return

  autosaveBusy = true
  updateAutosaveStatus()
  try {
    const data = await autosaveProject({
      project_id: form.projectId,
      title: form.title,
      category_id: form.categoryId,
      content: form.content,
      time_modes: form.timeModes,
    })
    if (data.skipped) return
    if (data.project?.id) {
      form.projectId = data.project.id
    }
    dirty.value = false
    lastAutosaveAt.value = new Date().toLocaleTimeString()
    if (force) ElMessage.success('草稿已保存')
  } catch (e) {
    autosaveStatus.value = `自动保存失败：${e.friendlyMessage || e.message}`
    if (force) toastError(e, '草稿保存失败')
  } finally {
    autosaveBusy = false
    updateAutosaveStatus()
  }
}

function restartAutosaveTimer() {
  if (autosaveTimer) {
    clearInterval(autosaveTimer)
    autosaveTimer = null
  }
  if (!autosaveEnabled.value) {
    updateAutosaveStatus()
    return
  }
  const sec = Math.max(10, Number(autosaveSeconds.value || 30))
  autosaveTimer = setInterval(() => doAutosave(false), sec * 1000)
  updateAutosaveStatus()
}

function onFileChange(uploadFile, uploadFiles) {
  fileList.value = uploadFiles
  markDirty()
}

function onFileRemove(_file, uploadFiles) {
  fileList.value = uploadFiles
  markDirty()
}

async function onSave() {
  if (saveBusy.value) {
    ElMessage.info('正在保存中，请勿重复点击')
    return
  }
  if (!contentText.value) {
    ElMessage.error('请先粘贴或输入项目内容')
    return
  }
  if (!form.categoryId) {
    ElMessage.error('请选择归属分类')
    return
  }
  if (!form.timeModes.length) {
    ElMessage.error('请至少选择一个时间周期')
    return
  }

  saveBusy.value = true
  try {
    const fd = new FormData()
    fd.append('content', form.content)
    fd.append('category_id', String(form.categoryId))
    fd.append('title', form.title || '')
    fd.append('time_modes', form.timeModes.join(','))
    fd.append('client_save_token', clientSaveToken.value)
    if (form.projectId) fd.append('project_id', String(form.projectId))
    for (const f of fileList.value) {
      if (f.raw) fd.append('files', f.raw, f.name)
    }
    const project = await saveProject(fd)
    ElMessage.success(
      `项目已保存：${project.title}；已更新 ${(project.period_files || []).length} 个周期 Word`,
    )
    resetForm()
    await Promise.all([refreshCategories(), refreshProjects(), refreshPeriodFiles(), refreshTimeInfo()])
  } catch (e) {
    const payload = e?.response?.data
    const maybeId = payload?.id || payload?.project_id || payload?.project?.id
    if (maybeId) form.projectId = Number(maybeId)
    let msg = e.friendlyMessage || e.message || '保存失败'
    if (e?.response?.status === 423 || /占用|正在被打开|请先关闭|Word/.test(msg)) {
      msg += ' 请关闭对应 Word/WPS 文件后，再点一次保存。系统会更新同一项目，不会重复创建。'
    }
    ElMessage.error({ message: msg, duration: 8000, showClose: true })
  } finally {
    saveBusy.value = false
  }
}

watch(
  () => appState.leafCategories,
  (leaves) => {
    if (!form.categoryId && leaves?.[0]) form.categoryId = leaves[0].id
  },
  { immediate: true },
)

// 侧边栏点选分类时同步到表单（任意级，不再限制仅叶子）
watch(
  () => appState.selectedCategoryId,
  (id) => {
    if (id) form.categoryId = id
  },
)

watch(autosaveEnabled, restartAutosaveTimer)
watch(autosaveSeconds, restartAutosaveTimer)

function loadEditPayload() {
  const raw = sessionStorage.getItem('edit_project_payload')
  if (!raw) return
  try {
    const p = JSON.parse(raw)
    form.projectId = p.id
    form.title = p.title || ''
    form.content = p.content || ''
    form.categoryId = p.category_id || null
    form.timeModes = p.time_modes?.length ? [...p.time_modes] : ['week', 'month', 'quarter']
    dirty.value = false
    clientSaveToken.value = makeSaveToken()
    ElMessage.success('已加载项目到编辑区')
  } catch {
    // ignore
  } finally {
    sessionStorage.removeItem('edit_project_payload')
  }
}

onMounted(async () => {
  if (!appState.timeInfo) await refreshTimeInfo()
  if (appState.timeInfo?.autosave_seconds) {
    autosaveSeconds.value = Number(appState.timeInfo.autosave_seconds)
  }
  if (route.query.edit) loadEditPayload()
  restartAutosaveTimer()
})

watch(
  () => route.query.edit,
  (v) => {
    if (v) loadEditPayload()
  },
)

onUnmounted(() => {
  if (autosaveTimer) clearInterval(autosaveTimer)
})
</script>

<template>
  <div class="panel compose-panel">
    <div class="panel-head">
      <div class="title-area">
        <div class="title-row">
          <h2>{{ form.projectId ? '编辑项目' : '新建项目' }}</h2>
          <el-tag v-if="form.projectId" size="small" type="warning" effect="plain" round>
            编辑中 #{{ form.projectId }}
          </el-tag>
          <el-tag v-else size="small" type="info" effect="plain" round>新建</el-tag>
          <el-button plain class="reset-btn" @click="resetForm">重置表单</el-button>
        </div>
        <p class="muted">
          每次粘贴保存一个项目信息；可归属任意级分类（中间级/末级均可），并按时间周期合并进同一 Word
        </p>
      </div>

      <div class="autosave-box">
        <el-switch v-model="autosaveEnabled" active-text="定时保存" />
        <el-select v-model="autosaveSeconds" style="width: 110px">
          <el-option :value="15" label="15 秒" />
          <el-option :value="30" label="30 秒" />
          <el-option :value="60" label="60 秒" />
          <el-option :value="120" label="2 分钟" />
        </el-select>
        <span class="hint autosave-status" :class="{ dirty }">{{ autosaveStatus }}</span>
      </div>
    </div>

    <el-form class="compose-form" label-position="top">
      <el-row :gutter="18">
        <el-col :xs="24" :md="14">
          <el-form-item label="项目标题（可空，默认取首行）">
            <el-input
              v-model="form.title"
              placeholder="例如：XX招标项目谈判要点"
              maxlength="120"
              show-word-limit
              @input="markDirty"
            />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="10">
          <el-form-item label="归属分类 *">
            <el-cascader
              v-model="categoryPath"
              :options="categoryCascaderOptions"
              :props="categoryCascaderProps"
              clearable
              filterable
              style="width: 100%"
              placeholder="请选择分类（支持中间级，悬停展开）"
              :show-all-levels="true"
              separator=" / "
              @change="onCategoryCascaderChange"
            />
            <div class="hint field-hint">多级弹出选择；悬停展开子级，可点选中间级或最末级</div>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="写入时间周期（可多选；同一最末级分类同一周期的所有项目合并到一个 Word）">
        <el-checkbox-group v-model="form.timeModes" class="period-checks" @change="markDirty">
          <el-checkbox label="week" border>按周</el-checkbox>
          <el-checkbox label="month" border>按月</el-checkbox>
          <el-checkbox label="quarter" border>按季度</el-checkbox>
        </el-checkbox-group>
        <div class="hint-stack">
          <div class="hint">{{ weekHint }}</div>
          <div class="hint path-hint">{{ timeHint }}</div>
        </div>
      </el-form-item>

      <el-form-item label="项目内容 *">
        <div class="rich-editor-shell">
          <Toolbar
            class="rich-toolbar"
            :editor="editorRef"
            :default-config="toolbarConfig"
            :mode="editorMode"
          />
          <Editor
            v-model="form.content"
            class="rich-editor"
            :default-config="editorConfig"
            :mode="editorMode"
            @on-created="handleEditorCreated"
            @on-change="handleEditorChange"
          />
        </div>
        <div class="content-meta">
          <span class="hint">支持标题、粗体、列表、引用和链接等常用格式</span>
          <span class="hint">{{ contentLength }} 字</span>
        </div>
      </el-form-item>

      <el-form-item label="附件（可选，支持多个）">
        <el-upload
          class="upload-box"
          drag
          multiple
          :auto-upload="false"
          :file-list="fileList"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
        >
          <div class="upload-inner">
            <div class="upload-title">拖拽文件到此处，或 <em>点击选择</em></div>
            <div class="hint">可多选，附件会随项目一并归档</div>
          </div>
        </el-upload>
      </el-form-item>

      <div class="form-actions">
        <el-button type="primary" size="large" :loading="saveBusy" @click="onSave">
          正式保存到 Word
        </el-button>
        <el-button size="large" @click="doAutosave(true)">立即保存草稿</el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped>
.compose-panel {
  width: 100%;
}

.reset-btn {
  margin-left: 2px;
  color: #9a3412 !important;
  background: #ffedd5 !important;
  border-color: #fb923c !important;
  box-shadow: 0 2px 6px rgba(194, 65, 12, 0.12);
}

.reset-btn:hover,
.reset-btn:focus-visible {
  color: #ffffff !important;
  background: #c2410c !important;
  border-color: #c2410c !important;
  box-shadow: 0 0 0 3px rgba(234, 88, 12, 0.18);
}

.autosave-status {
  max-width: 220px;
  text-align: right;
}
.autosave-status.dirty {
  color: #b45309;
  font-weight: 600;
}

.compose-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.field-hint {
  margin-top: 6px;
}

.hint-stack {
  margin-top: 8px;
  display: grid;
  gap: 2px;
}

.path-hint {
  font-family: var(--font-mono);
  color: #64748b;
  word-break: break-all;
}

.rich-editor-shell {
  width: 100%;
  overflow: hidden;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.rich-editor-shell:focus-within {
  border-color: #3730a3;
  box-shadow: 0 0 0 3px rgba(55, 48, 163, 0.14);
}

.rich-toolbar {
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.rich-editor {
  min-height: 320px;
  max-height: 560px;
  overflow-y: auto;
  background: #fff;
}

.rich-editor :deep(.w-e-text-container) {
  min-height: 320px;
  background: #fff;
}

.rich-editor :deep(.w-e-scroll) {
  min-height: 320px;
}

.rich-editor :deep(.w-e-text-placeholder) {
  color: #94a3b8;
  font-style: normal;
}

.rich-editor :deep(.w-e-text-container [data-slate-editor]) {
  padding: 16px 18px;
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.75;
  color: #0f172a;
}

.rich-toolbar :deep(.w-e-bar-item button) {
  min-width: 34px;
  height: 34px;
  color: #334155;
  border-radius: 7px;
}

.rich-toolbar :deep(.w-e-bar-item button:hover),
.rich-toolbar :deep(.w-e-bar-item button.active) {
  color: #312e81;
  background: #e8eaf8;
}

.content-meta {
  width: 100%;
  margin-top: 7px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.period-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}

.upload-inner {
  padding: 8px 0 4px;
}

.upload-title {
  color: #334155;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.upload-title em {
  color: var(--brand, #4f46e5);
  font-style: normal;
  font-weight: 700;
}

.form-actions :deep(.el-button--large) {
  min-width: 148px;
  height: 42px;
}
</style>
