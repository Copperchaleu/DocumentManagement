/**
 * HTML 工具：纯文本提取与白名单安全清洗。
 * 口径对齐后端 get_plain_text / html_to_plain_text。
 */

/** Tiptap 产出 + 预览允许的标签白名单（见设计 §9.3） */
const ALLOWED_TAGS = new Set([
  'P',
  'BR',
  'STRONG',
  'B',
  'EM',
  'I',
  'U',
  'S',
  'DEL',
  'STRIKE',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'UL',
  'OL',
  'LI',
  'BLOCKQUOTE',
  'PRE',
  'CODE',
  'A',
  'SPAN',
  'DIV',
])

/** a 标签允许的属性 */
const ALLOWED_A_ATTRS = new Set(['href', 'title', 'target', 'rel'])

/**
 * 将 HTML 提取为可见纯文本（字数统计 / 判空）。
 * 与后端 html_to_plain_text 口径一致：忽略标签噪声。
 */
export function htmlToPlainText(html: string): string {
  if (typeof document === 'undefined') {
    return String(html || '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/gi, ' ')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
      .replace(/&amp;/gi, '&')
      .replace(/\s+/g, ' ')
      .trim()
  }
  const div = document.createElement('div')
  div.innerHTML = html || ''
  return (div.textContent || div.innerText || '')
    .replace(/\u00a0/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/**
 * 是否允许的链接地址：http(s) / mailto / 锚点 / 相对路径；禁止 javascript:。
 */
export function isSafeHref(href: string): boolean {
  const value = (href || '').trim()
  if (!value) return false
  const lower = value.toLowerCase()
  if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:')) {
    return false
  }
  return true
}

/**
 * 轻量白名单 sanitize：剥离 script/iframe/事件属性与危险 URL。
 * 不依赖 DOMPurify，供 HtmlPreview 与编辑器预览态使用。
 */
export function sanitizeHtml(html: string): string {
  if (!html) return ''
  if (typeof document === 'undefined') {
    return String(html)
      .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
      .replace(/on\w+\s*=\s*(['"]).*?\1/gi, '')
      .replace(/javascript:/gi, '')
  }

  const template = document.createElement('template')
  template.innerHTML = html

  const walk = (node: Node): void => {
    const children = Array.from(node.childNodes)
    for (const child of children) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const el = child as HTMLElement
        const tag = el.tagName.toUpperCase()

        if (!ALLOWED_TAGS.has(tag)) {
          // 保留文本子节点，移除危险/未知标签外壳
          const parent = el.parentNode
          if (parent) {
            while (el.firstChild) {
              parent.insertBefore(el.firstChild, el)
            }
            parent.removeChild(el)
          }
          continue
        }

        // 剥离全部 on* 事件与 style 表达式
        const attrs = Array.from(el.attributes)
        for (const attr of attrs) {
          const name = attr.name.toLowerCase()
          if (name.startsWith('on') || name === 'style' || name === 'src' || name === 'srcset') {
            el.removeAttribute(attr.name)
            continue
          }
          if (tag === 'A') {
            if (!ALLOWED_A_ATTRS.has(name)) {
              el.removeAttribute(attr.name)
              continue
            }
            if (name === 'href' && !isSafeHref(attr.value)) {
              el.removeAttribute('href')
            }
          } else if (name === 'href' || name === 'target' || name === 'rel') {
            // 非 a 标签不保留链接相关属性
            el.removeAttribute(attr.name)
          }
        }

        if (tag === 'A') {
          const href = el.getAttribute('href') || ''
          if (href && !isSafeHref(href)) {
            el.removeAttribute('href')
          }
          // 外链安全默认
          if (el.getAttribute('target') === '_blank') {
            el.setAttribute('rel', 'noopener noreferrer')
          }
        }

        walk(el)
      } else if (child.nodeType === Node.COMMENT_NODE) {
        child.parentNode?.removeChild(child)
      }
    }
  }

  walk(template.content)
  return template.innerHTML
}
