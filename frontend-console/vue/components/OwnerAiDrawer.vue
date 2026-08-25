<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { getAppState, getRouteQuery, getRouter } from "../bridge/index.js"
import GenerateView from "../views/generate/GenerateView.vue"
import { generateSessionKey } from "../views/generate/generateSession.js"
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
  writingContext: { type: Object, default: () => ({}) },
  evidenceCharacters: { type: Array, default: () => [] },
  evidenceScenes: { type: Array, default: () => [] },
})

const emit = defineEmits(["close"])
const GENERATION_TABS = new Set(["world", "task", "preview", "pov_prose"])
const appState = getAppState()
const router = getRouter()
const projectId = computed(() => props.projectId || appState?.currentProjectId || null)
const mode = ref(GENERATION_TABS.has(props.initialMode)
  ? props.initialMode
  : props.initialMode || (props.owner === "world" ? "world" : "writing"))
const generateProps = ref(null)
const generateLoading = ref(false)
const generateError = ref("")
const loadedKey = ref("")
const closeButton = ref(null)
let loadGeneration = 0
let loadGenerateModulePromise = null
let focusOrigin = null

async function loadGenerateProps(options) {
  loadGenerateModulePromise ||= import("../generateIsland.js")
  const module = await loadGenerateModulePromise
  return module.loadGenerate(options)
}

const ownerLabel = computed(() => props.owner === "world" ? "人物与世界" : "写作")
const isWorld = computed(() => props.owner === "world")
const writingSelected = computed(() => ["writing", "pov_prose"].includes(mode.value))
const taskSelected = computed(() => ["task", "preview"].includes(mode.value))
const activeCategory = computed(() => mode.value === "world" ? "world" : writingSelected.value ? "writing" : taskSelected.value ? "task" : "evidence")
const drawerHint = computed(() => mode.value === "evidence"
  ? "搜索词、筛选和结果会按当前作品保留；打开来源不会修改正文或设定。"
  : "未发送文字、任务进度和阶段结果仍按原会话保存；生成结果只会进入可编辑预览。")
const hasWritingChapter = computed(() => Number(props.chapter) > 0)
const hasWritingContent = computed(() => Boolean(props.writingContext?.hasContent))
const writingLocationTitle = computed(() => {
  if (!hasWritingChapter.value) return "还没有选择章节"
  const title = String(props.writingContext?.chapterTitle || "").trim()
  return `第 ${Number(props.chapter)} 章${title ? ` · ${title}` : ""}`
})
const writingPrimary = computed(() => hasWritingContent.value
  ? {
    action: "generateContinuation",
    title: "从当前正文继续写",
    label: "续写这一章",
    description: "沿用当前已保存正文生成后续内容，结果先作为待审建议。",
  }
  : {
    action: "generateDraft",
    title: "为本章生成正文建议",
    label: "生成本章建议",
    description: "根据本章和作品资料生成一版可编辑建议，不会直接写入工作稿。",
  })
const writingPrimaryDisabledReason = computed(() => {
  if (props.writingBusy) return "正文建议正在生成"
  if (!hasWritingChapter.value) return "先选择一个章节，再生成正文建议。"
  if (props.writingContext?.readonly) return "当前打开的是只读版本，请先回到工作稿。"
  if (hasWritingContent.value && props.writingContext?.hasUnsavedContent) {
    return props.writingContext?.saveError
      ? "当前修改还没有保存成功，请先重试保存。"
      : "当前正文有未保存修改；先保存工作稿，AI 才能从这一版准确续写。"
  }
  return ""
})
const writingPovDisabledReason = computed(() => {
  if (!hasWritingChapter.value) return "先选择章节"
  if (!props.sceneId) return "当前章节还没有关联场景"
  if (!props.writingContext?.hasPovCharacter) return "当前场景还没有设置视角人物"
  if (props.writingContext?.readonly) return "当前打开的是只读版本"
  return ""
})
const canSaveWriting = computed(() => typeof props.writingActions?.saveDraft === "function")
const modeKey = computed(() => `${projectId.value || "none"}:${props.owner}:${mode.value}:${props.sourcePageId || ""}:${props.targetKind || ""}:${props.preset || ""}:${props.checkpointId || ""}`)

function syncOpenQuery(open) {
  const query = getRouteQuery()
  const current = query.toString()
  if (open) {
    query.set("owner_ai", "1")
    query.set("owner_ai_mode", mode.value)
  } else {
    query.delete("owner_ai")
  }
  if (query.toString() !== current) router?.commitCurrentQuery?.(query, "replace")
}

async function closeDrawer({ restoreFocus = true } = {}) {
  syncOpenQuery(false)
  emit("close")
  await nextTick()
  if (restoreFocus && focusOrigin?.isConnected) focusOrigin.focus()
}

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
    if (["task", "preview"].includes(nextMode)) {
      const worldOptions = generateOptions("world")
      loaded.handoffSessionKey = generateSessionKey(worldOptions.projectId, worldOptions.sourcePageId, worldOptions.targetKind, worldOptions.preset)
    }
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
  if (!GENERATION_TABS.has(mode.value) && GENERATION_TABS.has(nextMode)) {
    loadedKey.value = ""
    generateProps.value = null
  }
  mode.value = nextMode
  const query = getRouteQuery()
  query.set("owner_ai", "1")
  query.set("owner_ai_mode", nextMode)
  router?.commitCurrentQuery?.(query, "replace")
}

function onCategoryKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
  const tabs = [...(event.currentTarget.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]') || [])]
  const current = tabs.indexOf(event.currentTarget)
  if (current < 0 || !tabs.length) return
  const target = event.key === "Home" ? 0
    : event.key === "End" ? tabs.length - 1
      : event.key === "ArrowLeft" ? (current - 1 + tabs.length) % tabs.length
        : (current + 1) % tabs.length
  event.preventDefault()
  tabs[target]?.focus()
}

async function runWriting(action) {
  const handler = props.writingActions?.[action]
  if (typeof handler !== "function" || props.writingBusy) return
  try {
    const result = await handler()
    if (result && props.open) await closeDrawer({ restoreFocus: false })
  } catch { /* controller owns author-facing errors */ }
}

async function saveWriting() {
  if (!canSaveWriting.value || props.writingContext?.saving) return
  try { await props.writingActions.saveDraft() } catch { /* editor keeps its inline recovery */ }
}

watch(() => props.owner, (owner) => {
  mode.value = GENERATION_TABS.has(props.initialMode)
    ? props.initialMode
    : props.initialMode || (owner === "world" ? "world" : "writing")
  generateProps.value = null
  loadedKey.value = ""
})
watch(() => props.open, (open) => {
  if (open) {
    focusOrigin = document.activeElement
    syncOpenQuery(true)
    if (GENERATION_TABS.has(mode.value)) void ensureGenerate(mode.value)
    void nextTick(() => closeButton.value?.focus())
  } else {
    loadGeneration += 1
  }
}, { immediate: true })
watch(modeKey, () => {
  if (props.open && GENERATION_TABS.has(mode.value)) void ensureGenerate(mode.value)
})
</script>

<template>
  <aside v-if="open" class="owner-ai-drawer" data-owner-ai-drawer role="dialog" aria-labelledby="owner-ai-drawer-title" @keydown.esc.stop.prevent="closeDrawer()">
    <button type="button" class="btn owner-ai-drawer__collapse" data-action="collapse-owner-ai-drawer" aria-label="收回 AI 工具" title="收回 AI 工具" @click="closeDrawer()">›</button>
    <div class="owner-ai-drawer__scroll">
    <header class="owner-ai-drawer__header">
      <div>
        <span id="owner-ai-drawer-title" class="owner-ai-drawer__eyebrow">{{ ownerLabel }} · AI 工具</span>
      </div>
      <button ref="closeButton" type="button" class="btn btn-sm" data-action="close-owner-ai-drawer" @click="closeDrawer()">关闭</button>
    </header>
    <p class="owner-ai-drawer__hint">{{ drawerHint }}</p>

    <nav class="owner-ai-drawer__tabs subnav" aria-label="AI 工具类别" role="tablist">
      <button v-if="isWorld" id="owner-ai-tab-world" type="button" class="owner-ai-drawer__tab subnav-item" :class="{ active: mode === 'world' }" role="tab" :aria-selected="mode === 'world'" aria-controls="owner-ai-panel-world" :tabindex="mode === 'world' ? 0 : -1" data-action="owner-world-generation" @keydown="onCategoryKeydown" @click="selectMode('world')">设定共创</button>
      <template v-else>
        <button id="owner-ai-tab-writing" type="button" class="owner-ai-drawer__tab subnav-item" :class="{ active: writingSelected }" role="tab" :aria-selected="writingSelected" aria-controls="owner-ai-panel-writing" :tabindex="writingSelected ? 0 : -1" data-action="owner-writing-generation" @keydown="onCategoryKeydown" @click="selectMode('writing')">写作建议</button>
      </template>
      <button id="owner-ai-tab-task" type="button" class="owner-ai-drawer__tab subnav-item" :class="{ active: taskSelected }" role="tab" :aria-selected="taskSelected" aria-controls="owner-ai-panel-task" :tabindex="taskSelected ? 0 : -1" data-action="owner-task-context" @keydown="onCategoryKeydown" @click="selectMode('task')">整理资料</button>
      <button id="owner-ai-tab-evidence" type="button" class="owner-ai-drawer__tab subnav-item" :class="{ active: mode === 'evidence' }" role="tab" :aria-selected="mode === 'evidence'" aria-controls="owner-ai-panel-evidence" :tabindex="mode === 'evidence' ? 0 : -1" data-action="owner-evidence" @keydown="onCategoryKeydown" @click="selectMode('evidence')">查找资料</button>
    </nav>

    <section v-if="mode === 'writing'" id="owner-ai-panel-writing" class="owner-ai-drawer__writing" role="tabpanel" aria-labelledby="owner-ai-tab-writing">
      <header class="owner-ai-writing__context">
        <span>当前写作位置</span>
        <h2>{{ writingLocationTitle }}</h2>
        <p v-if="writingContext.sceneTitle">当前场景：{{ writingContext.sceneTitle }}</p>
      </header>

      <div v-if="writingBusy" class="owner-ai-writing__progress" role="status" aria-live="polite">
        <strong>正文建议正在生成</strong>
        <p>可以收起 AI 工具继续写作；任务进度会留在写作页顶部，完成后仍需你审阅。</p>
        <button type="button" class="btn btn-sm btn-primary" data-action="owner-writing-show-progress" @click="closeDrawer()">收起并查看进度</button>
      </div>

      <template v-else>
        <section class="owner-ai-writing__primary" aria-labelledby="owner-ai-writing-primary-title">
          <span>推荐下一步</span>
          <h3 id="owner-ai-writing-primary-title">{{ writingPrimary.title }}</h3>
          <p>{{ writingPrimaryDisabledReason || writingPrimary.description }}</p>
          <div class="owner-ai-writing__primary-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="Boolean(writingPrimaryDisabledReason)"
              :data-action="writingPrimary.action === 'generateContinuation' ? 'owner-writing-continuation' : 'owner-writing-draft'"
              @click="runWriting(writingPrimary.action)"
            >{{ writingPrimary.label }}</button>
            <button
              v-if="hasWritingContent && writingContext.hasUnsavedContent && canSaveWriting"
              type="button"
              class="btn"
              :disabled="writingContext.saving"
              data-action="owner-writing-save"
              @click="saveWriting"
            >{{ writingContext.saving ? '正在保存…' : writingContext.saveError ? '重试保存' : '先保存工作稿' }}</button>
          </div>
        </section>

        <details class="owner-ai-writing__more">
          <summary>其他写作方式</summary>
          <div class="owner-ai-writing__options">
            <div class="owner-ai-writing__option">
              <span><strong>{{ hasWritingContent ? '生成整章新建议' : '从已有正文继续写' }}</strong><small>{{ hasWritingContent ? '重新构思一版，不会覆盖当前工作稿' : '写下并保存正文后可用' }}</small></span>
              <button
                type="button"
                class="btn btn-sm"
                :disabled="!hasWritingContent"
                :data-action="hasWritingContent ? 'owner-writing-draft' : 'owner-writing-continuation'"
                @click="runWriting(hasWritingContent ? 'generateDraft' : 'generateContinuation')"
              >{{ hasWritingContent ? '生成新建议' : '继续写' }}</button>
            </div>
            <div class="owner-ai-writing__option">
              <span><strong>按当前场景视角生成</strong><small>{{ writingPovDisabledReason || '只使用视角人物此刻知道的信息' }}</small></span>
              <button type="button" class="btn btn-sm" :disabled="Boolean(writingPovDisabledReason)" data-action="owner-writing-pov" @click="runWriting('generatePovDraft')">按视角生成</button>
            </div>
            <div class="owner-ai-writing__option">
              <span><strong>指定章节与视角</strong><small>需要切换章节、场景或人物时使用</small></span>
              <button type="button" class="btn btn-sm" data-action="owner-writing-pov-workbench" @click="selectMode('pov_prose')">打开选择</button>
            </div>
          </div>
        </details>
      </template>

      <p class="owner-ai-writing__safety">所有结果都会先进入待审建议，不会直接覆盖工作稿或正式正文。</p>
    </section>

    <section v-else-if="mode === 'evidence'" id="owner-ai-panel-evidence" class="owner-ai-drawer__evidence" role="tabpanel" aria-labelledby="owner-ai-tab-evidence">
      <RagSearchView :project-id="projectId" :characters="evidenceCharacters" :scenes="evidenceScenes" embedded />
    </section>

    <section v-else :id="`owner-ai-panel-${activeCategory}`" class="owner-ai-drawer__generate" role="tabpanel" :aria-labelledby="`owner-ai-tab-${activeCategory}`">
      <div v-if="mode === 'pov_prose'" class="owner-ai-drawer__backbar"><button type="button" class="btn btn-sm" data-action="return-owner-writing-tools" @click="selectMode('writing')">返回写作建议</button></div>
      <GenerateView v-if="generateProps" :key="`${generateProps.sessionKey}:${generateProps.tab}`" v-bind="generateProps" embedded @select-mode="selectMode" />
      <p v-else-if="generateLoading" class="owner-ai-drawer__status" role="status">正在恢复生成工作台…</p>
      <p v-else-if="generateError" class="owner-ai-drawer__status" role="alert">{{ generateError }}</p>
      <p v-else class="owner-ai-drawer__status">请选择一个工具。</p>
    </section>
    </div>
  </aside>
</template>
