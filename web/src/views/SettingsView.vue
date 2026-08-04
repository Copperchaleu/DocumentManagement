<script setup>
import { onActivated, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  browseFolder,
  createDatabaseBackup,
  databaseBackupDownloadUrl,
  deleteDatabaseBackup,
  getDatabaseBackupSettings,
  listDatabaseBackups,
  openDatabaseBackupFolder,
  updateDatabaseBackupSettings,
} from '../api'
import { toastError } from '../api/http'

const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const openingFolder = ref(false)
const backups = ref([])
const database = ref({})
const summary = ref({})

const form = reactive({
  enabled: true,
  directory: 'data/backups',
  resolvedDirectory: '',
  intervalHours: 24,
  maxBackups: 7,
})

function formatBytes(value) {
  const size = Number(value || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function applySettingsPayload(data) {
  const settings = data?.settings || {}
  form.enabled = settings.enabled ?? true
  form.directory = settings.directory || 'data/backups'
  form.resolvedDirectory = settings.resolved_directory || ''
  form.intervalHours = Number(settings.interval_hours || 24)
  form.maxBackups = Number(settings.max_backups || 7)
  database.value = data?.database || {}
  summary.value = data?.summary || {}
}

async function refreshBackups() {
  const data = await listDatabaseBackups()
  backups.value = data.items || []
}

async function loadAll() {
  if (loading.value) return
  loading.value = true
  try {
    const [settingsData, backupsData] = await Promise.all([
      getDatabaseBackupSettings(),
      listDatabaseBackups(),
    ])
    applySettingsPayload(settingsData)
    backups.value = backupsData.items || []
  } catch (e) {
    toastError(e, '读取数据库备份设置失败')
  } finally {
    loading.value = false
  }
}

async function chooseDirectory() {
  try {
    const data = await browseFolder(form.resolvedDirectory || form.directory, 'backup')
    if (data?.ok && data.path) {
      form.directory = data.path
      form.resolvedDirectory = data.path
    }
  } catch (e) {
    toastError(e, '选择备份目录失败')
  }
}

async function saveSettings() {
  const directory = String(form.directory || '').trim()
  if (!directory) {
    ElMessage.error('请设置数据库备份目录')
    return
  }
  const maxBackups = Number(form.maxBackups)
  const intervalHours = Number(form.intervalHours)
  if (!Number.isInteger(maxBackups) || maxBackups < 1) {
    ElMessage.error('最大备份数必须是大于 0 的整数')
    return
  }
  if (!Number.isInteger(intervalHours) || intervalHours < 1) {
    ElMessage.error('备份间隔必须是大于 0 的整数小时')
    return
  }

  try {
    if (maxBackups < backups.value.length) {
      await ElMessageBox.confirm(
        `当前有 ${backups.value.length} 份备份，保存后将删除最旧的 ${backups.value.length - maxBackups} 份。是否继续？`,
        '缩减备份数量',
        { type: 'warning' },
      )
    }
    saving.value = true
    const data = await updateDatabaseBackupSettings({
      enabled: form.enabled,
      directory,
      interval_hours: intervalHours,
      max_backups: maxBackups,
    })
    applySettingsPayload(data)
    await refreshBackups()
    ElMessage.success(
      data.removed_count ? `设置已保存，并清理 ${data.removed_count} 份旧备份` : '设置已保存',
    )
  } catch (e) {
    if (e !== 'cancel') toastError(e, '保存数据库备份设置失败')
  } finally {
    saving.value = false
  }
}

async function createBackup() {
  if (creating.value) return
  creating.value = true
  try {
    const data = await createDatabaseBackup()
    ElMessage.success(`数据库备份已创建：${data.backup?.filename || ''}`)
    await loadAll()
  } catch (e) {
    toastError(e, '创建数据库备份失败')
  } finally {
    creating.value = false
  }
}

async function openBackupFolder() {
  openingFolder.value = true
  try {
    await openDatabaseBackupFolder()
    ElMessage.success('已请求打开数据库备份目录')
  } catch (e) {
    toastError(e, '打开数据库备份目录失败')
  } finally {
    openingFolder.value = false
  }
}

async function removeBackup(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除数据库备份「${row.filename}」？删除后无法恢复。`,
      '删除数据库备份',
      { type: 'warning' },
    )
    await deleteDatabaseBackup(row.filename)
    ElMessage.success('备份已删除')
    await loadAll()
  } catch (e) {
    if (e !== 'cancel') toastError(e, '删除数据库备份失败')
  }
}

onActivated(loadAll)
</script>

<template>
  <div class="settings-page" v-loading="loading">
    <section class="panel settings-panel">
      <div class="panel-head">
        <div class="title-area">
          <div class="title-row">
            <h2>系统设置</h2>
            <el-tag type="info" effect="plain" round>数据库备份</el-tag>
          </div>
        </div>
        <div class="toolbar-row">
          <el-button :loading="openingFolder" @click="openBackupFolder">打开备份目录</el-button>
          <el-button type="primary" :loading="creating" @click="createBackup">立即备份</el-button>
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-card">
          <span>当前数据库</span>
          <strong>{{ formatBytes(database.size) }}</strong>
          <small :title="database.path">{{ database.path || '—' }}</small>
        </div>
        <div class="summary-card">
          <span>已有备份</span>
          <strong>{{ summary.backup_count || 0 }} 份</strong>
          <small>共 {{ formatBytes(summary.total_size) }}</small>
        </div>
        <div class="summary-card">
          <span>最近备份</span>
          <strong class="summary-time">{{ summary.latest_backup_at || '尚无备份' }}</strong>
          <small>数据库更新：{{ database.modified_at || '—' }}</small>
        </div>
      </div>

      <el-form class="backup-form" label-position="top">
        <el-row :gutter="18">
          <el-col :xs="24" :md="8">
            <el-form-item label="自动备份">
              <div class="switch-line">
                <el-switch v-model="form.enabled" />
                <span>{{ form.enabled ? '已启用' : '已停用（仍可手动备份）' }}</span>
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="12" :md="8">
            <el-form-item label="备份间隔（小时）">
              <el-input-number
                v-model="form.intervalHours"
                :min="1"
                :max="8760"
                :step="1"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :md="8">
            <el-form-item label="最大备份数">
              <el-input-number
                v-model="form.maxBackups"
                :min="1"
                :max="1000"
                :step="1"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="备份目录">
          <div class="directory-row">
            <el-input v-model="form.directory" placeholder="例如：data/backups 或外部绝对路径" />
            <el-button @click="chooseDirectory">选择目录</el-button>
          </div>
          <div class="resolved-path" :title="form.resolvedDirectory">
            实际目录：{{ form.resolvedDirectory || form.directory || '—' }}
          </div>
        </el-form-item>

        <div class="settings-actions">
          <div class="settings-note">
            服务每分钟检查一次，到达间隔后自动备份。修改目录不会搬移旧目录中的备份。
          </div>
          <el-button type="primary" :loading="saving" @click="saveSettings">保存设置</el-button>
        </div>
      </el-form>
    </section>

    <section class="panel backup-list-panel">
      <div class="panel-head compact-head">
        <div class="title-row">
          <h2>备份文件</h2>
          <el-tag type="info" effect="plain" round>{{ backups.length }} 份</el-tag>
        </div>
        <el-button @click="loadAll">刷新</el-button>
      </div>

      <el-table :data="backups" border stripe empty-text="暂无数据库备份">
        <el-table-column prop="filename" label="文件名" min-width="260">
          <template #default="{ row }">
            <span class="backup-name" :title="row.path">{{ row.filename }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="modified_at" label="备份时间" min-width="160" />
        <el-table-column label="大小" width="110" align="right">
          <template #default="{ row }">{{ formatBytes(row.size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" align="center" fixed="right">
          <template #default="{ row }">
            <div class="backup-ops">
              <a
                class="download-link"
                :href="databaseBackupDownloadUrl(row.filename)"
                target="_blank"
              >下载</a>
              <el-button type="danger" plain size="small" @click="removeBackup(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 18px;
}

.settings-panel,
.backup-list-panel {
  min-width: 0;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.summary-card {
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #f8fafc;
  min-width: 0;
}

.summary-card span,
.summary-card small {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.summary-card strong {
  display: block;
  margin: 7px 0 6px;
  color: #0f172a;
  font-size: 22px;
  line-height: 1.2;
}

.summary-card .summary-time {
  font-size: 16px;
  line-height: 26px;
}

.summary-card small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backup-form {
  padding: 18px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #fff;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  color: #475569;
  font-size: 13px;
}

.directory-row {
  display: flex;
  width: 100%;
  gap: 10px;
}

.resolved-path {
  width: 100%;
  margin-top: 7px;
  color: #64748b;
  font-family: var(--font-mono, Consolas, monospace);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.settings-note {
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.compact-head {
  align-items: center;
}

.backup-name {
  color: #334155;
  font-family: var(--font-mono, Consolas, monospace);
  font-size: 12.5px;
}

.backup-ops {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.download-link {
  color: #4f46e5;
  font-size: 13px;
  font-weight: 650;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .settings-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
