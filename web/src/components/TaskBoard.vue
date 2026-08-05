<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import {
  Bell,
  Calendar,
  Check,
  Clock,
  Delete,
  EditPen,
  Plus,
  Search,
  Warning,
} from '@element-plus/icons-vue'
import { getTasks, createTask, updateTask, deleteTask, migrateWorkbench } from '../api/workbench'
import { toastError } from '../api/http'

// 仅用于一次性迁移探测 + 离线回退读取，不再作为主存储。
const LEGACY_STORAGE_KEY = 'document-management-workbench-tasks-v1'
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
const filters = [
  { value: 'all', label: '全部任务' },
  { value: 'today', label: '今日截止' },
  { value: 'upcoming', label: '未来待办' },
  { value: 'completed', label: '已完成' },
]
const priorities = {
  high: { label: '高优先级', short: '高', color: '#dc2626', type: 'danger' },
  medium: { label: '中优先级', short: '中', color: '#d97706', type: 'warning' },
  low: { label: '低优先级', short: '低', color: '#059669', type: 'success' },
}

const tasks = ref([])
const activeFilter = ref('all')
const keyword = ref('')
const selectedDate = ref(dateKey(new Date()))
const calendarCursor = ref(startOfMonth(new Date()))
const dialogVisible = ref(false)
const editingId = ref(null)
const permissionState = ref(
  typeof Notification === 'undefined' ? 'unsupported' : Notification.permission,
)
const loading = ref(false)
let reminderTimer = null

const form = reactive(emptyForm())
const formRef = ref(null)
const formRules = {
  title: [
    { required: true, message: '请输入待办事项', trigger: 'blur' },
    { max: 80, message: '标题不超过 80 个字', trigger: 'blur' },
  ],
}

const todayKey = computed(() => dateKey(new Date()))
const completedCount = computed(() => tasks.value.filter(isCompleted).length)
const activeCount = computed(() => tasks.value.length - completedCount.value)
const todayCount = computed(
  () => tasks.value.filter((task) => task.dueDate === todayKey.value && !isCompleted(task)).length,
)
const overdueCount = computed(
  () => tasks.value.filter((task) => isOverdue(task) && !isCompleted(task)).length,
)
const filteredTasks = computed(() => {
  const now = todayKey.value
  let list = [...tasks.value]
  if (activeFilter.value === 'today') list = list.filter((task) => task.dueDate === now && !isCompleted(task))
  if (activeFilter.value === 'upcoming') list = list.filter((task) => task.dueDate > now && !isCompleted(task))
  if (activeFilter.value === 'completed') list = list.filter(isCompleted)
  if (keyword.value.trim()) {
    const query = keyword.value.trim().toLowerCase()
    list = list.filter((task) => `${task.title} ${task.notes || ''}`.toLowerCase().includes(query))
  }
  return list.sort(compareTasks)
})

const selectedDayTasks = computed(() =>
  tasks.value.filter((task) => task.dueDate === selectedDate.value).sort(compareTasks),
)

const upcomingReminders = computed(() => {
  const now = Date.now()
  return tasks.value
    .filter((task) => task.reminderAt && !isCompleted(task) && new Date(task.reminderAt).getTime() >= now)
    .sort((a, b) => new Date(a.reminderAt) - new Date(b.reminderAt))
    .slice(0, 4)
})

const calendarTitle = computed(
  () => `${calendarCursor.value.getFullYear()} 年 ${calendarCursor.value.getMonth() + 1} 月`,
)

const calendarDays = computed(() => {
  const year = calendarCursor.value.getFullYear()
  const month = calendarCursor.value.getMonth()
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7
  const start = new Date(year, month, 1 - offset)
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)
    const key = dateKey(date)
    const dayTasks = tasks.value.filter((task) => task.dueDate === key)
    return {
      key,
      day: date.getDate(),
      currentMonth: date.getMonth() === month,
      isToday: key === todayKey.value,
      isSelected: key === selectedDate.value,
      taskCount: dayTasks.length,
      completed: dayTasks.filter(isCompleted).length,
      hasHigh: dayTasks.some((task) => task.priority === 'high' && !isCompleted(task)),
    }
  })
})

function emptyForm() {
  return {
    title: '',
    notes: '',
    priority: 'medium',
    dueDate: dateKey(new Date()),
    dueTime: '',
    reminderEnabled: false,
    reminderAt: '',
  }
}

function dateKey(value) {
  const date = value instanceof Date ? value : new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function isCompleted(task) {
  return Boolean(task.completed)
}

function isOverdue(task) {
  const deadline = task.dueTime ? `${task.dueDate}T${task.dueTime}` : `${task.dueDate}T23:59`
  return new Date(deadline).getTime() < Date.now()
}

function compareTasks(a, b) {
  if (isCompleted(a) !== isCompleted(b)) return isCompleted(a) ? 1 : -1
  const first = `${a.dueDate || '9999-12-31'}T${a.dueTime || '23:59'}`
  const second = `${b.dueDate || '9999-12-31'}T${b.dueTime || '23:59'}`
  if (first !== second) return first.localeCompare(second)
  return { high: 0, medium: 1, low: 2 }[a.priority] - { high: 0, medium: 1, low: 2 }[b.priority]
}

function loadTasks() {
  loading.value = true
  getTasks()
    .then((res) => {
      tasks.value = Array.isArray(res?.items) ? res.items : []
      // 后端为空且本地存在旧数据：一次性迁移到后端，再重载。
      if (tasks.value.length === 0) {
        const legacy = readLegacyTasks()
        if (legacy.length > 0) {
          return migrateWorkbench({ tasks: legacy, notes: [] })
            .then(() => getTasks())
            .then((reload) => {
              tasks.value = Array.isArray(reload?.items) ? reload.items : []
              clearLegacyTasks()
            })
            .catch((err) => {
              // 迁移失败：回退使用本地缓存，保留旧数据以便重试。
              tasks.value = legacy
              toastError(err, '迁移失败，已使用本地缓存')
            })
        }
      }
    })
    .catch((err) => {
      // 网络/服务异常：回退本地缓存，保证不白屏。
      tasks.value = readLegacyTasks()
      toastError(err, '离线使用本地缓存')
    })
    .finally(() => {
      loading.value = false
    })
}

// 读取并归一化旧版 localStorage 数据（用于迁移探测与离线回退）。
function readLegacyTasks() {
  try {
    const stored = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || '[]')
    if (!Array.isArray(stored)) return []
    return stored.map(({ progress, ...task }) => ({
      ...task,
      completed: typeof task.completed === 'boolean' ? task.completed : Number(progress) >= 100,
    }))
  } catch {
    return []
  }
}

function clearLegacyTasks() {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  } catch {
    /* 忽略清除失败，下次仍可按空库触发迁移重试 */
  }
}

function openCreate(prefilledDate = selectedDate.value || todayKey.value) {
  editingId.value = null
  Object.assign(form, emptyForm(), { dueDate: prefilledDate })
  dialogVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

function openEdit(task) {
  editingId.value = task.id
  Object.assign(form, emptyForm(), {
    ...task,
    reminderEnabled: Boolean(task.reminderAt),
  })
  dialogVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

async function submitTask() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.reminderEnabled && !form.reminderAt) {
    ElMessage.warning('请选择提醒时间')
    return
  }
  const now = new Date().toISOString()
  const payload = {
    title: form.title.trim(),
    notes: form.notes.trim(),
    priority: form.priority,
    dueDate: form.dueDate,
    dueTime: form.dueTime || '',
    reminderAt: form.reminderEnabled ? form.reminderAt : '',
    updatedAt: now,
  }
  loading.value = true
  try {
    if (editingId.value) {
      const updated = await updateTask(editingId.value, payload)
      const index = tasks.value.findIndex((task) => task.id === editingId.value)
      if (index >= 0) tasks.value[index] = updated
      ElMessage.success('待办已更新')
    } else {
      const created = await createTask({
        ...payload,
        id:
          globalThis.crypto?.randomUUID?.() ||
          `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        createdAt: now,
        completed: false,
        notifiedAt: '',
      })
      tasks.value.unshift(created)
      ElMessage.success('待办已创建')
    }
    dialogVisible.value = false
    selectedDate.value = form.dueDate
    calendarCursor.value = startOfMonth(new Date(`${form.dueDate}T00:00:00`))
  } catch (e) {
    toastError(e, '保存失败，请重试')
  } finally {
    loading.value = false
  }
}

async function removeTask(task) {
  try {
    await ElMessageBox.confirm(`确定删除“${task.title}”吗？`, '删除待办', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    const snapshot = tasks.value
    tasks.value = tasks.value.filter((item) => item.id !== task.id)
    loading.value = true
    try {
      await deleteTask(task.id)
      ElMessage.success('待办已删除')
    } catch (e) {
      tasks.value = snapshot
      toastError(e, '删除失败，已恢复')
    } finally {
      loading.value = false
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') toastError(error, '删除失败')
  }
}

function toggleCompleted(task) {
  const previous = task.completed
  const next = !isCompleted(task)
  task.completed = next
  task.updatedAt = new Date().toISOString()
  updateTask(task.id, { completed: next, updatedAt: task.updatedAt })
    .then((updated) => {
      Object.assign(task, updated)
    })
    .catch((err) => {
      task.completed = previous
      toastError(err, '状态更新失败，已回滚')
    })
}

function selectCalendarDay(day) {
  selectedDate.value = day.key
  if (!day.currentMonth) calendarCursor.value = startOfMonth(new Date(`${day.key}T00:00:00`))
}

function changeMonth(offset) {
  calendarCursor.value = new Date(
    calendarCursor.value.getFullYear(),
    calendarCursor.value.getMonth() + offset,
    1,
  )
}

function jumpToday() {
  const today = new Date()
  calendarCursor.value = startOfMonth(today)
  selectedDate.value = dateKey(today)
}

function formatDate(value, withYear = false) {
  if (!value) return '未设置'
  const date = new Date(`${value}T00:00:00`)
  return new Intl.DateTimeFormat('zh-CN', {
    ...(withYear ? { year: 'numeric' } : {}),
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(date)
}

function formatReminder(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function deadlineText(task) {
  if (task.dueDate === todayKey.value) return `今天${task.dueTime ? ` ${task.dueTime}` : ''}`
  return `${formatDate(task.dueDate)}${task.dueTime ? ` ${task.dueTime}` : ''}`
}

async function requestNotificationPermission() {
  if (typeof Notification === 'undefined') {
    ElMessage.info('当前环境不支持系统通知，仍会使用站内提醒')
    return
  }
  permissionState.value = await Notification.requestPermission()
  if (permissionState.value === 'granted') ElMessage.success('系统提醒已开启')
  if (permissionState.value === 'denied') ElMessage.warning('系统通知已被拒绝，将使用站内提醒')
}

function checkReminders() {
  const now = Date.now()
  tasks.value.forEach((task) => {
    if (!task.reminderAt || task.notifiedAt || isCompleted(task)) return
    const reminderTime = new Date(task.reminderAt).getTime()
    if (Number.isNaN(reminderTime) || reminderTime > now) return
    task.notifiedAt = new Date().toISOString()
    // 持久化 notifiedAt，保证刷新后不再重复提醒（fire-and-forget，失败不影响会话内去重）
    updateTask(task.id, { notifiedAt: task.notifiedAt }).catch(() => {})
    ElNotification({
      title: '待办提醒',
      message: task.title,
      type: 'warning',
      duration: 8000,
      position: 'bottom-right',
    })
    if (permissionState.value === 'granted') {
      new Notification('待办提醒', { body: task.title, tag: task.id })
    }
  })
}

// ---- 暴露给外壳 WorkbenchView 的 hero 使用 ----
function createTaskToday() {
  openCreate(todayKey.value)
}

function enableNotifications() {
  requestNotificationPermission()
}

onMounted(() => {
  loadTasks()
  checkReminders()
  reminderTimer = window.setInterval(checkReminders, 30_000)
})

onUnmounted(() => window.clearInterval(reminderTimer))

defineExpose({ createTaskToday, enableNotifications, permissionState })
</script>

<template>
  <div class="task-board-page">
    <section class="metric-grid" aria-label="任务概况">
      <article class="metric-card metric-indigo">
        <div class="metric-icon"><Calendar /></div>
        <div><span>今日待办</span><strong>{{ todayCount }}</strong></div>
        <small>聚焦今天要完成的事</small>
      </article>
      <article class="metric-card metric-amber">
        <div class="metric-icon"><Clock /></div>
        <div><span>进行中</span><strong>{{ activeCount }}</strong></div>
        <small>{{ overdueCount ? `${overdueCount} 项已逾期` : '当前节奏良好' }}</small>
      </article>
      <article class="metric-card metric-emerald">
        <div class="metric-icon"><Check /></div>
        <div><span>已完成</span><strong>{{ completedCount }}</strong></div>
        <small>共 {{ tasks.length }} 项待办事项</small>
      </article>
      <article class="metric-card metric-rose">
        <div class="metric-icon"><Warning /></div>
        <div><span>已过期</span><strong>{{ overdueCount }}</strong></div>
        <small>{{ overdueCount ? '需要尽快处理' : '没有逾期待办' }}</small>
      </article>
    </section>

    <div class="workbench-grid">
      <section class="workbench-card task-board" v-loading="loading" element-loading-text="加载待办…">
        <header class="workbench-card-head">
          <el-input v-model="keyword" class="task-search" clearable :prefix-icon="Search" placeholder="搜索待办…" />
        </header>

        <div class="task-filter-row">
          <button
            v-for="item in filters"
            :key="item.value"
            type="button"
            :class="{ active: activeFilter === item.value }"
            @click="activeFilter = item.value"
          >
            {{ item.label }}
          </button>
        </div>

        <div v-if="filteredTasks.length" class="task-list">
          <article
            v-for="task in filteredTasks"
            :key="task.id"
            class="task-item"
            :class="{ completed: isCompleted(task), overdue: isOverdue(task) && !isCompleted(task) }"
          >
            <div class="task-primary">
              <button class="task-check" type="button" :aria-label="isCompleted(task) ? '恢复任务' : '完成任务'" @click="toggleCompleted(task)">
                <Check v-if="isCompleted(task)" />
              </button>
              <div class="task-primary-copy">
                <h3 :title="task.title">{{ task.title }}</h3>
                <span class="task-deadline" :class="{ danger: isOverdue(task) && !isCompleted(task) }">
                  <Clock />{{ deadlineText(task) }}
                </span>
              </div>
            </div>
            <div class="task-details">
              <p :class="{ empty: !task.notes }" :title="task.notes || '暂无补充说明'">
                {{ task.notes || '暂无补充说明' }}
              </p>
              <div class="task-detail-meta">
                <span class="priority-label" :style="{ '--priority-color': priorities[task.priority]?.color }">
                  {{ priorities[task.priority]?.label }}
                </span>
                <span v-if="task.reminderAt" class="reminder-label">
                  <Bell />{{ formatReminder(task.reminderAt) }} 提醒
                </span>
              </div>
            </div>
            <div class="task-actions">
              <el-button circle size="small" :icon="EditPen" title="编辑" @click="openEdit(task)" />
              <el-button circle size="small" :icon="Delete" title="删除" @click="removeTask(task)" />
            </div>
          </article>
        </div>

        <div v-else class="task-empty">
          <div class="empty-illustration"><Check /></div>
          <h3>{{ keyword ? '没有找到匹配的待办' : '这里已经清空了' }}</h3>
          <p>{{ keyword ? '换个关键词试试，或创建一条新待办。' : '记录下一件要做的事，让计划开始运转。' }}</p>
          <el-button v-if="!keyword" type="primary" plain :icon="Plus" @click="openCreate()">添加待办</el-button>
        </div>
      </section>

      <aside class="workbench-side">
        <section class="workbench-card calendar-card">
          <header class="calendar-head">
            <div>
              <span class="section-kicker">CALENDAR</span>
              <h2>{{ calendarTitle }}</h2>
            </div>
            <div class="calendar-nav">
              <button type="button" aria-label="上个月" @click="changeMonth(-1)">‹</button>
              <button type="button" @click="jumpToday">今</button>
              <button type="button" aria-label="下个月" @click="changeMonth(1)">›</button>
            </div>
          </header>
          <div class="calendar-weekdays"><span v-for="day in WEEKDAYS" :key="day">{{ day }}</span></div>
          <div class="calendar-grid">
            <button
              v-for="day in calendarDays"
              :key="day.key"
              type="button"
              :class="{ muted: !day.currentMonth, today: day.isToday, selected: day.isSelected, busy: day.taskCount, urgent: day.hasHigh }"
              @click="selectCalendarDay(day)"
            >
              <span>{{ day.day }}</span>
              <i v-if="day.taskCount">{{ day.completed }}/{{ day.taskCount }}</i>
            </button>
          </div>
          <div class="day-agenda">
            <div class="agenda-head">
              <div><b>{{ formatDate(selectedDate, true) }}</b><span>{{ selectedDayTasks.length }} 项安排</span></div>
              <el-button link type="primary" :icon="Plus" @click="openCreate(selectedDate)">添加</el-button>
            </div>
            <button v-for="task in selectedDayTasks.slice(0, 3)" :key="task.id" type="button" class="agenda-item" @click="openEdit(task)">
              <i :style="{ background: priorities[task.priority]?.color }" />
              <span :class="{ done: isCompleted(task) }">{{ task.title }}</span>
              <time>{{ task.dueTime || '全天' }}</time>
            </button>
            <div v-if="!selectedDayTasks.length" class="agenda-empty">这一天还没有安排</div>
          </div>
        </section>

        <section class="workbench-card reminder-card">
          <header>
            <div class="reminder-title"><span><Bell /></span><div><b>提醒中心</b><small>临近事项，及时处理</small></div></div>
            <el-tag size="small" effect="plain" round>{{ upcomingReminders.length }}</el-tag>
          </header>
          <div v-if="upcomingReminders.length" class="reminder-list">
            <button v-for="task in upcomingReminders" :key="task.id" type="button" @click="openEdit(task)">
              <span>{{ formatReminder(task.reminderAt) }}</span><b>{{ task.title }}</b>
            </button>
          </div>
          <div v-else class="reminder-empty">暂无即将触发的提醒</div>
          <button v-if="permissionState !== 'granted' && permissionState !== 'unsupported'" type="button" class="notification-link" @click="requestNotificationPermission">
            开启桌面通知，让提醒更及时 →
          </button>
        </section>
      </aside>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑待办' : '新建待办'" width="560px" destroy-on-close append-to-body class="task-dialog">
      <el-form ref="formRef" :model="form" :rules="formRules" label-position="top">
        <el-form-item label="待办事项" prop="title">
          <el-input v-model="form.title" maxlength="80" show-word-limit placeholder="例如：整理本周项目资料" @keyup.enter="submitTask" />
        </el-form-item>
        <el-form-item label="补充说明">
          <el-input v-model="form.notes" type="textarea" :rows="3" maxlength="300" show-word-limit placeholder="写下必要的背景、目标或备注…" />
        </el-form-item>
        <div class="dialog-form-grid">
          <el-form-item label="优先级">
            <el-select v-model="form.priority" style="width: 100%">
              <el-option v-for="(item, key) in priorities" :key="key" :label="item.label" :value="key" />
            </el-select>
          </el-form-item>
          <el-form-item label="截止日期">
            <el-date-picker v-model="form.dueDate" type="date" value-format="YYYY-MM-DD" format="YYYY年MM月DD日" style="width: 100%" :clearable="false" />
          </el-form-item>
          <el-form-item label="截止时间">
            <el-time-select v-model="form.dueTime" start="08:00" step="00:30" end="23:30" placeholder="可选" style="width: 100%" clearable />
          </el-form-item>
        </div>
        <div class="reminder-setting" :class="{ enabled: form.reminderEnabled }">
          <div class="reminder-setting-copy">
            <span><Bell /></span>
            <div><b>闹钟提醒</b><small>到达设定时间后发送站内与系统通知</small></div>
          </div>
          <el-switch v-model="form.reminderEnabled" />
        </div>
        <el-form-item v-if="form.reminderEnabled" label="提醒时间" class="reminder-time-field">
          <el-date-picker v-model="form.reminderAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY年MM月DD日 HH:mm" placeholder="选择提醒时间" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTask">{{ editingId ? '保存修改' : '创建待办' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.task-board-page { --wb-indigo: #4f46e5; --wb-navy: #172554; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 0 0 16px; }
.metric-card { position: relative; overflow: hidden; min-height: 98px; padding: 14px 16px; border: 1px solid #e2e8f0; border-radius: 15px; background: rgba(255,255,255,.92); box-shadow: 0 5px 16px rgba(15, 23, 42, .045); }
.metric-card > div:not(.metric-icon) { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.metric-card span { color: #475569; font-size: 13px; font-weight: 650; }
.metric-card strong { color: #0f172a; font-size: 25px; line-height: 1; }
.metric-card small { display: block; margin-top: 7px; color: #94a3b8; font-size: 11px; }
.metric-icon { display: grid; place-items: center; width: 28px; height: 28px; margin-bottom: 8px; border-radius: 9px; }
.metric-icon svg { width: 16px; }
.metric-indigo .metric-icon { color: #4f46e5; background: #eef2ff; }.metric-amber .metric-icon { color: #d97706; background: #fffbeb; }.metric-emerald .metric-icon { color: #059669; background: #ecfdf5; }.metric-rose .metric-icon { color: #dc2626; background: #fff1f2; }
.workbench-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(0, .82fr); gap: 16px; align-items: start; }
.workbench-side { display: grid; gap: 16px; }
.workbench-card { border: 1px solid #dde5ef; border-radius: 19px; background: rgba(255,255,255,.96); box-shadow: 0 10px 30px rgba(15, 23, 42, .055); }
.task-board { min-height: 540px; padding: 21px; }
.workbench-card-head,.calendar-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.workbench-card h2 { margin: 3px 0 0; color: #172554; font-size: 19px; letter-spacing: -.02em; }
.task-search { width: 100%; max-width: 240px; }
.task-filter-row { display: flex; gap: 5px; margin: 20px 0 12px; padding: 4px; border-radius: 11px; background: #f1f5f9; }
.task-filter-row button { flex: 1; min-height: 34px; padding: 5px 10px; border: 0; border-radius: 8px; background: transparent; color: #64748b; font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; transition: .15s ease; }
.task-filter-row button:hover { color: #312e81; }.task-filter-row button.active { color: #312e81; background: #fff; box-shadow: 0 2px 8px rgba(15,23,42,.08); }
.task-list { display: grid; gap: 8px; max-height: 418px; padding-right: 3px; overflow: auto; }
.task-item { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr) auto; gap: 14px; align-items: center; min-height: 66px; padding: 9px 12px; border: 1px solid #e7edf4; border-left: 3px solid #818cf8; border-radius: 11px; background: #fff; transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease; }
.task-item:hover { transform: translateY(-1px); border-color: #c7d2fe; box-shadow: 0 7px 18px rgba(30,41,59,.07); }.task-item.overdue { border-left-color: #ef4444; }.task-item.completed { opacity: .7; border-left-color: #94a3b8; }
.task-primary { display: grid; grid-template-columns: 22px minmax(0,1fr); gap: 10px; align-items: center; min-width: 0; }
.task-check { display: grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1.5px solid #cbd5e1; border-radius: 7px; background: #fff; color: #fff; cursor: pointer; }.task-check:hover { border-color: #6366f1; }.completed .task-check { border-color: #4f46e5; background: #4f46e5; }.task-check svg { width: 13px; }
.task-primary-copy { min-width: 0; }.task-primary-copy h3 { overflow: hidden; margin: 0 0 4px; color: #1e293b; font-size: 13px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }.completed .task-primary-copy h3 { text-decoration: line-through; color: #64748b; }
.task-deadline { display: inline-flex; align-items: center; gap: 4px; color: #94a3b8; font-size: 10px; }.task-deadline svg { width: 11px; }.task-deadline.danger { color: #dc2626; font-weight: 650; }
.task-details { min-width: 0; padding-left: 12px; }.task-details > p { overflow: hidden; margin: 0 0 5px; color: #475569; font-size: 11px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }.task-details > p.empty { color: #b0bac8; font-style: italic; }
.task-detail-meta { display: flex; align-items: center; gap: 10px; overflow: hidden; color: #94a3b8; font-size: 9px; white-space: nowrap; }.priority-label,.reminder-label { display: inline-flex; align-items: center; gap: 4px; }.priority-label::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: var(--priority-color); }.reminder-label { overflow: hidden; text-overflow: ellipsis; }.reminder-label svg { width: 10px; flex-shrink: 0; }
.task-actions { display: flex; gap: 5px; }.task-actions :deep(.el-button + .el-button) { margin-left: 0; }.task-actions :deep(.el-button) { width: 30px; height: 30px; min-height: 30px; }
.task-empty { display: grid; justify-items: center; padding: 82px 20px; text-align: center; }.empty-illustration { display: grid; place-items: center; width: 66px; height: 66px; border-radius: 22px; background: linear-gradient(135deg,#eef2ff,#e0e7ff); color: #6366f1; transform: rotate(-5deg); }.empty-illustration svg { width: 28px; }.task-empty h3 { margin: 20px 0 6px; font-size: 16px; color: #334155; }.task-empty p { margin: 0 0 18px; color: #94a3b8; font-size: 12px; }
.calendar-card { padding: 18px 20px; }.calendar-nav { display: flex; gap: 4px; }.calendar-nav button { width: 26px; height: 26px; padding: 0; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; color: #475569; font-size: 16px; line-height: 1; cursor: pointer; }.calendar-nav button:nth-child(2) { font-size: 10px; font-weight: 700; }.calendar-nav button:hover { color: #4338ca; border-color: #a5b4fc; background: #eef2ff; }
.calendar-weekdays,.calendar-grid { display: grid; grid-template-columns: repeat(7,1fr); gap: 2px; }.calendar-weekdays { margin: 13px 0 5px; color: #94a3b8; font-size: 10px; font-weight: 700; text-align: center; }
.calendar-grid button { position: relative; display: grid; justify-items: center; align-content: center; gap: 1px; height: 32px; min-width: 0; padding: 1px; border: 0; border-radius: 8px; background: transparent; color: #334155; font: inherit; font-size: 11px; cursor: pointer; }.calendar-grid button:hover { background: #f1f5f9; }.calendar-grid button.muted { color: #cbd5e1; }.calendar-grid button.today span { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 7px; color: #4338ca; background: #eef2ff; font-weight: 800; }.calendar-grid button.selected { color: #fff; background: #4338ca; box-shadow: 0 4px 9px rgba(67,56,202,.23); }.calendar-grid button.selected span { color: #fff; background: transparent; }.calendar-grid button i { color: #818cf8; font-size: 7px; font-style: normal; line-height: 1; }.calendar-grid button.selected i { color: #c7d2fe; }.calendar-grid button.urgent::after { content: ''; position: absolute; top: 3px; right: 3px; width: 4px; height: 4px; border-radius: 50%; background: #ef4444; }
.day-agenda { margin-top: 12px; padding-top: 11px; border-top: 1px solid #edf2f7; }.agenda-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; }.agenda-head > div { display: grid; }.agenda-head b { color: #334155; font-size: 12px; }.agenda-head span { color: #94a3b8; font-size: 10px; }.agenda-head :deep(.el-button) { min-height: 26px; }
.agenda-item { display: grid; grid-template-columns: 6px minmax(0,1fr) auto; align-items: center; gap: 8px; width: 100%; padding: 8px 5px; border: 0; border-radius: 7px; background: transparent; color: #475569; text-align: left; cursor: pointer; }.agenda-item:hover { background: #f8fafc; }.agenda-item i { width: 6px; height: 6px; border-radius: 50%; }.agenda-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }.agenda-item .done { text-decoration: line-through; color: #94a3b8; }.agenda-item time { color: #94a3b8; font-size: 10px; }.agenda-empty { padding: 11px 0 4px; color: #94a3b8; font-size: 11px; text-align: center; }
.reminder-card { overflow: hidden; padding: 19px 20px; background: linear-gradient(145deg,#172554,#1e1b4b); color: #fff; }.reminder-card > header { display: flex; align-items: center; justify-content: space-between; }.reminder-title { display: flex; align-items: center; gap: 10px; }.reminder-title > span { display: grid; place-items: center; width: 33px; height: 33px; border-radius: 10px; background: rgba(165,180,252,.16); color: #c7d2fe; }.reminder-title svg { width: 16px; }.reminder-title div { display: grid; }.reminder-title b { font-size: 13px; }.reminder-title small { margin-top: 2px; color: #a5b4fc; font-size: 10px; }.reminder-list { display: grid; gap: 5px; margin-top: 13px; }.reminder-list button { display: grid; grid-template-columns: 80px minmax(0,1fr); gap: 8px; width: 100%; padding: 8px 10px; border: 1px solid rgba(255,255,255,.08); border-radius: 9px; background: rgba(255,255,255,.06); color: #e0e7ff; text-align: left; cursor: pointer; }.reminder-list button:hover { background: rgba(255,255,255,.1); }.reminder-list span { color: #a5b4fc; font-size: 10px; }.reminder-list b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }.reminder-empty { padding: 18px 0 7px; color: #a5b4fc; font-size: 11px; text-align: center; }.notification-link { width: 100%; margin-top: 11px; padding: 7px; border: 0; border-top: 1px solid rgba(255,255,255,.09); background: transparent; color: #c7d2fe; font-size: 10px; cursor: pointer; }
.dialog-form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 12px; }.reminder-setting { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; padding: 13px 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #f8fafc; }.reminder-setting.enabled { border-color: #c7d2fe; background: #eef2ff; }.reminder-setting-copy { display: flex; align-items: center; gap: 10px; }.reminder-setting-copy > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: #fff; color: #4f46e5; }.reminder-setting-copy svg { width: 15px; }.reminder-setting-copy div { display: grid; }.reminder-setting-copy b { color: #334155; font-size: 12px; }.reminder-setting-copy small { color: #94a3b8; font-size: 10px; }.reminder-time-field { margin-top: 15px; }
@media (max-width: 1180px) { .metric-grid { grid-template-columns: repeat(2,1fr); }.workbench-grid { grid-template-columns: minmax(0,1fr) 320px; } }
@media (max-width: 850px) { .workbench-grid { grid-template-columns: 1fr; }.task-board { min-height: 480px; }.workbench-side { grid-template-columns: minmax(310px,1fr) minmax(260px,.8fr); } }
@media (max-width: 620px) { .metric-grid { grid-template-columns: 1fr 1fr; }.metric-card { min-height: 94px; padding: 13px; }.workbench-side { grid-template-columns: 1fr; }.workbench-card-head { align-items: stretch; flex-direction: column; }.task-search { width: 100%; }.task-board { padding: 17px; }.task-filter-row { overflow-x: auto; }.task-filter-row button { flex: 0 0 auto; }.task-item { grid-template-columns: minmax(0,1fr) auto; gap: 8px 10px; }.task-details { grid-column: 1 / -1; grid-row: 2; padding: 7px 0 0 32px; border-top: 1px solid #edf2f7; border-left: 0; }.task-actions { grid-column: 2; grid-row: 1; }.dialog-form-grid { grid-template-columns: 1fr; } }

/* 容器查询：组件被放入较窄的列时（列宽 ≤ 620px），内部两栏堆叠为单列、
   4 张统计卡降为 2×2，保证日历/提醒移至列表下方且不丢失功能。
   视口较宽但单栏较窄时视口媒体查询不会触发，因此以容器查询为准。 */
@container (max-width: 620px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workbench-grid { grid-template-columns: 1fr; }
  .workbench-side { grid-template-columns: 1fr; }
  .task-board { min-height: auto; }
}
@container (max-width: 420px) {
  .metric-grid { grid-template-columns: 1fr; }
}
</style>
