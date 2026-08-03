// 安全清理 dist 目录（避免 trash 插件被阻塞导致构建失败）
import { rmSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const dist = resolve(process.cwd(), '../frontend/dist')
if (existsSync(dist)) {
  try {
    rmSync(dist, { recursive: true, force: true })
    console.log('[clean] dist removed')
  } catch (e) {
    console.warn('[clean] 未能完全删除 dist，尝试逐层清理')
    // 逐层尝试
    const assets = resolve(dist, 'assets')
    ;[assets, resolve(dist, 'index.html')].forEach(p => {
      try { rmSync(p, { recursive: true, force: true }) } catch {}
    })
  }
}
console.log('[clean] done')