<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  browseFolder,
  createCategory,
  updateCategory,
} from '../api'
import { toastError } from '../api/http'
import { appState } from '../stores/appState'
import { toTreeSelectOptions } from '../utils/tree'

const emit = defineEmits(['saved'])
const visible = ref(false)
const saving = ref(false)
const formRef = ref(null)
const editingId = ref(null)
const form = reactive({
  name: '',
  parent_id: null,
  path: '',
  description: '',
})

const parentOptions = computed(() =>
  toTreeSelectOptions(appState.categoryTree, editingId.value),
)

const rules = {
  name: [{ required: true, message: '请输入分类名称', trigger: 'blur' }],
}

function reset() {
  editingId.value = null
  form.name = ''
  form.parent_id = null
  form.path = ''
  form.description = ''
}

function open(cat = null, parentId = null) {
  reset()
  if (cat) {
    editingId.value = cat.id
    form.name = cat.name || ''
    form.parent_id = cat.parent_id ?? null
    form.path = cat.path || ''
    form.description = cat.description || ''
  } else if (parentId) {
    form.parent_id = parentId
  }
  visible.value = true
}

async function onBrowse() {
  try {
    const data = await browseFolder(form.path || '')
    if (data.cancelled) {
      ElMessage.info('已取消选择')
      return
    }
    if (data.path) {
      form.path = data.path
      ElMessage.success('已选择目录')
    }
  } catch (e) {
    toastError(e, '选择目录失败')
  }
}

async function onSubmit() {
  await formRef.value?.validate?.()
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      path: form.path.trim(),
      description: form.description.trim(),
      parent_id: form.parent_id || null,
    }
    if (editingId.value) {
      await updateCategory(editingId.value, payload)
      ElMessage.success('分类已更新')
    } else {
      await createCategory(payload)
      ElMessage.success('分类已创建')
    }
    visible.value = false
    emit('saved')
  } catch (e) {
    toastError(e, '保存分类失败')
  } finally {
    saving.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="editingId ? '编辑分类' : '新建分类'"
    width="560px"
    destroy-on-close
    class="category-dialog"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="cat-form">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="例如：招标项目" maxlength="80" show-word-limit />
      </el-form-item>
      <el-form-item label="上级分类">
        <el-tree-select
          v-model="form.parent_id"
          :data="parentOptions"
          check-strictly
          clearable
          filterable
          placeholder="不选则为顶级分类"
          style="width: 100%"
          :render-after-expand="false"
          :props="{ label: 'label', value: 'value', children: 'children' }"
        />
        <div class="hint">可建多级，如：工作 / 招标 / 某地区</div>
      </el-form-item>
      <el-form-item label="本地目录（最末级分类建议设置）">
        <div class="path-row">
          <el-input v-model="form.path" placeholder="可填绝对路径，或点击浏览选择" />
          <el-button @click="onBrowse">浏览…</el-button>
        </div>
        <div class="hint">一级/二级等中间层级可不设；准备挂项目的最末级需要设置目录。</div>
      </el-form-item>
      <el-form-item label="说明">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="2"
          placeholder="可选说明，方便区分同类分类"
          maxlength="200"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button size="large" @click="visible = false">取消</el-button>
      <el-button size="large" type="primary" :loading="saving" @click="onSubmit">保存分类</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cat-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.path-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.hint {
  margin-top: 6px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}
</style>
