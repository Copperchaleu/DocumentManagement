import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '',
  timeout: 120000,
})

function extractErrorMessage(error) {
  const status = error?.response?.status
  const data = error?.response?.data
  if (!data) {
    if (status === 423) return 'Word 文件正在被打开，请先关闭后再保存'
    if (status >= 500) return '服务器内部错误，请稍后重试'
    return error?.message || '请求失败'
  }
  if (typeof data === 'string') {
    if (/internal server error/i.test(data)) {
      return '服务器内部错误。若刚打开了 Word，请先关闭对应 Word 文件后再保存。'
    }
    return data
  }
  const detail = data.detail ?? data.message ?? data.error
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((x) => (typeof x === 'string' ? x : x.msg || JSON.stringify(x))).join('；')
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail)
  }
  try {
    return JSON.stringify(data)
  } catch {
    return `请求失败 ${status || ''}`.trim()
  }
}

http.interceptors.response.use(
  (res) => res.data,
  (error) => {
    const msg = extractErrorMessage(error)
    error.friendlyMessage = msg
    return Promise.reject(error)
  },
)

export function toastError(error, fallback = '操作失败') {
  const msg = error?.friendlyMessage || extractErrorMessage(error) || fallback
  ElMessage.error({ message: msg, duration: 6000, showClose: true })
  return msg
}

export default http
