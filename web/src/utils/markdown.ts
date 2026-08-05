import MarkdownIt from 'markdown-it'

// 渲染配置：与后端 mistune 导出的 Markdown 语义接近（标题/粗体/斜体/列表/引用/链接）。
// html:false —— 不渲染原始 HTML，纯展示样式（font/color/align）随 Markdown 丢弃，
// 与「样式默认不保留」决议一致，也避免前端 XSS。
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

/**
 * 将 Markdown 渲染为 HTML 字符串（用于项目详情/预览渲染）。
 */
export function renderMarkdown(source: string): string {
  return md.render(source || '')
}

/**
 * 从 Markdown 提取纯文本（字数统计 / 判空使用）。
 * 先渲染为 HTML，再剥离标签，与后端 html_to_plain_text 口径对齐。
 */
export function mdToPlainText(source: string): string {
  const html = md.render(source || '')
  const div = document.createElement('div')
  div.innerHTML = html
  return (div.textContent || div.innerText || '')
    .replace(/ /g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
