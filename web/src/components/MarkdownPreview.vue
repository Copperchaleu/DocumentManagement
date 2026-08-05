<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  /** Markdown 源文本 */
  content?: string
}>()

const renderedHtml = computed(() => renderMarkdown(props.content || ''))
</script>

<template>
  <div class="markdown-preview" v-html="renderedHtml"></div>
</template>

<style scoped>
.markdown-preview {
  width: 100%;
  min-height: 60px;
  max-height: 420px;
  overflow: auto;
  line-height: 1.75;
  color: #1e293b;
  font-family: var(--font-sans, system-ui, sans-serif);
  word-break: break-word;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3),
.markdown-preview :deep(h4),
.markdown-preview :deep(h5),
.markdown-preview :deep(h6) {
  margin: 0.6em 0 0.4em;
  line-height: 1.3;
  font-weight: 700;
  color: #0f172a;
}

.markdown-preview :deep(h1) {
  font-size: 1.5em;
}
.markdown-preview :deep(h2) {
  font-size: 1.3em;
}
.markdown-preview :deep(h3) {
  font-size: 1.15em;
}

.markdown-preview :deep(p) {
  margin: 0.5em 0;
}

.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  padding-left: 1.4em;
  margin: 0.5em 0;
}

.markdown-preview :deep(blockquote) {
  margin: 0.6em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #c7d2fe;
  background: #f8fafc;
  color: #475569;
}

.markdown-preview :deep(a) {
  color: #4f46e5;
  text-decoration: underline;
}

.markdown-preview :deep(code) {
  background: #f1f5f9;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.92em;
}

.markdown-preview :deep(pre) {
  background: #f1f5f9;
  padding: 0.8em 1em;
  border-radius: 8px;
  overflow: auto;
}

.markdown-preview :deep(pre code) {
  background: transparent;
  padding: 0;
}

.markdown-preview :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
}

.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 0.35em 0.6em;
}
</style>
