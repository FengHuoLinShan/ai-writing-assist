<script setup>
/**
 * 本机 CLI 单次运行授权 — 仅用于图片生成（世界对象图片 / 地图册页面）。
 * 轮询 pending 列表判断任务是否仍等待作者确认；不在待确认列表中时自动隐藏。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  taskId: { type: String, required: true },
  executorKind: { type: String, default: "" },
  purpose: { type: String, default: "本机生成" },
})
const emit = defineEmits(["approved"])

const CLI_NAMES = { codex: "Codex", claude: "Claude", kimi: "Kimi", dsh: "DSH", pi: "Pi" }
function cliName(kind) {
  return CLI_NAMES[kind] || kind || "本机 CLI"
}

const pendingItem = ref(null)
const checked = ref(false)
const approving = ref(false)
const error = ref("")
let timer = null
let epoch = 0

async function poll(token) {
  if (!props.projectId || !props.taskId) { pendingItem.value = null; return }
  try {
    const result = await getApi().localAgent.pending(props.projectId)
    if (token !== epoch) return
    const items = result?.items || []
    pendingItem.value = items.find((item) => item.task_id === props.taskId) || null
    error.value = ""
  } catch (err) {
    if (token !== epoch) return
    error.value = err.message || "待确认任务暂时无法读取"
  } finally {
    schedule(token)
  }
}

function schedule(token) {
  clearTimeout(timer); timer = null
  if (token !== epoch || !pendingItem.value) return
  timer = setTimeout(() => poll(token), 3000)
}

function reset() {
  epoch += 1
  clearTimeout(timer); timer = null
  pendingItem.value = null; checked.value = false; approving.value = false; error.value = ""
}

watch(() => [props.projectId, props.taskId], () => {
  reset()
  const token = epoch
  void poll(token)
}, { immediate: true })

onBeforeUnmount(() => { epoch += 1; clearTimeout(timer) })

async function approve() {
  if (!checked.value || approving.value || !pendingItem.value) return
  approving.value = true; error.value = ""
  const token = epoch
  try {
    await getApi().localAgent.approve(props.projectId, props.taskId)
    if (token !== epoch) return
    clearTimeout(timer); timer = null
    pendingItem.value = null
    emit("approved")
  } catch (err) {
    if (token === epoch) error.value = err.message || "确认失败，请重试"
  } finally {
    if (token === epoch) approving.value = false
  }
}

const label = computed(() => pendingItem.value?.label || props.purpose)
const cli = computed(() => cliName(props.executorKind))
</script>

<template>
  <section
    v-if="pendingItem"
    class="local-run-approval card"
    role="group"
    :aria-label="`本机生成待确认：${label}`"
    :aria-busy="approving"
  >
    <p>
      {{ label }}将由你自己电脑上的 {{ cli }} 生成，它以当前 macOS 用户的文件与命令权限运行；
      本产品只接收生成的图片，经检查后作为候选，由你决定是否采用。请确认本机伴随程序正在运行。
    </p>
    <label class="local-run-approval__checkbox">
      <input v-model="checked" type="checkbox" :disabled="approving" />
      我了解并允许本次在本机运行
    </label>
    <button type="button" class="btn btn-primary" :disabled="!checked || approving" @click="approve">
      {{ approving ? "正在确认…" : "允许本次生成" }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.local-run-approval { display: grid; gap: 10px; }
.local-run-approval p { margin: 0; line-height: 1.6; }
.local-run-approval__checkbox { display: flex; align-items: center; gap: 8px; }
.local-run-approval button { min-height: 44px; width: max-content; }
@media (max-width: 480px) {
  .local-run-approval button { width: 100%; }
}
</style>
