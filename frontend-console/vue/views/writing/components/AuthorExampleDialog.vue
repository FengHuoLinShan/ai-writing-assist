<template>
  <div v-if="open" class="author-example-dialog-backdrop" @click.self="cancel">
    <div
      ref="dialogEl"
      class="author-example-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="author-example-dialog-title"
      @keydown.esc.stop.prevent="cancel"
      @keydown.tab.prevent="trapTab"
    >
      <h2 id="author-example-dialog-title">存为写作示例</h2>
      <p class="author-example-dialog__hint">
        示例会作为你的偏好进入之后的正文生成：好例是「以后照这个写」，反例是「别这样写」。
        示例只影响语感，不会替你新增情节或设定。
      </p>
      <fieldset class="author-example-dialog__kind">
        <legend>类型</legend>
        <label><input v-model="kind" type="radio" value="good" /> 以后照这个写（好例）</label>
        <label><input v-model="kind" type="radio" value="bad" /> 别这样写（反例）</label>
      </fieldset>
      <label class="author-example-dialog__field">
        <span>内容</span>
        <textarea v-model="content" rows="7" maxlength="2000" aria-label="示例内容" :readonly="contentLocked" />
        <span class="author-example-dialog__count">{{ content.length }}/2000</span>
      </label>
      <label class="author-example-dialog__field">
        <span>{{ kind === 'bad' ? '差在哪里（必填）' : '备注（可选）' }}</span>
        <textarea v-model="note" rows="2" maxlength="500" :aria-label="kind === 'bad' ? '差在哪里' : '备注'" :placeholder="kind === 'bad' ? '说明这种写法的问题，AI 会避免类似问题' : '例如：喜欢这种克制的白描'" />
      </label>
      <p v-if="error" class="author-example-dialog__error" role="alert">{{ error }}</p>
      <p v-if="limitHint" class="author-example-dialog__hint" role="status">{{ limitHint }}</p>
      <div class="author-example-dialog__actions">
        <button type="button" class="btn" @click="cancel">取消</button>
        <button type="button" class="btn btn-primary" :disabled="saving || !canSave" @click="save">{{ saving ? '保存中…' : '保存示例' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { getApi, getToast } from "../../../bridge/index.js"

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: String, default: null },
  // { content, chapterIndex, title, candidateId, contentLocked }
  draft: { type: Object, default: null },
})
const emit = defineEmits(["close", "saved"])

const kind = ref("good")
const content = ref("")
const note = ref("")
const saving = ref(false)
const error = ref("")
const version = ref(0)
const examples = ref([])
const dialogEl = ref(null)
let focusOrigin = null

const contentLocked = computed(() => Boolean(props.draft?.contentLocked))
const canSave = computed(() => Boolean(
  content.value.trim() && (kind.value !== "bad" || note.value.trim())
))
const limitHint = computed(() => {
  const good = examples.value.filter(item => item.kind === "good").length
  const bad = examples.value.filter(item => item.kind === "bad").length
  if (kind.value === "good" && good >= 3) return "好例已有 3 条（上限），保存会先被拒：可到项目设置删掉一条再存。"
  if (kind.value === "bad" && bad >= 2) return "反例已有 2 条（上限），保存会先被拒：可到项目设置删掉一条再存。"
  return ""
})

watch(() => props.open, async visible => {
  if (!visible) {
    if (focusOrigin?.isConnected) focusOrigin.focus()
    focusOrigin = null
    return
  }
  error.value = ""
  note.value = ""
  kind.value = "good"
  content.value = String(props.draft?.content || "").slice(0, 2000)
  focusOrigin = document.activeElement
  void nextTick(() => {
    const first = dialogEl.value?.querySelector("input, textarea, button")
    if (first) first.focus()
  })
  try {
    const state = await getApi().projects.authorExamples(props.projectId)
    version.value = Number(state.version) || 0
    examples.value = state.examples || []
  } catch { /* 首次使用时读取失败按空处理，保存仍会走乐观锁 */ }
})

function trapTab(event) {
  const root = dialogEl.value
  if (!root) return
  const focusables = Array.from(
    root.querySelectorAll("button:not([disabled]), input:not([disabled]), select, textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])")
  ).filter(el => el.offsetParent !== null)
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement
  const currentIndex = root.contains(active) ? focusables.indexOf(active) : -1
  if (event.shiftKey) {
    const target = currentIndex <= 0 ? last : focusables[currentIndex - 1]
    target.focus()
  } else {
    const target = currentIndex === -1 || currentIndex === focusables.length - 1 ? first : focusables[currentIndex + 1]
    target.focus()
  }
}

function cancel() {
  if (saving.value) return
  emit("close")
}

async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true
  error.value = ""
  try {
    const next = [...examples.value, {
      id: crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : `${Date.now()}${Math.random().toString(16).slice(2, 10)}`,
      kind: kind.value,
      content: content.value.trim(),
      note: note.value.trim(),
      source: {
        chapter_index: props.draft?.chapterIndex ?? null,
        title: String(props.draft?.title || "").slice(0, 200),
        candidate_id: props.draft?.candidateId ?? null,
      },
      capability_id: "writing.generate",
    }]
    const saved = await getApi().projects.saveAuthorExamples(props.projectId, {
      expected_version: version.value,
      state: { examples: next },
    })
    version.value = Number(saved.version) || 0
    examples.value = saved.examples || []
    getToast()(kind.value === "good" ? "已存为好例，之后的生成会参考这段语感。" : "已存为反例，之后的生成会避免这种写法。", "success")
    emit("saved")
    emit("close")
  } catch (cause) {
    error.value = cause.message || "保存失败，请重试。"
  } finally {
    saving.value = false
  }
}
</script>
