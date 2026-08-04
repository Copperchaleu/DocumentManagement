<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, EditPen, Notebook } from '@element-plus/icons-vue'

const STORAGE_KEY = 'document-management-workbench-notes-v1'

const notes = ref([])
const draft = ref('')
const editDialogVisible = ref(false)
const editingId = ref(null)
const editForm = reactive({ content: '' })

const sortedNotes = computed(() =>
  [...notes.value].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)),
)

function loadNotes() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    notes.value = Array.isArray(stored) ? stored : []
  } catch {
    notes.value = []
    ElMessage.warning('随心记本地数据读取失败，已使用空列表')
  }
}

function saveNotes() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes.value))
  } catch {
    ElMessage.error('无法保存随心记，请检查浏览器存储设置')
  }
}

function addNote() {
  const content = draft.value.trim()
  if (!content) {
    ElMessage.warning('写点什么再记一笔吧')
    return
  }
  const now = new Date().toISOString()
  notes.value.unshift({
    id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    content,
    createdAt: now,
    updatedAt: now,
  })
  saveNotes()
  draft.value = ''
  ElMessage.success('已记一笔')
}

function openEdit(note) {
  editingId.value = note.id
  editForm.content = note.content
  editDialogVisible.value = true
}

async function submitEdit() {
  const content = editForm.content.trim()
  if (!content) {
    ElMessage.warning('内容不能为空')
    return
  }
  const index = notes.value.findIndex((n) => n.id === editingId.value)
  if (index >= 0) {
    notes.value[index] = {
      ...notes.value[index],
      content,
      updatedAt: new Date().toISOString(),
    }
    saveNotes()
  }
  editDialogVisible.value = false
  editingId.value = null
  ElMessage.success('已更新')
}

async function removeNote(note) {
  try {
    await ElMessageBox.confirm('确定删除这条随心记吗？', '删除随心记', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    notes.value = notes.value.filter((n) => n.id !== note.id)
    saveNotes()
    ElMessage.success('已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('删除失败')
  }
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(() => {
  loadNotes()
})

defineExpose({ loadNotes })
</script>

<template>
  <div class="notes-panel">
    <section class="workbench-card notes-compose">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        resize="none"
        placeholder="此刻在想什么？随手记一笔…"
        @keydown.ctrl.enter="addNote"
        @keydown.meta.enter="addNote"
      />
      <div class="notes-compose-actions">
        <span class="notes-hint">Ctrl / Cmd + Enter 快速记录</span>
        <el-button type="primary" :icon="Notebook" @click="addNote">记一笔</el-button>
      </div>
    </section>

    <section class="notes-list">
      <div v-if="sortedNotes.length" class="notes-items">
        <article v-for="note in sortedNotes" :key="note.id" class="note-item">
          <p class="note-content">{{ note.content }}</p>
          <div class="note-meta">
            <time>{{ formatTime(note.createdAt) }}</time>
            <div class="note-actions">
              <el-button circle size="small" :icon="EditPen" title="编辑" @click="openEdit(note)" />
              <el-button circle size="small" :icon="Delete" title="删除" @click="removeNote(note)" />
            </div>
          </div>
        </article>
      </div>
      <div v-else class="notes-empty">
        <div class="empty-illustration"><Notebook /></div>
        <h3>还没有随手记</h3>
        <p>记下第一件小事吧</p>
      </div>
    </section>

    <el-dialog v-model="editDialogVisible" title="编辑随心记" width="520px" destroy-on-close append-to-body>
      <el-input
        v-model="editForm.content"
        type="textarea"
        :rows="4"
        maxlength="500"
        show-word-limit
        resize="none"
      />
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.notes-panel { --wb-indigo: #4f46e5; --wb-navy: #172554; display: grid; gap: 16px; }
.workbench-card { border: 1px solid #dde5ef; border-radius: 19px; background: rgba(255,255,255,.96); box-shadow: 0 10px 30px rgba(15, 23, 42, .055); }
.notes-compose { padding: 21px; }
.workbench-card-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.workbench-card h2 { margin: 3px 0 0; color: #172554; font-size: 19px; letter-spacing: -.02em; }
.section-kicker { color: #6366f1; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.notes-compose-actions { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }
.notes-hint { color: #94a3b8; font-size: 11px; }
.notes-list { min-height: 120px; }
.notes-items { display: grid; gap: 10px; }
.note-item { padding: 14px 16px; border: 1px solid #e7edf4; border-left: 3px solid #818cf8; border-radius: 13px; background: #fff; transition: transform .16s ease, box-shadow .16s ease; }
.note-item:hover { transform: translateY(-1px); box-shadow: 0 7px 18px rgba(30, 41, 59, .06); }
.note-content { margin: 0 0 10px; color: #334155; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.note-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.note-meta time { color: #94a3b8; font-size: 11px; }
.note-actions { display: flex; gap: 5px; }
.note-actions :deep(.el-button + .el-button) { margin-left: 0; }
.note-actions :deep(.el-button) { width: 30px; height: 30px; min-height: 30px; }
.notes-empty { display: grid; justify-items: center; padding: 64px 20px; text-align: center; }
.empty-illustration { display: grid; place-items: center; width: 60px; height: 60px; border-radius: 20px; background: linear-gradient(135deg,#eef2ff,#e0e7ff); color: #6366f1; }
.empty-illustration svg { width: 26px; }
.notes-empty h3 { margin: 16px 0 6px; font-size: 15px; color: #334155; }
.notes-empty p { margin: 0; color: #94a3b8; font-size: 12px; }
</style>
