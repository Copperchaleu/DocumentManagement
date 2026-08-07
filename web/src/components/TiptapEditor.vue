<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { useEditor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isSafeHref, sanitizeHtml } from '../utils/html'

const props = withDefaults(
  defineProps<{
    /** HTML 字符串 v-model */
    modelValue?: string
    placeholder?: string
    editable?: boolean
  }>(),
  {
    modelValue: '',
    placeholder: '在此撰写该项目的相关信息…',
    editable: true,
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', html: string): void
  (e: 'change'): void
}>()

const isPreview = ref(false)
const isFullscreen = ref(false)
const rootRef = ref<HTMLElement | null>(null)

/** 事务计数：驱动工具栏 isActive / canUndo 在选择与历史变化时刷新 */
const editorTick = ref(0)

const editor = useEditor({
  content: props.modelValue || '',
  editable: props.editable && !isPreview.value,
  extensions: [
    // StarterKit v3 已内置 link/underline，显式关闭以免与独立扩展 name 冲突
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      link: false,
      underline: false,
    }),
    Underline,
    Link.configure({
      openOnClick: false,
      autolink: true,
      linkOnPaste: true,
      HTMLAttributes: {
        rel: 'noopener noreferrer',
      },
      validate: (href: string) => isSafeHref(href),
    }),
    Placeholder.configure({
      placeholder: props.placeholder,
    }),
  ],
  editorProps: {
    attributes: {
      class: 'tiptap-prose',
    },
  },
  onUpdate: ({ editor: ed }) => {
    const html = ed.getHTML()
    emit('update:modelValue', html)
    emit('change')
  },
  onTransaction: () => {
    editorTick.value += 1
  },
  onSelectionUpdate: () => {
    editorTick.value += 1
  },
})

const previewHtml = computed(() => sanitizeHtml(props.modelValue || editor.value?.getHTML() || ''))

watch(
  () => props.modelValue,
  (next) => {
    const ed = editor.value
    if (!ed) return
    const incoming = next || ''
    // 仅当与当前 getHTML 不同时才 setContent，避免打断光标
    if (incoming !== ed.getHTML()) {
      ed.commands.setContent(incoming, { emitUpdate: false })
    }
  },
)

watch(
  () => props.editable,
  (val) => {
    editor.value?.setEditable(Boolean(val) && !isPreview.value)
  },
)

watch(isPreview, (preview) => {
  editor.value?.setEditable(Boolean(props.editable) && !preview)
})

function run(command: () => boolean | void) {
  if (!editor.value || isPreview.value) return
  command()
}

function toggleBold() {
  run(() => editor.value!.chain().focus().toggleBold().run())
}
function toggleItalic() {
  run(() => editor.value!.chain().focus().toggleItalic().run())
}
function toggleUnderline() {
  run(() => editor.value!.chain().focus().toggleUnderline().run())
}
function toggleStrike() {
  run(() => editor.value!.chain().focus().toggleStrike().run())
}
function toggleCode() {
  run(() => editor.value!.chain().focus().toggleCode().run())
}
function setHeading(level: 1 | 2 | 3) {
  run(() => editor.value!.chain().focus().toggleHeading({ level }).run())
}
function toggleBlockquote() {
  run(() => editor.value!.chain().focus().toggleBlockquote().run())
}
function toggleBulletList() {
  run(() => editor.value!.chain().focus().toggleBulletList().run())
}
function toggleOrderedList() {
  run(() => editor.value!.chain().focus().toggleOrderedList().run())
}
function toggleCodeBlock() {
  run(() => editor.value!.chain().focus().toggleCodeBlock().run())
}
function undo() {
  run(() => editor.value!.chain().focus().undo().run())
}
function redo() {
  run(() => editor.value!.chain().focus().redo().run())
}

async function setLink() {
  const ed = editor.value
  if (!ed || isPreview.value) return

  const previous = ed.getAttributes('link').href || ''
  try {
    const { value } = await ElMessageBox.prompt('请输入链接地址（http(s) / mailto / 相对路径）', '插入链接', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: previous,
      inputPlaceholder: 'https://example.com',
      distinguishCancelAndClose: true,
    })
    const href = (value || '').trim()
    if (!href) {
      ed.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    if (!isSafeHref(href)) {
      ElMessage.error('不允许的链接协议（如 javascript:）')
      return
    }
    ed.chain().focus().extendMarkRange('link').setLink({ href }).run()
  } catch {
    // 取消
  }
}

function unsetLink() {
  run(() => editor.value!.chain().focus().extendMarkRange('link').unsetLink().run())
}

function togglePreview() {
  isPreview.value = !isPreview.value
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isFullscreen.value) {
    isFullscreen.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  editor.value?.destroy()
})

function isActive(name: string, attrs?: Record<string, unknown>) {
  // 依赖 editorTick，确保光标/标记变化后工具栏激活态刷新
  void editorTick.value
  return editor.value?.isActive(name, attrs) ?? false
}

const canUndo = computed(() => {
  void editorTick.value
  return editor.value?.can().chain().focus().undo().run() ?? false
})
const canRedo = computed(() => {
  void editorTick.value
  return editor.value?.can().chain().focus().redo().run() ?? false
})
</script>

<template>
  <div
    ref="rootRef"
    class="tiptap-editor"
    :class="{ 'is-fullscreen': isFullscreen, 'is-preview': isPreview }"
  >
    <div class="tiptap-toolbar" role="toolbar" aria-label="格式工具栏">
      <button
        type="button"
        class="tb-btn"
        title="粗体"
        :class="{ active: isActive('bold') }"
        :disabled="isPreview"
        @click="toggleBold"
      >
        <strong>B</strong>
      </button>
      <button
        type="button"
        class="tb-btn"
        title="斜体"
        :class="{ active: isActive('italic') }"
        :disabled="isPreview"
        @click="toggleItalic"
      >
        <em>I</em>
      </button>
      <button
        type="button"
        class="tb-btn"
        title="下划线"
        :class="{ active: isActive('underline') }"
        :disabled="isPreview"
        @click="toggleUnderline"
      >
        <span class="u">U</span>
      </button>
      <button
        type="button"
        class="tb-btn"
        title="删除线"
        :class="{ active: isActive('strike') }"
        :disabled="isPreview"
        @click="toggleStrike"
      >
        <span class="s">S</span>
      </button>
      <button
        type="button"
        class="tb-btn"
        title="行内代码"
        :class="{ active: isActive('code') }"
        :disabled="isPreview"
        @click="toggleCode"
      >
        &lt;/&gt;
      </button>

      <span class="tb-sep" />

      <button
        type="button"
        class="tb-btn"
        title="标题 1"
        :class="{ active: isActive('heading', { level: 1 }) }"
        :disabled="isPreview"
        @click="setHeading(1)"
      >
        H1
      </button>
      <button
        type="button"
        class="tb-btn"
        title="标题 2"
        :class="{ active: isActive('heading', { level: 2 }) }"
        :disabled="isPreview"
        @click="setHeading(2)"
      >
        H2
      </button>
      <button
        type="button"
        class="tb-btn"
        title="标题 3"
        :class="{ active: isActive('heading', { level: 3 }) }"
        :disabled="isPreview"
        @click="setHeading(3)"
      >
        H3
      </button>
      <button
        type="button"
        class="tb-btn"
        title="引用"
        :class="{ active: isActive('blockquote') }"
        :disabled="isPreview"
        @click="toggleBlockquote"
      >
        ❝
      </button>
      <button
        type="button"
        class="tb-btn"
        title="无序列表"
        :class="{ active: isActive('bulletList') }"
        :disabled="isPreview"
        @click="toggleBulletList"
      >
        •≡
      </button>
      <button
        type="button"
        class="tb-btn"
        title="有序列表"
        :class="{ active: isActive('orderedList') }"
        :disabled="isPreview"
        @click="toggleOrderedList"
      >
        1.
      </button>
      <button
        type="button"
        class="tb-btn"
        title="代码块"
        :class="{ active: isActive('codeBlock') }"
        :disabled="isPreview"
        @click="toggleCodeBlock"
      >
        { }
      </button>

      <span class="tb-sep" />

      <button
        type="button"
        class="tb-btn"
        title="插入/编辑链接"
        :class="{ active: isActive('link') }"
        :disabled="isPreview"
        @click="setLink"
      >
        🔗
      </button>
      <button type="button" class="tb-btn" title="取消链接" :disabled="isPreview || !isActive('link')" @click="unsetLink">
        取消链
      </button>

      <span class="tb-sep" />

      <button type="button" class="tb-btn" title="撤销" :disabled="isPreview || !canUndo" @click="undo">↺</button>
      <button type="button" class="tb-btn" title="重做" :disabled="isPreview || !canRedo" @click="redo">↻</button>

      <span class="tb-sep" />

      <button type="button" class="tb-btn" title="预览" :class="{ active: isPreview }" @click="togglePreview">
        {{ isPreview ? '编辑' : '预览' }}
      </button>
      <button
        type="button"
        class="tb-btn"
        title="全屏"
        :class="{ active: isFullscreen }"
        @click="toggleFullscreen"
      >
        {{ isFullscreen ? '退出全屏' : '全屏' }}
      </button>
    </div>

    <div class="tiptap-body">
      <EditorContent v-show="!isPreview" :editor="editor" class="tiptap-content" />
      <div v-show="isPreview" class="tiptap-preview" v-html="previewHtml"></div>
    </div>
  </div>
</template>

<style scoped>
.tiptap-editor {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 480px;
  height: 480px;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
}

.tiptap-editor.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 4000;
  height: 100vh;
  min-height: 100vh;
  border-radius: 0;
  box-shadow: 0 0 0 1px #e2e8f0;
}

.tiptap-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.tb-btn {
  min-width: 32px;
  height: 30px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.12s ease,
    border-color 0.12s ease,
    color 0.12s ease;
}

.tb-btn:hover:not(:disabled) {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #3730a3;
}

.tb-btn.active {
  background: #e0e7ff;
  border-color: #a5b4fc;
  color: #4f46e5;
  font-weight: 700;
}

.tb-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tb-btn .u {
  text-decoration: underline;
}
.tb-btn .s {
  text-decoration: line-through;
}

.tb-sep {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: #e2e8f0;
}

.tiptap-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #fff;
}

.tiptap-content {
  height: 100%;
}

.tiptap-content :deep(.tiptap-prose),
.tiptap-content :deep(.ProseMirror) {
  min-height: 100%;
  padding: 16px 18px;
  outline: none;
  line-height: 1.75;
  color: #1e293b;
  font-size: 15px;
  word-break: break-word;
}

.tiptap-content :deep(.ProseMirror:focus) {
  box-shadow: inset 0 0 0 2px rgba(79, 70, 229, 0.18);
}

.tiptap-content :deep(.ProseMirror p.is-editor-empty:first-child::before),
.tiptap-content :deep(.ProseMirror p.has-focus.is-empty::before),
.tiptap-content :deep(.ProseMirror .is-empty::before) {
  color: #94a3b8;
  content: attr(data-placeholder);
  float: left;
  height: 0;
  pointer-events: none;
}

.tiptap-content :deep(h1),
.tiptap-preview :deep(h1) {
  font-size: 1.5em;
  font-weight: 700;
  margin: 0.6em 0 0.4em;
  color: #0f172a;
}
.tiptap-content :deep(h2),
.tiptap-preview :deep(h2) {
  font-size: 1.3em;
  font-weight: 700;
  margin: 0.6em 0 0.4em;
  color: #0f172a;
}
.tiptap-content :deep(h3),
.tiptap-preview :deep(h3) {
  font-size: 1.15em;
  font-weight: 700;
  margin: 0.6em 0 0.4em;
  color: #0f172a;
}

.tiptap-content :deep(p),
.tiptap-preview :deep(p) {
  margin: 0.5em 0;
}

.tiptap-content :deep(ul),
.tiptap-content :deep(ol),
.tiptap-preview :deep(ul),
.tiptap-preview :deep(ol) {
  padding-left: 1.4em;
  margin: 0.5em 0;
}

.tiptap-content :deep(blockquote),
.tiptap-preview :deep(blockquote) {
  margin: 0.6em 0;
  padding: 0.2em 0.9em;
  border-left: 3px solid #c7d2fe;
  background: #f8fafc;
  color: #475569;
}

.tiptap-content :deep(a),
.tiptap-preview :deep(a) {
  color: #4f46e5;
  text-decoration: underline;
}

.tiptap-content :deep(code),
.tiptap-preview :deep(code) {
  background: #f1f5f9;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.92em;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
}

.tiptap-content :deep(pre),
.tiptap-preview :deep(pre) {
  background: #f1f5f9;
  padding: 0.8em 1em;
  border-radius: 8px;
  overflow: auto;
}

.tiptap-content :deep(pre code),
.tiptap-preview :deep(pre code) {
  background: transparent;
  padding: 0;
}

.tiptap-preview {
  padding: 16px 18px;
  line-height: 1.75;
  color: #1e293b;
  min-height: 100%;
}
</style>
