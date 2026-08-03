import http from './http'

export const getHealth = () => http.get('/api/health')
export const getTimeInfo = () => http.get('/api/time-info')
export const getConfig = () => http.get('/api/config')

export const listCategories = (params = {}) => http.get('/api/categories', { params })
export const createCategory = (data) => http.post('/api/categories', data)
export const updateCategory = (id, data) => http.put(`/api/categories/${id}`, data)
export const deleteCategory = (id) => http.delete(`/api/categories/${id}`)
export const openCategoryFolder = (id) => http.post(`/api/categories/${id}/open-folder`)
export const browseFolder = (initialPath) =>
  http.post('/api/browse-folder', null, {
    params: initialPath ? { initial_path: initialPath } : {},
  })

export const listProjects = (params = {}) => http.get('/api/projects', { params })
export const getProject = (id) => http.get(`/api/projects/${id}`)
export const deleteProject = (id) => http.delete(`/api/projects/${id}`)
export const autosaveProject = (data) => http.post('/api/projects/autosave', data)

export function saveProject(formData) {
  return http.post('/api/projects', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const listPeriodFiles = (params = {}) => http.get('/api/period-files', { params })
export function openPeriodFile({ category_id, period_type, period_label }) {
  const fd = new FormData()
  fd.append('category_id', category_id)
  fd.append('period_type', period_type)
  fd.append('period_label', period_label)
  return http.post('/api/period-files/open', fd)
}

export function periodDownloadUrl({ category_id, period_type, period_label }) {
  const qs = new URLSearchParams({
    category_id,
    period_type,
    period_label,
  })
  return `/api/period-files/download?${qs.toString()}`
}

export function attachmentDownloadUrl(id) {
  return `/api/attachments/${id}/download`
}
