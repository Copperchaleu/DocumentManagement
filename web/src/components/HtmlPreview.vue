<script setup lang="ts">
import { computed } from 'vue'
import { sanitizeHtml } from '../utils/html'

const props = defineProps<{
  /** HTML 源文本（将经白名单 sanitize 后渲染） */
  content?: string
}>()

const safeHtml = computed(() => sanitizeHtml(props.content || ''))
</script>

<template>
  <div class="html-preview" v-html="safeHtml"></div>
</template>

<style scoped>
.html-preview {
  width: 100%;
  min-height: 60px;
  max-height: 420px;
  overflow: auto;
  line-height: 1.75;
  color: #1e293b;
  font-family: var(--font-sans, system-ui, sans-serif);
  word-break: break-word;
}

.html-preview :deep(h1),
.html-preview :deep(h2),
.html-preview :deep(h3),
.html-preview :deep(h4),
.html-preview :deep(h5),
.html-preview :deep(h6) {
  margin: 0.6em 0 0.4em;
  line-height: 1.3;
  font-weight: 700;
  color: #0f172a;
}

.html-preview :deep(h1) {
  font-size: 1.5em;
}
.html-preview :deep(h2) {
  font-size: 1.3em;
}
.html-preview :deep(h3) {
  font-size: 1.15em;
}

.html-preview :deep(p) {
  margin: 0.5em 0;
}

.html-preview :deep(ul),
.html-preview :deep(ol) {
  padding-left: 1.4em;
  margin: 0.5em 0;
}

.html-preview :deep(blockquote) {
  margin: 0.6em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #c7d2fe;
  background: #f8fafc;
  color: #475569;
}

.html-preview :deep(a) {
  color: #4f46e5;
  text-decoration: underline;
}

.html-preview :deep(code) {
  background: #f1f5f9;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.92em;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
}

.html-preview :deep(pre) {
  background: #f1f5f9;
  padding: 0.8em 1em;
  border-radius: 8px;
  overflow: auto;
}

.html-preview :deep(pre code) {
  background: transparent;
  padding: 0;
}

.html-preview :deep(u) {
  text-decoration: underline;
}

.html-preview :deep(s),
.html-preview :deep(del),
.html-preview :deep(strike) {
  text-decoration: line-through;
}
</style>
