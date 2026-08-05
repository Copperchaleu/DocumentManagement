import http from './http'

// 用户隔离维度：首次访问生成并持久化到 localStorage 的 UUID。
// 后端以 query 参数 user_key 接收，缺省 'default'。
const USER_KEY_STORAGE = 'document-management-user-key'

/**
 * 取（首次生成并缓存）当前浏览器的工作面板用户标识。
 * 仅生成、不主动重置，保证同一浏览器数据跨会话一致。
 */
export function getUserKey() {
  let key = localStorage.getItem(USER_KEY_STORAGE)
  if (!key) {
    key =
      globalThis.crypto?.randomUUID?.() ||
      `${Date.now()}-${Math.random().toString(16).slice(2)}`
    localStorage.setItem(USER_KEY_STORAGE, key)
  }
  return key
}

// 把 user_key 合并进请求参数，所有工作面板接口统一携带。
const withUser = (params) => ({ ...(params || {}), user_key: getUserKey() })

export const getTasks = () => http.get('/api/workbench/tasks', { params: withUser() })
export const createTask = (task) =>
  http.post('/api/workbench/tasks', task, { params: withUser() })
export const updateTask = (id, patch) =>
  http.put(`/api/workbench/tasks/${id}`, patch, { params: withUser() })
export const deleteTask = (id) =>
  http.delete(`/api/workbench/tasks/${id}`, { params: withUser() })

export const getNotes = () => http.get('/api/workbench/notes', { params: withUser() })
export const createNote = (note) =>
  http.post('/api/workbench/notes', note, { params: withUser() })
export const updateNote = (id, patch) =>
  http.put(`/api/workbench/notes/${id}`, patch, { params: withUser() })
export const deleteNote = (id) =>
  http.delete(`/api/workbench/notes/${id}`, { params: withUser() })

export const migrateWorkbench = ({ tasks, notes }) =>
  http.post('/api/workbench/migrate', { user_key: getUserKey(), tasks, notes })
