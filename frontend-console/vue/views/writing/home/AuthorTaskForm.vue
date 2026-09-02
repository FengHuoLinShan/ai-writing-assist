<script setup>
import { reactive, ref, watch } from "vue"

const props = defineProps({
  task: { type: Object, default: null },
  source: { type: Object, default: null },
  draft: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(["submit", "cancel", "change"])

const form = reactive({ title: "", note: "", dueDate: "" })
const error = ref("")

function reset() {
  form.title = props.draft?.title ?? props.task?.title ?? props.source?.taskTitle ?? ""
  form.note = props.draft?.note ?? props.task?.note ?? ""
  form.dueDate = props.draft?.dueDate ?? props.task?.due_date ?? ""
  error.value = ""
}
watch(() => [props.task, props.source, props.draft], reset, { immediate: true })

function changed() {
  emit("change", { title: form.title, note: form.note, dueDate: form.dueDate })
}

function submit() {
  const title = form.title.trim()
  if (!title) {
    error.value = "请填写任务标题"
    return
  }
  error.value = ""
  emit("submit", {
    title,
    note: form.note.trim() || null,
    due_date: form.dueDate || null,
    source: props.task || !props.source ? undefined : { kind: props.source.kind, id: props.source.id },
  })
}
</script>

<template>
  <form class="author-task-form" aria-labelledby="author-task-form-title" @submit.prevent="submit">
    <div class="author-task-form__heading">
      <div>
        <h2 id="author-task-form-title">{{ task ? '编辑任务' : '添加任务' }}</h2>
        <p v-if="source">来源：{{ source.label || '当前资料' }}</p>
      </div>
      <button type="button" class="btn btn-sm btn-ghost" :disabled="busy" @click="emit('cancel')">取消</button>
    </div>
    <label for="author-task-title">标题</label>
    <input id="author-task-title" v-model="form.title" type="text" maxlength="255" required autofocus :disabled="busy" @input="changed">
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <label for="author-task-note">备注（可选）</label>
    <textarea id="author-task-note" v-model="form.note" rows="3" maxlength="4000" :disabled="busy" @input="changed" />
    <label for="author-task-date">日期（可选）</label>
    <input id="author-task-date" v-model="form.dueDate" type="date" :disabled="busy" @input="changed">
    <div class="author-task-form__actions">
      <button class="btn btn-primary" type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存任务' }}</button>
    </div>
  </form>
</template>

<style scoped>
.author-task-form { display: grid; gap: 10px; padding: 18px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-panel); }
.author-task-form__heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.author-task-form__heading h2, .author-task-form__heading p { margin: 0; }
.author-task-form__heading p { margin-top: 4px; color: var(--text-muted); }
.author-task-form input, .author-task-form textarea { width: 100%; min-height: 44px; }
.author-task-form__actions { display: flex; justify-content: flex-end; }
.field-error { margin: 0; color: var(--danger); }
</style>
