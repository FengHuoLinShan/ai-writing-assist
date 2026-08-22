<script setup>
import { computed, ref, watch } from "vue"
import { getAppState } from "../bridge/index.js"
import GenerateView from "../views/generate/GenerateView.vue"
import RagSearchView from "../views/rag/RagSearchView.vue"

const props = defineProps({
  open: { type: Boolean, default: false },
  owner: { type: String, default: "writing" },
  initialMode: { type: String, default: null },
  projectId: { type: String, default: null },
  sourcePageId: { type: String, default: null },
  targetKind: { type: String, default: null },
  preset: { type: String, default: null },
  checkpointId: { type: String, default: null },
  chapter: { type: [Number, String], default: null },
  sceneId: { type: String, default: null },
  writingActions: { type: Object, default: () => ({}) },
  writingBusy: { type: Boolean, default: false },
  evidenceCharacters: { type: Array, default: () => [] },
  evidenceScenes: { type: Array, default: () => [] },
})

const emit = defineEmits(["close"])
const GENERATION_TABS = new Set(["world", "task", "preview", "pov_prose"])
const appState = getAppState()
const projectId = computed(() => props.projectId || appState?.currentProjectId || null)
const mode = ref(GENERATION_TABS.has(props.initialMode)
  ? props.initialMode
  : props.initialMode || (props.owner === "world" ? "world" : "writing"))
const generateProps = ref(null)
const generateLoading = ref(false)
const generateError = ref("")
const loadedKey = ref("")
let loadGeneration = 0
let loadGenerateModulePromise = null

async function loadGenerateProps(options) {
  loadGenerateModulePromise ||= import("../generateIsland.js")
  const module = await loadGenerateModulePromise
  return module.loadGenerate(options)
}

const ownerLabel = computed(() => props.owner === "world" ? "人物与世界" : "写作")
const isWorld = computed(() => props.owner === "world")
const modeKey = computed(() => `${projectId.value || "none"}:${props.owner}:${mode.value}:${props.sourcePageId || ""}:${props.targetKind || ""}:${props.preset || ""}:${props.checkpointId || ""}`)

function generateOptions(nextMode) {
  if (nextMode === "world") {
    return props.sourcePageId
      ? {
        projectId: projectId.value,
        tab: "world",
        preset: props.preset || "custom",
        sourcePageId: props.sourcePageId,
        targetKind: props.targetKind || "world_bible_page",
        checkpointId: props.checkpointId,
      }
      : {
        projectId: projectId.value,
        tab: "world",
        preset: props.preset || "custom",
        targetKind: props.targetKind || "core_entity",
        checkpointId: props.checkpointId,
      }
  }
  return {
    projectId: projectId.value,
    tab: GENERATION_TABS.has(nextMode) ? nextMode : "task",
    preset: isWorld.value ? "world_core" : "custom",
  }
}

async function ensureGenerate(nextMode = mode.value) {
  if (nextMode === "writing" || nextMode === "evidence" || !GENERATION_TABS.has(nextMode) || (loadedKey.value === modeKey.value && generateProps.value)) return
  const token = ++loadGeneration
  generateLoading.value = true
  generateError.value = ""
  try {
    const loaded = await loadGenerateProps(generateOptions(nextMode))
    if (token !== loadGeneration || !props.open) return
    generateProps.value = loaded
    loadedKey.value = modeKey.value
  } catch (error) {
    if (token === loadGeneration) generateError.value = error?.message || "AI 工具暂时无法加载"
  } finally {
    if (token === loadGeneration) generateLoading.value = false
  }
}

function selectMode(nextMode) {
  mode.value = nextMode
  if (nextMode === "world" || nextMode === "task") void ensureGenerate(nextMode)
}

function runWriting(action) {
  const handler = props.writingActions?.[action]
  if (typeof handler !== "function" || props.writingBusy) return
  void Promise.resolve(handler()).catch(() => {})
}

watch(() => props.owner, (owner) => {
  mode.value = GENERATION_TABS.has(props.initialMode)
    ? props.initialMode
    : props.initialMode || (owner === "world" ? "world" : "writing")
  generateProps.value = null
  loadedKey.value = ""
})
watch(() => props.open, (open) => {
  if (open && GENERATION_TABS.has(mode.value)) void ensureGenerate(mode.value)
  if (!open) loadGeneration += 1
}, { immediate: true })
watch(modeKey, () => {
  if (props.open && GENERATION_TABS.has(mode.value)) void ensureGenerate(mode.value)
})
</script>

<template>
  <aside v-if="open" class="owner-ai-drawer" data-owner-ai-drawer role="dialog" aria-label="AI 工具">
    <button type="button" class="btn owner-ai-drawer__collapse" data-action="collapse-owner-ai-drawer" aria-label="收回 AI 工具" title="收回 AI 工具" @click="emit('close')">›</button>
    <div class="owner-ai-drawer__scroll">
    <header class="owner-ai-drawer__header">
      <div>
        <span class="owner-ai-drawer__eyebrow">{{ ownerLabel }} · AI 工具</span>
      </div>
      <button type="button" class="btn btn-sm" data-action="close-owner-ai-drawer" @click="emit('close')">关闭</button>
    </header>
    <p class="owner-ai-drawer__hint">未发送文字、任务进度和阶段结果仍按原会话保存；生成结果只会进入可编辑预览。</p>

    <nav class="owner-ai-drawer__tabs" aria-label="AI 工具类别" role="tablist">
      <button v-if="isWorld" type="button" class="btn btn-sm" :class="{ 'btn-primary': mode === 'world' }" role="tab" :aria-selected="mode === 'world'" data-action="owner-world-generation" @click="selectMode('world')">世界设定共创</button>
      <template v-else>
        <button type="button" class="btn btn-sm" :class="{ 'btn-primary': mode === 'writing' }" role="tab" :aria-selected="mode === 'writing'" data-action="owner-writing-generation" @click="selectMode('writing')">写作建议</button>
      </template>
      <button type="button" class="btn btn-sm" :class="{ 'btn-primary': mode === 'task' }" role="tab" :aria-selected="mode === 'task'" data-action="owner-task-context" @click="selectMode('task')">任务上下文</button>
      <button type="button" class="btn btn-sm" :class="{ 'btn-primary': mode === 'evidence' }" role="tab" :aria-selected="mode === 'evidence'" data-action="owner-evidence" @click="selectMode('evidence')">查找证据</button>
    </nav>

    <section v-if="mode === 'writing'" class="owner-ai-drawer__writing" aria-label="写作生成">
      <p>沿用写作页的确认、任务进度和恢复；这里不会绕过正文待审阅流程。</p>
      <div class="owner-ai-drawer__actions">
        <button type="button" class="btn btn-sm btn-primary" :disabled="writingBusy" data-action="owner-writing-draft" @click="runWriting('generateDraft')">生成正文建议</button>
        <button type="button" class="btn btn-sm" :disabled="writingBusy" data-action="owner-writing-continuation" @click="runWriting('generateContinuation')">从当前正文续写</button>
        <button v-if="sceneId" type="button" class="btn btn-sm" :disabled="writingBusy" data-action="owner-writing-pov" @click="runWriting('generatePovDraft')">按当前视角生成</button>
      </div>
    </section>

    <section v-else-if="mode === 'evidence'" class="owner-ai-drawer__evidence" aria-label="查找证据">
      <RagSearchView :project-id="projectId" :characters="evidenceCharacters" :scenes="evidenceScenes" />
    </section>

    <section v-else class="owner-ai-drawer__generate" aria-label="生成工作台">
      <GenerateView v-if="generateProps" v-bind="generateProps" />
      <p v-else-if="generateLoading" class="owner-ai-drawer__status" role="status">正在恢复生成工作台…</p>
      <p v-else-if="generateError" class="owner-ai-drawer__status" role="alert">{{ generateError }}</p>
      <p v-else class="owner-ai-drawer__status">请选择一个工具。</p>
    </section>
    </div>
  </aside>
</template>
