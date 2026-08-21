<template>
  <div class="view-header view-header--with-tabs generate-toolbar">
    <div class="subnav generate-subtabs" role="tablist" aria-label="生成模式">
      <button v-for="item in tabs" :key="item.key" :id="tabId(item.key)" class="generate-subtab" :class="{ active: activeTab === item.key }"
        type="button" role="tab" :aria-selected="activeTab === item.key" :aria-controls="tabPanelId(item.key)" :tabindex="activeTab === item.key ? 0 : -1"
        data-action="switch-generate-subtab" :data-subtab="item.key" @keydown="onTabKeydown($event, item.key)" @click="switchTab(item.key)">{{ item.label }}</button>
    </div>
    <div class="view-header__actions">
      <span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span>
      <template v-if="activeTab === 'world' && !isWorldCore">
        <span class="generate-suggestion-note">对象建议会一并参考输入框中尚未发送的内容</span>
        <button class="btn btn-sm btn-primary" data-action="generate-world-suggestion" :disabled="worldBusy" @click="requestWorldSuggestion">{{ generateLabel }}</button>
      </template>
      <button v-else-if="activeTab === 'pov_prose' && !pov.loading && pov.chapters.length" class="btn btn-sm btn-primary" data-action="generate-pov-prose" :disabled="povPending" @click="generatePov">生成角色视角正文</button>
      <template v-else-if="activeTab === 'task'">
        <button class="btn btn-sm btn-primary" data-action="run-task" :disabled="taskPending" @click="compileTask(false)">编译上下文</button>
        <button class="btn btn-sm" data-action="preview-task-context" :disabled="taskPending" @click="compileTask(true)">预览上下文</button>
        <button class="btn btn-sm" data-action="render-task-md" :disabled="taskPending" @click="renderTaskMarkdown">渲染 Markdown</button>
        <button class="btn btn-sm" data-action="apply-to-chat" @click="applyTaskToChat">应用到聊天</button>
      </template>
    </div>
  </div>

  <div v-if="activeTab === 'world'" :id="tabPanelId('world')" class="generate-tab-panel" role="tabpanel" :aria-labelledby="tabId('world')">
    <WorkflowProgressCard
      v-if="worldTaskProgress"
      :progress="worldTaskProgress"
      variant="card"
      title="生成世界设定建议"
      :show-task-id="false"
    >
      <button v-if="!worldTaskProgress.terminal" type="button" class="btn btn-sm" @click="cancelWorldTask">取消生成</button>
      <button v-else-if="worldTaskProgress.failed || worldTaskProgress.cancelled" type="button" class="btn btn-sm" @click="dismissWorldTask">收起</button>
    </WorkflowProgressCard>
    <WorldWorkspace ref="worldWorkspaceRef"
      :project-id="projectId" :source-page-id="sourcePageId" :target-kind="targetKind" :source-page="world.sourcePage" :source-draft="world.sourceDraft"
      :warning="world.warning" :templates="templates" :activation-profiles="activationProfiles" :categories="world.categories" :page-templates="world.pageTemplates" :pages="world.pages"
      :scenes="world.scenes" :threads="world.threads" :characters="world.characters" :entities="world.entities" :result="worldResult" :previous-result="previousWorldResult" :proposal-draft="session.pageProposalDraft" :proposal-reset-token="pageProposalEditorResetToken" :recovered-page-proposal="recoveredPageProposal"
      :chat-context-usage="chatContextUsage" :entity-context-usage="entityContextUsage" :convergence-draft="session.convergenceDraft" :convergence-pending="convergencePending" :visual-brief="session.visualBrief" :external-packets="session.externalPackets" :exploration-draft="explorationDraft" :exploration-pending="explorationPending" :exploration-selection="explorationSelection" :source-revision-result="sourceRevisionResult" :busy="worldBusy" :chat-pending="chatPending" :loading-result="suggestionPending" :result-error="worldError"
      :world-core="isWorldCore" :successful-rounds="session.successfulRounds" :checkpoint-pending="checkpointPending" :checkpoint-saved="Boolean(session.checkpointId)"
      v-model:selected-template-id="session.selectedTemplateId" v-model:messages="session.messages" v-model:composer="composer"
      v-model:external-packet-draft="session.externalPacketDraft"
      v-model:quality-mode="session.qualityMode" v-model:include-world-synopsis="session.includeWorldSynopsis" v-model:activation-profile-id="session.activationProfileId"
      v-model:selected-chapters="session.selectedChapters" v-model:selected-scene-id="session.selectedSceneId" v-model:selected-thread-ids="session.selectedThreadIds"
      v-model:selected-character-ids="session.selectedCharacterIds" v-model:selected-entity-ids="session.selectedEntityIds"
      v-model:selected-world-page-ids="session.selectedWorldPageIds"
      v-model:new-page-type="session.newPageType" v-model:new-page-template-key="session.newPageTemplateKey"
      @select-target="selectTarget" @edit-templates="openTemplateEditor" @return-world-bible="returnToWorldBible" @select-chapters="openChapterPicker"
      @send-chat="sendChat" @converge="convergeWorld" @set-convergence-disposition="setConvergenceDisposition" @edit-convergence-message="editConvergenceMessage" @apply-convergence-message="applyConvergenceMessage" @dismiss-convergence="dismissConvergence" @open-convergence-source="openConvergenceSource"
      @prefill-world-core="prefillWorldCore" @save-world-core-checkpoint="saveWorldCoreCheckpoint"
      @explore="exploreWorld" @select-exploration="selectExploration" @dismiss-exploration="dismissExploration" @open-source-revision="openSourceRevision"
      @copy-handoff="copyWorldHandoff" @download-handoff="downloadWorldHandoff" @open-story-outline="openStoryOutline" @preview-external-packet="previewExternalPacket" @clear-external-packet="session.externalPacketDraft = ''"
      @create-visual-brief="createVisualBrief" @edit-visual-brief="editVisualBrief" @confirm-visual-brief="confirmVisualBrief" @copy-visual-brief="copyVisualBrief" @download-visual-brief="downloadVisualBrief" @preview-visual-map="previewVisualMap"
      @apply-page="applyWorldPage" @proposal-dirty="pageProposalDirty = $event" @proposal-edit="capturePageProposalEdit" @clear-result="requestWorldSuggestion" @open-review="openReview" @view-context="viewGenerationContext" />
  </div>
  <div v-else-if="activeTab === 'pov_prose'" :id="tabPanelId('pov_prose')" class="generate-tab-panel" role="tabpanel" :aria-labelledby="tabId('pov_prose')">
    <PovProseTab v-model:form="povForm" :loading="pov.loading" :chapters="pov.chapters" :scenes="pov.scenes" :characters="pov.characters" :warning="pov.warning" :submission="povSubmission" :pending="povPending" :progress="povProgress" :error="povError" @change-chapter="changePovChapter" @change-scene="changePovScene" @cancel="cancelPovTask" @open-result="openPovResult" @open-writing="openPovWriting" @return-world="switchTab('world')" />
  </div>
  <div v-else-if="activeTab === 'task'" :id="tabPanelId('task')" class="generate-tab-panel" role="tabpanel" :aria-labelledby="tabId('task')">
    <TaskContextTab v-model:form="taskForm" :project-id="projectId" :preset="taskPreset" :bundle="lastContextBundle" :markdown="lastContextMarkdown" :pending="taskPending" :error="taskError" @select-preset="selectTaskPreset" @copy-markdown="copyTaskMarkdown" @export-markdown="exportTaskMarkdown" />
  </div>
  <div v-else :id="tabPanelId('preview')" class="generate-tab-panel" role="tabpanel" :aria-labelledby="tabId('preview')">
    <ContextPreviewTab :bundle="lastContextBundle" :markdown="lastContextMarkdown" :source-text="contextSourceText" :busy="taskPending" @render-markdown="renderTaskMarkdown" @copy-markdown="copyTaskMarkdown" @export-markdown="exportTaskMarkdown" @return="switchTab(lastContextSource === 'world' ? 'world' : 'task')" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { getApi, getAppState, getCloseModal, getConfirm, getEsc, getRouter, getShowModalHtml, getToast } from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import WorldWorkspace from "./components/WorldWorkspace.vue"
import PovProseTab from "./components/PovProseTab.vue"
import TaskContextTab from "./components/TaskContextTab.vue"
import ContextPreviewTab from "./components/ContextPreviewTab.vue"
import WorkflowProgressCard from "../../components/WorkflowProgressCard.vue"
import { createGenerateRequestOwner } from "./requestOwner.js"
import {
  clearActiveWorkflow,
  createOperationId,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"
import {
  clearCreativeContinuation,
  readCreativeContinuation,
  readGenerateContextPreview,
  writeCreativeContinuation,
  writeGenerateContextPreview,
  writeGenerateSession,
} from "./generateSession.js"
import { pageProposalDraftMatches } from "./pageProposalSession.js"
import {
  AI_MESSAGE_LIMIT, AI_SELECTED_CHAPTER_LIMIT, EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT, OBJECT_TEMPLATES, PAGE_SIZE, TASK_PRESETS, VISUAL_BRIEF_FIELD_LIMIT, VISUAL_BRIEF_PURPOSE_OPTIONS, applyTaskPreset,
  buildPovInstruction, buildTaskPayload, buildVisualBriefMarkdown, buildWorldCoreCheckpointContext, buildWorldCoreCheckpointRequest, buildWorldHandoffMarkdown, buildWorldPayload, characterId, compileConvergenceMessage,
  convergenceDraftFromResponse, convergenceSourceMatchesPayload, createDefaultTaskForm, externalDispositionCounts, externalPacketCharacterCount,
  hashExternalPacket, listItems, normalizeTemplate, parseExternalPacketPosition, validateTaskPayload, visualBriefFromConvergence, visualBriefMatchesConvergence,
} from "./logic/generateLogic.js"

const props = defineProps({
  projectId: { type: String, default: null }, tab: { type: String, default: "world" }, preset: { type: String, default: "custom" },
  sourcePageId: { type: String, default: null }, targetKind: { type: String, default: "core_entity" }, sessionKey: { type: String, required: true },
  initialSession: { type: Object, required: true }, templates: { type: Array, default: () => [] }, activationProfiles: { type: Array, default: () => [] },
  sourcePage: Object, sourceDraft: Object, worldCategories: { type: Array, default: () => [] }, worldPageTemplates: { type: Array, default: () => [] }, worldPages: { type: Array, default: () => [] },
  worldScenes: { type: Array, default: () => [] }, worldThreads: { type: Array, default: () => [] }, worldCharacters: { type: Array, default: () => [] }, worldEntities: { type: Array, default: () => [] },
  worldWorkspaceWarning: String, worldSourceUnavailable: { type: Boolean, default: false }, restoredWorldResult: Object, restoredPreviousWorldResult: Object, povChapters: { type: Array, default: () => [] }, povCharacters: { type: Array, default: () => [] }, povLoadWarning: String,
})

const api = getApi(); const appState = getAppState(); const router = getRouter(); const toast = getToast(); const confirm = getConfirm()
const showModalHtml = getShowModalHtml(); const closeModal = getCloseModal(); const esc = getEsc()
const owner = createGenerateRequestOwner({ projectId: props.projectId, sessionKey: props.sessionKey })
const receiptStorage = globalThis.sessionStorage
const notices = new Set()
const session = reactive({ ...props.initialSession })
if (props.preset === "world_core") session.selectedTemplateId = "builtin:none"
const composer = ref(props.initialSession.composer || "")
const templates = ref(props.templates.length ? props.templates : [...OBJECT_TEMPLATES])
const activationProfiles = ref(props.activationProfiles)
const activeTab = ref(props.tab)
const taskPreset = ref(TASK_PRESETS[props.preset] ? props.preset : "custom")
const taskForm = ref(applyTaskPreset(createDefaultTaskForm(), taskPreset.value))
const restoredContext = readGenerateContextPreview(props.projectId)
const lastContextBundle = ref(restoredContext.bundle); const lastContextMarkdown = ref(restoredContext.markdown); const lastContextSource = ref(restoredContext.source); const lastContextRequest = ref(restoredContext.request)
const worldResult = ref(props.restoredWorldResult); const previousWorldResult = ref(props.restoredPreviousWorldResult); const chatContextUsage = ref(null); const entityContextUsage = ref(null); const worldError = ref("")
const worldTaskProgress = ref(null)
const initialPageProposalDraft = pageProposalDraftMatches(worldResult.value, session.pageProposalDraft)
const pageProposalDirty = ref(Boolean(initialPageProposalDraft))
const recoveredPageProposal = ref(Boolean(initialPageProposalDraft))
const pageProposalEditorResetToken = ref(0)
const taskPending = ref(false); const taskError = ref("")
const chatPending = ref(false); const convergencePending = ref(false); const explorationPending = ref(false); const suggestionPending = ref(false); const applyPending = ref(false); const checkpointPending = ref(false)
const explorationDraft = ref(null); const explorationSelection = ref(null); const sourceRevisionResult = ref(null)
const worldWorkspaceRef = ref(null)
const sourceUnavailable = ref(props.worldSourceUnavailable)
const world = reactive({ sourcePage: props.sourcePage, sourceDraft: props.sourceDraft, categories: props.worldCategories, pageTemplates: props.worldPageTemplates, pages: props.worldPages, scenes: props.worldScenes, threads: props.worldThreads, characters: props.worldCharacters, entities: props.worldEntities, warning: props.worldWorkspaceWarning, loaded: props.tab === "world" })
const pov = reactive({ chapters: props.povChapters, scenes: [], characters: props.povCharacters, warning: props.povLoadWarning, loaded: props.tab === "pov_prose", loading: false })
const povForm = ref({ chapterIndex: null, sceneId: "", viewpointCharacterId: "", instruction: "" })
const povSubmission = ref(null); const povPending = ref(false); const povProgress = ref(null); const povError = ref("")
const povTaskId = ref(null)
let modalGeneration = 0
let ownedModal = null
let povSceneGeneration = 0
let copiedBuiltinTemplate = null
let templateMutationPending = false
let worldTaskPoller = null

const tabs = [{ key: "world", label: "世界设定" }, { key: "pov_prose", label: "角色视角正文" }, { key: "task", label: "任务" }, { key: "preview", label: "上下文预览" }]
const projectTitle = computed(() => appState?.currentProject?.title || appState?.currentProject?.name || "")
const isWorldCore = computed(() => props.preset === "world_core")
const generateLabel = computed(() => explorationSelection.value ? "生成所选探索建议" : ({ core_entity: "生成世界对象建议", world_bible_page: "生成整页提案", world_bible_new_page: "生成新页提案" })[props.targetKind] || "生成建议")
const worldBusy = computed(() => (
  sourceUnavailable.value
  || chatPending.value
  || convergencePending.value
  || explorationPending.value
  || suggestionPending.value
  || applyPending.value
  || checkpointPending.value
  || Boolean(worldTaskProgress.value && !worldTaskProgress.value.terminal)
))
const contextSourceText = computed(() => lastContextSource.value === "world" ? "世界设定共创" : lastContextSource.value === "task" ? `任务：${TASK_PRESETS[taskPreset.value]?.label || "自定义任务"}` : "")
const worldHandoffMarkdown = computed(() => buildWorldHandoffMarkdown({ projectTitle: projectTitle.value, targetKind: props.targetKind, sourcePage: world.sourcePage, sourceDraft: world.sourceDraft, convergenceDraft: session.convergenceDraft }))
const visualBriefMarkdown = computed(() => buildVisualBriefMarkdown({ handoffMarkdown: worldHandoffMarkdown.value, visualBrief: session.visualBrief, convergenceDraft: session.convergenceDraft }))
const visualBriefCurrent = computed(() => visualBriefMatchesConvergence(session.visualBrief, session.convergenceDraft))
function notifyOnce(code, message) { const key = `${props.sessionKey}:${code}`; if (notices.has(key)) return; notices.add(key); toast(message, "warning") }
function persistContextPreview() {
  writeGenerateContextPreview(props.projectId, {
    bundle: lastContextBundle.value,
    markdown: lastContextMarkdown.value,
    source: lastContextSource.value,
    request: lastContextRequest.value,
  })
}
function persist() {
  const saved = writeGenerateSession(props.sessionKey, { ...session, composer: composer.value }, { notify: notifyOnce })
  if (!saved) clearGenerateContinuation()
  return saved
}
function rememberGenerateContinuation() {
  writeCreativeContinuation(props.projectId, {
    destination: "generate",
    route: {
      source_page_id: props.sourcePageId || null,
      target: props.targetKind,
      ...(isWorldCore.value ? { preset: "world_core" } : {}),
      ...(session.checkpointId ? { checkpoint_id: session.checkpointId } : {}),
    },
  })
}
function clearGenerateContinuation() {
  const continuation = readCreativeContinuation(props.projectId)
  if (
    continuation?.destination === "generate"
    && continuation.route.source_page_id === (props.sourcePageId || null)
    && continuation.route.target === props.targetKind
    && (continuation.route.preset || "custom") === (isWorldCore.value ? "world_core" : "custom")
  ) clearCreativeContinuation(props.projectId)
}
watch(session, persist, { deep: true })
watch(composer, () => { if (persist()) rememberGenerateContinuation() })
watch(worldResult, (result) => {
  if (!session.pageProposalDraft) return
  if (!result) return
  if (!pageProposalDraftMatches(result, session.pageProposalDraft)) discardPageProposalDraft()
  else pageProposalDirty.value = true
}, { immediate: true })
watch(
  [lastContextBundle, lastContextMarkdown, lastContextSource, lastContextRequest],
  persistContextPreview,
  { deep: true },
)

function discardPageProposalDraft() {
  session.pageProposalDraft = null
  pageProposalDirty.value = false
  recoveredPageProposal.value = false
  pageProposalEditorResetToken.value += 1
}
function capturePageProposalEdit(draft) {
  session.pageProposalDraft = draft
  pageProposalDirty.value = Boolean(draft)
  if (persist()) rememberGenerateContinuation()
}
function confirmDiscard(message) { if (!pageProposalDirty.value) return true; const accepted = confirm(message); if (accepted) { discardPageProposalDraft(); persist() } return accepted }
useLeaveGuard(() => confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并离开吗？"))

async function loadAll(fetchPage) { const output = []; let skip = 0; while (true) { const data = await fetchPage(skip); const page = data?.items || []; output.push(...page); const total = Number(data?.total); if (page.length < PAGE_SIZE || (Number.isFinite(total) && output.length >= total) || !page.length) return output; skip += page.length } }
async function ensureWorld() {
  if (world.loaded) return
  const scope = owner.begin()
  try {
    const [pages, drafts, categories, pageTemplates, scenes, threads, characters, entities] = await Promise.all([
      api.world.listBiblePages({ novel_id: props.projectId }), api.world.listBibleDrafts(props.projectId), api.world.listBibleCategories(props.projectId), api.world.listBiblePageTemplates(props.projectId),
      api.outline.listScenesOrdered(props.projectId), api.outline.listThreads(props.projectId, { limit: 50 }),
      loadAll((skip) => api.world.listCharacters({ novel_id: props.projectId, skip, limit: PAGE_SIZE })), loadAll((skip) => api.world.listEntities({ novel_id: props.projectId, display_state: "active", skip, limit: PAGE_SIZE })),
    ])
    if (!owner.isActive(scope)) return
    const pagesList = listItems(pages); const draftsList = listItems(drafts)
    world.sourcePage = props.sourcePageId ? pagesList.find((item) => item.id === props.sourcePageId) || null : null
    world.sourceDraft = props.sourcePageId ? draftsList.find((item) => item.page_id === props.sourcePageId) || null : null
    world.categories = listItems(categories); world.pageTemplates = listItems(pageTemplates); world.pages = pagesList.filter((item) => ["canonical", "confirmed"].includes(item.status)); world.scenes = listItems(scenes); world.threads = listItems(threads); world.characters = characters
    const characterIds = new Set(characters.flatMap((item) => [item.id, item.entity_id].filter(Boolean)))
    world.entities = entities.filter((item) => item.entity_type !== "character" && !characterIds.has(item.id)); world.loaded = true
    sourceUnavailable.value = Boolean(props.sourcePageId && !world.sourcePage)
    if (sourceUnavailable.value) clearGenerateContinuation()
    world.warning = sourceUnavailable.value
      ? "原来源页面已变化。本地对话和未发送内容仍保留，请返回世界笔记选择新的目标。"
      : null
  } catch (err) {
    if (owner.isActive(scope)) {
      sourceUnavailable.value = Boolean(props.sourcePageId)
      world.warning = props.sourcePageId
        ? `原来源与生成上下文暂时无法核对：${err?.message || "未知错误"}。本地对话和未发送内容仍保留，请稍后重试或返回世界笔记。`
        : `生成上下文加载不完整：${err?.message || "未知错误"}`
    }
  } finally { owner.finish(scope) }
}
async function ensurePov() {
  if (pov.loaded || pov.loading) return
  pov.loading = true
  const scope = owner.begin()
  try { const [chapters, characters] = await Promise.all([api.writing.listChapters(props.projectId), loadAll((skip) => api.world.listCharacters({ novel_id: props.projectId, skip, limit: PAGE_SIZE }))]); if (!owner.isActive(scope)) return; pov.chapters = chapters?.chapters || []; pov.characters = characters; pov.warning = null; pov.loaded = true }
  catch (err) { if (owner.isActive(scope)) pov.warning = `加载章节或角色失败：${err?.message || "未知错误"}` } finally { owner.finish(scope); pov.loading = false }
}

async function switchTab(tab) { if (!tabs.some((item) => item.key === tab) || tab === activeTab.value) return; if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并切换标签吗？")) return; activeTab.value = tab; if (tab === "world") await ensureWorld(); if (tab === "pov_prose") await ensurePov() }
function tabId(tab) { return `generate-mode-tab-${tab}` }
function tabPanelId(tab) { return `generate-mode-panel-${tab}` }
function onTabKeydown(event, tab) {
  const current = tabs.findIndex((item) => item.key === tab)
  const target = event.key === "ArrowLeft" ? (current - 1 + tabs.length) % tabs.length
    : event.key === "ArrowRight" ? (current + 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null
  if (target === null) return
  event.preventDefault()
  event.currentTarget
    ?.closest('[role="tablist"]')
    ?.querySelector(`[data-subtab="${tabs[target].key}"]`)
    ?.focus()
}
function currentWorldPayload() {
  const payload = buildWorldPayload({ ...session, projectId: props.projectId, sourcePageId: props.sourcePageId, targetKind: props.targetKind, sourcePage: world.sourcePage, sourceDraft: world.sourceDraft, templates: templates.value, activationProfiles: activationProfiles.value, worldPageTemplates: world.pageTemplates, worldPages: world.pages, workflowPreset: isWorldCore.value ? "world_core" : "default" })
  const checkpointContext = buildWorldCoreCheckpointContext(session.convergenceDraft)
  if (checkpointContext) payload.pasted_context = checkpointContext
  return payload
}
function convergencePayload() {
  const payload = currentWorldPayload()
  const messages = (session.messages || [])
    .filter((item) => !item.pending && !item.error && ["user", "assistant"].includes(item.role))
    .map(({ role, content }) => ({ role, content }))
  if (composer.value.trim()) messages.push({ role: "user", content: composer.value.trim() })
  payload.messages = messages.slice(-AI_MESSAGE_LIMIT)
  payload.excluded_message_count = Math.max(0, messages.length - payload.messages.length)
  return payload
}
function explorationPayload() {
  const payload = convergencePayload()
  delete payload.excluded_message_count
  payload.depth = 1
  return payload
}
const convergenceInputSignature = computed(() => JSON.stringify(convergencePayload()))
if (session.convergenceDraft && !convergenceSourceMatchesPayload(session.convergenceDraft, currentWorldPayload())) session.convergenceDraft.stale = true
function markVisualBriefStale() { if (session.visualBrief) session.visualBrief.stale = true }
watch(convergenceInputSignature, (value, previous) => {
  if (value === previous) return
  if (!convergencePending.value && session.convergenceDraft) session.convergenceDraft.stale = true
  if (!explorationPending.value && explorationDraft.value) explorationDraft.value.stale = true
  if (!convergencePending.value) markVisualBriefStale()
})
watch(() => session.externalPacketDraft, (value, previous) => {
  if (value === previous || convergencePending.value || !session.convergenceDraft?.externalPacketHash) return
  session.convergenceDraft.stale = true
  markVisualBriefStale()
})
function captureComposer() { const text = composer.value.trim(); if (!text) return false; session.messages.push({ role: "user", content: text }); composer.value = ""; return true }
function beforeUnload() { persist(); owner.dispose() }
function armBeforeUnload() { window.addEventListener("beforeunload", beforeUnload) }
function disarmBeforeUnload() { window.removeEventListener("beforeunload", beforeUnload) }

async function sendChat() {
  if (worldBusy.value) return false
  if (!composer.value.trim()) return toast("请输入要聊的内容", "warning")
  captureComposer(); const pending = reactive({ role: "assistant", content: "正在思考...", pending: true }); session.messages.push(pending); if (persist()) rememberGenerateContinuation(); const scope = owner.begin(); armBeforeUnload(); chatPending.value = true
  try { const response = await api.generate.worldChat(currentWorldPayload(), { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; chatContextUsage.value = response?.context_usage || null; pending.content = response?.reply || "生成完成，但没有返回回复。"; pending.pending = false; if (isWorldCore.value) session.successfulRounds = Math.min(999, Number(session.successfulRounds || 0) + 1); persist() }
  catch (err) { if (!owner.isActive(scope)) return; pending.content = `聊天失败：${err?.message || "未知错误"}`; pending.pending = false; pending.error = true; persist(); toast(pending.content, "error") }
  finally {
    owner.finish(scope)
    disarmBeforeUnload()
    chatPending.value = false
    await nextTick()
    worldWorkspaceRef.value?.focusComposer?.()
  }
}
function rememberExternalPacket(hash, position, characterCount, status, receipt = {}) {
  session.externalPackets = [...(session.externalPackets || []), {
    hash,
    packetIndex: position.packetIndex,
    packetTotal: position.packetTotal,
    characterCount,
    status,
    previewedAt: Date.now(),
    ...receipt,
  }].slice(-20)
}
async function convergeWorld(options = {}) {
  if (worldBusy.value) return false
  const payload = convergencePayload()
  if (isWorldCore.value) session.worldCoreAction = "consolidate"
  if (options.externalPacket) {
    payload.pasted_context = options.externalPacket
    payload.external_packet = {
      sha256: options.externalPacketHash,
      packet_index: options.position.packetIndex,
      packet_total: options.position.packetTotal,
    }
  }
  if (!payload.messages.some((item) => item.role === "user")) return toast(options.externalPacket ? "请先在主输入框写清这份回包要服务的当前目标" : "请先写下或发送本轮想整理的内容", "warning")
  const submittedSignature = convergenceInputSignature.value
  convergencePending.value = true
  const scope = owner.begin()
  try {
    const response = await api.generate.convergeWorld(payload, { signal: scope.controller.signal })
    if (!owner.isActive(scope)) return
    const nextDraft = convergenceDraftFromResponse(response)
    if (session.visualBrief && session.visualBrief.manifestHash !== nextDraft.manifestHash) markVisualBriefStale()
    session.convergenceDraft = nextDraft
    if (convergenceInputSignature.value !== submittedSignature || (options.externalPacket && session.externalPacketDraft !== options.externalPacket)) session.convergenceDraft.stale = true
    if (session.convergenceDraft.stale) markVisualBriefStale()
    if (options.externalPacketHash) {
      session.convergenceDraft.externalPacketHash = options.externalPacketHash
      rememberExternalPacket(options.externalPacketHash, options.position, options.characterCount, session.convergenceDraft.coverage.complete && !session.convergenceDraft.stale ? "previewed" : "incomplete", {
        manifestHash: session.convergenceDraft.manifestHash,
        sourceCount: session.convergenceDraft.coverage.sourceCount,
        coveredSourceCount: session.convergenceDraft.coverage.coveredSourceCount,
        dispositionCounts: externalDispositionCounts(session.convergenceDraft),
      })
    }
    if (persist()) rememberGenerateContinuation()
    toast(session.convergenceDraft.stale ? "输入在整理期间发生变化；结果仅供回看，请按当前内容重新整理" : session.convergenceDraft.coverage.complete ? "本轮已收束为可编辑的决定预览，尚未创建建议" : "部分来源未通过覆盖校验，请查看后重新收束", session.convergenceDraft.coverage.complete && !session.convergenceDraft.stale ? "success" : "warning")
  } catch (err) {
    if (!owner.isActive(scope)) return
    if (err?.status === 409 && session.convergenceDraft) session.convergenceDraft.stale = true
    if (err?.status === 409 && options.externalPacketHash) rememberExternalPacket(options.externalPacketHash, options.position, options.characterCount, "incomplete")
    toast(err?.status === 409 ? "来源在收束期间已变化；旧预览仅供回看，请重新收束。" : `收束失败：${err?.message || "未知错误"}`, err?.status === 409 ? "warning" : "error")
  } finally {
    owner.finish(scope)
    convergencePending.value = false
  }
}
async function exploreWorld() {
  if (worldBusy.value) return false
  if (!props.sourcePageId || props.targetKind !== "world_bible_new_page") return toast("请从一个世界书页进入，并先选择“新建世界书页”", "warning")
  const payload = explorationPayload()
  const submittedSignature = convergenceInputSignature.value
  explorationPending.value = true
  explorationSelection.value = null
  const scope = owner.begin()
  try {
    const response = await api.generate.exploreWorld(payload, { signal: scope.controller.signal })
    if (!owner.isActive(scope)) return false
    explorationDraft.value = {
      ...response,
      targets: (response?.targets || []).slice(0, 3),
      stale: convergenceInputSignature.value !== submittedSignature,
    }
    toast(explorationDraft.value.stale ? "材料在探索期间发生变化；结果仅供回看" : explorationDraft.value.targets.length ? "已找到最多三条相邻入口；请选择一条" : "当前没有证据充分的相邻缺口，已在这一跳停止", explorationDraft.value.stale || !explorationDraft.value.targets.length ? "info" : "success")
    return true
  } catch (err) {
    if (!owner.isActive(scope)) return false
    if (err?.status === 409 && explorationDraft.value) explorationDraft.value.stale = true
    toast(err?.status === 409 ? "来源在探索期间已变化，请刷新后重试" : `探索失败：${err?.message || "未知错误"}`, err?.status === 409 ? "warning" : "error")
    return false
  } finally {
    owner.finish(scope)
    explorationPending.value = false
  }
}
function selectExploration(item) {
  const draft = explorationDraft.value
  if (!draft || draft.stale || !draft.targets.some((target) => target.item_id === item?.item_id)) return false
  explorationSelection.value = {
    depth: 1,
    request_fingerprint: draft.request_fingerprint,
    item_id: item.item_id,
    title: item.title,
    gap: item.gap,
    why_it_matters: item.why_it_matters,
    author_boundary: item.author_boundary,
    reverse_check_focus: item.reverse_check_focus,
    source_keys: [...(item.source_keys || [])],
  }
  toast("已选择这一条；尚未创建建议", "success")
  return true
}
function dismissExploration() {
  explorationDraft.value = null
  explorationSelection.value = null
}
async function previewExternalPacket() {
  if (worldBusy.value) return false
  const text = String(session.externalPacketDraft || "")
  if (!text.trim()) return toast("请先粘贴一份外部回包", "warning")
  const characterCount = externalPacketCharacterCount(text)
  if (characterCount > EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT) return toast(`这份回包有 ${characterCount.toLocaleString("zh-CN")} 个字符，超过 55,000 字符上限；原文仍保留，请按当前目标拆包后再整理`, "warning")
  let hash
  try { hash = await hashExternalPacket(text) } catch (err) { return toast(err?.message || "无法校验这份回包", "error") }
  const position = parseExternalPacketPosition(text, Math.max(0, ...(session.externalPackets || []).map((item) => item.packetIndex)) + 1)
  if (
    session.convergenceDraft?.externalPacketHash === hash
    && session.convergenceDraft.coverage?.complete
    && !session.convergenceDraft.stale
  ) {
    return toast("当前已显示这份回包的完整决定预览，未再次调用 AI", "info")
  }
  const duplicate = (session.externalPackets || []).find((item) => (
    item.hash === hash && ["decision_ready", "exact_duplicate"].includes(item.status)
  ))
  if (duplicate) {
    rememberExternalPacket(hash, position, characterCount, "exact_duplicate", {
      ...(duplicate.manifestHash ? { manifestHash: duplicate.manifestHash } : {}),
      ...(duplicate.sourceCount != null ? { sourceCount: duplicate.sourceCount } : {}),
      ...(duplicate.coveredSourceCount != null ? { coveredSourceCount: duplicate.coveredSourceCount } : {}),
      ...(duplicate.dispositionCounts ? { dispositionCounts: duplicate.dispositionCounts } : {}),
    })
    persist()
    return toast(`这与本会话第 ${duplicate.packetIndex} 份回包完全相同，未再次调用 AI`, "info")
  }
  return convergeWorld({ externalPacket: text, externalPacketHash: hash, position, characterCount })
}
function setConvergenceDisposition(cardId, itemId, disposition) {
  if (!new Set(["include", "open", "discard", "rejected"]).has(disposition) || !session.convergenceDraft || session.convergenceDraft.stale) return
  const card = session.convergenceDraft.cards.find((item) => item.cardId === cardId)
  const item = card?.items.find((entry) => entry.itemId === itemId)
  if (!item) return
  item.disposition = disposition
  session.convergenceDraft.authorMessage = compileConvergenceMessage(session.convergenceDraft)
  markVisualBriefStale()
}
const WORLD_CORE_ACTIONS = {
  expand: "扩展一层：只补足当前灵感成立必需的一条规则，不开新世界线。",
  connect: "连起因果：选两条已有规则，说清它们如何共同改变一个真实的日常选择。",
  pressure: "压力测试：固定一处日常运转，检查维护中断时的故障、代价和边界。",
  consolidate: "收拢核心：只整理已有灵感的去向、3–7 条成立规则与一条日常＋故障纵切。",
}
function prefillWorldCore(action) {
  if (!isWorldCore.value || !WORLD_CORE_ACTIONS[action]) return false
  session.worldCoreAction = action
  composer.value = WORLD_CORE_ACTIONS[action]
  return true
}
async function saveWorldCoreCheckpoint() {
  if (!isWorldCore.value || checkpointPending.value || Number(session.successfulRounds || 0) < 3) return false
  const request = buildWorldCoreCheckpointRequest({
    novelId: props.projectId,
    draft: session.convergenceDraft,
    roundNo: session.successfulRounds,
    action: session.worldCoreAction,
    parentCheckpointId: session.checkpointId,
  })
  if (!request) return toast("请先完成来源完整、无阻断矛盾的 World Core 收束", "warning"), false
  checkpointPending.value = true
  const scope = owner.begin()
  try {
    const saved = await api.world.saveCoreCheckpoint(request)
    if (!owner.isActive(scope)) return false
    session.checkpointId = saved.id
    if (persist()) rememberGenerateContinuation()
    toast("阶段成果已保存；可以从决定摘要继续，它仍不是正式设定", "success")
    return true
  } catch (err) {
    if (!owner.isActive(scope)) return false
    toast(`保存阶段成果失败：${err?.message || "未知错误"}`, "error")
    return false
  } finally {
    owner.finish(scope)
    checkpointPending.value = false
  }
}
function editConvergenceMessage(value) {
  if (!session.convergenceDraft || session.convergenceDraft.stale) return
  session.convergenceDraft.authorMessage = value
  markVisualBriefStale()
}
async function applyConvergenceMessage() {
  const draft = session.convergenceDraft
  const message = draft?.authorMessage?.trim()
  if (!draft?.coverage?.complete || draft.stale || !message) return false
  session.messages.push({ role: "user", content: message })
  if (draft.externalPacketHash) {
    for (let index = session.externalPackets.length - 1; index >= 0; index -= 1) {
      const record = session.externalPackets[index]
      if (record.hash === draft.externalPacketHash && record.status === "previewed") {
        record.status = "decision_ready"
        break
      }
    }
  }
  markVisualBriefStale()
  session.convergenceDraft = null
  if (persist()) rememberGenerateContinuation()
  toast("作者决定已加入对话；尚未创建或采用任何设定", "success")
  await nextTick()
  worldWorkspaceRef.value?.focusComposer?.()
  return true
}
function dismissConvergence() { session.convergenceDraft = null }
function handoffFilename() {
  const source = world.sourceDraft || world.sourcePage
  const title = String(source?.title || projectTitle.value || "world").replace(/[^\p{L}\p{N}_-]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "world"
  return `world-handoff-${title}-${String(session.convergenceDraft?.generatedAt || "").slice(0, 10) || "current"}.md`
}
function copyMarkdown(markdown, { missing, title, success, failure }) {
  if (!markdown) return toast(missing, "warning")
  const copy = navigator.clipboard?.writeText
    ? Promise.resolve().then(() => navigator.clipboard.writeText(markdown))
    : Promise.reject(new Error("clipboard unavailable"))
  copy.then(() => toast(success, "success")).catch(() => {
    openOwnedModal(title, `<textarea class="form-textarea generate-handoff-manual" rows="20" readonly>${esc(markdown)}</textarea>`, [], { size: "large" })
    toast(failure, "warning")
  })
}
function downloadMarkdown(markdown, { missing, filename, success }) {
  if (!markdown) return toast(missing, "warning")
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }))
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url)
  toast(success, "success")
}
function copyWorldHandoff() {
  return copyMarkdown(worldHandoffMarkdown.value, {
    missing: "请先完成一次范围完整、未过期的收束",
    title: "手动复制创作交接快照",
    success: "创作交接快照已复制；不会创建或采用设定",
    failure: "自动复制失败；快照已保留，可手动选择或下载",
  })
}
function downloadWorldHandoff() {
  return downloadMarkdown(worldHandoffMarkdown.value, {
    missing: "请先完成一次范围完整、未过期的收束",
    filename: handoffFilename(),
    success: "创作交接快照已下载；文件由你保管并决定是否交给外部工具",
  })
}
function createVisualBrief() {
  const draft = session.convergenceDraft
  if (!draft?.coverage?.complete || draft.stale) return toast("请先完成一次范围完整、未过期的收束", "warning")
  if (session.visualBrief && !confirm("将用当前收束重新准备视觉简报，现有本地简报编辑会被替换。继续吗？")) return false
  const source = world.sourceDraft || world.sourcePage
  const sourceTitle = source?.title || ""
  const sourceLabel = source
    ? `${sourceTitle || "未命名世界笔记"} · ${world.sourceDraft ? "服务器工作稿" : "已发布世界笔记"}`
    : "当前项目相关资料；尚不能证明全项目所有来源未变化"
  session.visualBrief = visualBriefFromConvergence(draft, { sourceLabel, sourceTitle })
  toast("视觉简报草稿已建立；尚未生成图片或写入项目", "success")
  return true
}
function editVisualBrief(field, value) {
  const brief = session.visualBrief
  if (!brief || !visualBriefCurrent.value) return false
  const textFields = new Set(["mustKeep", "exactLabels", "openItems", "avoid"])
  if (field === "purpose") {
    if (!VISUAL_BRIEF_PURPOSE_OPTIONS.some((item) => item.value === value)) return false
    brief.purpose = value
  } else if (textFields.has(field)) brief[field] = String(value || "").slice(0, VISUAL_BRIEF_FIELD_LIMIT)
  else return false
  brief.confirmedAt = null
  return true
}
function confirmVisualBrief() {
  const brief = session.visualBrief
  if (!brief || !visualBriefCurrent.value) return toast("来源或作者决定已变化，请重新收束后再确认", "warning")
  if (!brief.mustKeep.trim() || !brief.avoid.trim()) return toast("请至少写清必须保留和不要新增的边界", "warning")
  brief.confirmedAt = new Date().toISOString()
  toast("视觉简报已确认；仍未生成图片、地图或事实", "success")
  return true
}
function visualBriefFilename() {
  return handoffFilename().replace(/^world-handoff-/, "world-visual-brief-")
}
function copyVisualBrief() {
  return copyMarkdown(visualBriefMarkdown.value, {
    missing: "请先确认一份来源未变化的视觉简报",
    title: "手动复制视觉简报",
    success: "视觉简报已复制；不会创建图片或采用设定",
    failure: "自动复制失败；简报已保留，可手动选择或下载",
  })
}
function downloadVisualBrief() {
  return downloadMarkdown(visualBriefMarkdown.value, {
    missing: "请先确认一份来源未变化的视觉简报",
    filename: visualBriefFilename(),
    success: "视觉简报已下载；外部候选图由你保管",
  })
}
async function previewVisualMap() {
  if (!visualBriefMarkdown.value) return false
  toast("视觉简报已保留；地图册只会在你确认后开始生成", "success")
  return router.navigate("map", null, true)
}
function openConvergenceSource(source) {
  const ref = source?.sourceRef || {}
  const type = ref.source_type || ""
  if (["author_message", "author_pasted_context"].includes(type)) {
    document.getElementById("generate-chat-messages")?.scrollIntoView?.({ block: "start" })
    return
  }
  if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃这些编辑并打开来源吗？")) return
  if (["world_bible_page", "world_bible_page_draft", "world_bible_synopsis"].includes(type)) {
    const query = new URLSearchParams()
    if (ref.page_id || props.sourcePageId) query.set("page_id", ref.page_id || props.sourcePageId)
    router.navigate("world", "bible", true, query)
    return
  }
  if (type === "writing_chapter" && ref.chapter_index) {
    router.navigate("writing", null, true, new URLSearchParams({ chapter_index: String(ref.chapter_index) }))
    return
  }
  if (["core_entity", "entity", "profile", "event"].includes(type)) {
    const query = new URLSearchParams()
    if (ref.title) query.set("q", ref.title)
    router.navigate("world", "objects", true, query)
    return
  }
  if (["entity_relation", "relation"].includes(type)) return router.navigate("world", "relations", true)
  if (type === "map_fact") return router.navigate("map", null, true)
  toast("该来源已纳入本轮范围，但当前没有更精确的打开入口", "info")
}
function requestWorldSuggestion() {
  if (worldBusy.value) return false
  if (explorationSelection.value && explorationDraft.value?.stale) return toast("探索所依据的材料已变化，请重新探索后再生成", "warning")
  const suggestion = worldResult.value?.suggestion
  if (!explorationSelection.value && suggestion?.id && suggestion.status === "pending") {
    openOwnedModal(
      "如何继续这个提案？",
      `<div class="generate-revision-choice"><p><strong>修订此版</strong>：新提案会替代当前待处理版；旧版保留为历史，不能再单独采用。</p><p><strong>另起方案</strong>：保留当前版，两个方案都可独立处理。</p></div>`,
      [
        { text: "取消", class: "btn-ghost", handler: closeModal },
        { text: "修订此版", class: "btn", handler: () => { closeModal(); return generateWorldSuggestion(suggestion.id) } },
        { text: "另起方案", class: "btn", handler: () => { closeModal(); return generateWorldSuggestion() } },
      ],
    )
    return true
  }
  if (!explorationSelection.value && !session.messages.length && !composer.value.trim()) return toast("请先聊天、粘贴已有对话，或选择一条相邻探索", "warning")
  return generateWorldSuggestion()
}
async function generateWorldSuggestion(revisesSuggestionId = null) {
  if (worldBusy.value) return false
  if (explorationSelection.value && (explorationDraft.value?.stale || revisesSuggestionId)) return toast("这条探索只能生成独立建议；材料变化后请重新探索", "warning")
  if (!explorationSelection.value && !session.messages.length && !composer.value.trim()) return toast("请先聊天、粘贴已有对话，或选择一条相邻探索", "warning")
  if (pageProposalDirty.value && !confirm("整页提案仍有未应用的编辑。生成成功后将用新版替换；如果生成失败，当前编辑会继续保留。是否继续？")) return
  captureComposer(); if (persist()) rememberGenerateContinuation(); suggestionPending.value = true; worldError.value = ""
  const operationId = createOperationId()
  const explored = Boolean(explorationSelection.value)
  const meta = {
    session_key: props.sessionKey,
    target_kind: props.targetKind,
    source_page_id: props.sourcePageId,
    revises_suggestion_id: revisesSuggestionId,
    explored,
    proposal_draft_baseline: JSON.stringify(session.pageProposalDraft),
  }
  persistActiveWorkflow({ taskId: operationId, workflowType: "world_generation_suggestion", label: "生成世界设定建议", projectId: props.projectId, view: "generate", meta }, receiptStorage)
  worldTaskProgress.value = normalizeTaskProgress({ task_id: operationId, task_type: "world_generation_suggestion", status: "pending" }, "world_generation_suggestion")
  try {
    const payload = currentWorldPayload()
    if (revisesSuggestionId) payload.revises_suggestion_id = revisesSuggestionId
    if (explorationSelection.value) payload.exploration_selection = { ...explorationSelection.value, source_keys: [...explorationSelection.value.source_keys] }
    const response = await api.generate.enqueueWorldSuggestion({ ...payload, operation_id: operationId })
    if (owner.isDisposed()) return true
    const taskId = response?.task_id || operationId
    if (taskId !== operationId) {
      clearActiveWorkflow(operationId, receiptStorage)
      persistActiveWorkflow({ taskId, workflowType: "world_generation_suggestion", label: "生成世界设定建议", projectId: props.projectId, view: "generate", meta }, receiptStorage)
    }
    startWorldTaskPolling(taskId, meta)
    toast("已开始生成，可以先去处理其他内容", "success")
    return true
  } catch (err) {
    if (Number(err?.status) >= 400 && Number(err?.status) < 500) {
      clearActiveWorkflow(operationId, receiptStorage)
      worldTaskPoller?.stop()
      worldTaskPoller = null
      if (!owner.isDisposed()) {
        if (err?.status === 409 && explorationDraft.value) explorationDraft.value.stale = true
        worldTaskProgress.value = null
        worldError.value = `生成失败：${err?.message || "未知错误"}`
        toast(err?.status === 409 ? "提案、探索材料或来源在生成期间已变化；没有创建过时建议，当前对话和编辑仍保留。" : worldError.value, err?.status === 409 ? "warning" : "error")
      }
    } else startWorldTaskPolling(operationId, meta)
    return false
  } finally { suggestionPending.value = false }
}
function startWorldTaskPolling(taskId, meta) {
  worldTaskPoller?.stop()
  worldTaskProgress.value = normalizeTaskProgress({ task_id: taskId, task_type: "world_generation_suggestion", status: "pending" }, "world_generation_suggestion")
  worldTaskPoller = pollTaskProgress({
    taskId,
    workflowType: "world_generation_suggestion",
    novelId: props.projectId,
    receiptStorage,
    apiClient: api,
    onUpdate: (progress) => { if (!owner.isDisposed()) worldTaskProgress.value = progress },
    onDone: (progress, task) => {
      clearActiveWorkflow(taskId, receiptStorage)
      if (owner.isDisposed()) return
      const response = task?.result || {}
      worldTaskProgress.value = progress
      if (JSON.stringify(session.pageProposalDraft) !== meta.proposal_draft_baseline) {
        previousWorldResult.value = response.result || previousWorldResult.value
        toast("新建议已生成；当前未应用编辑已保留", "success")
        return
      }
      previousWorldResult.value = meta.revises_suggestion_id ? worldResult.value : null
      worldResult.value = response.result || null
      sourceRevisionResult.value = response.source_revision || null
      session.suggestionId = response.result?.suggestion?.id || null
      entityContextUsage.value = response.context_usage || null
      discardPageProposalDraft()
      dismissExploration()
      toast(meta.revises_suggestion_id ? "修订版已进入待处理，旧版已封存" : sourceRevisionResult.value ? "相邻新页与一条来源页修订已进入待处理" : meta.explored ? "所选相邻新页已进入待处理；来源页无需另建修订" : worldResult.value?.kind === "core_entity" ? "世界对象建议已进入待处理" : "世界书整页提案已进入待处理", "success")
    },
    onFailed: (progress) => {
      clearActiveWorkflow(taskId, receiptStorage)
      if (owner.isDisposed()) return
      worldTaskProgress.value = progress
      worldError.value = progress.errorMessage || "生成失败，请重新开始"
    },
  })
}
async function cancelWorldTask() {
  const taskId = worldTaskProgress.value?.taskId
  if (!taskId) return false
  await api.tasks.cancel(taskId, props.projectId)
  return true
}
function dismissWorldTask() { worldTaskProgress.value = null }
async function applyWorldPage(payload) {
  if (worldBusy.value) return false
  const suggestionId = worldResult.value?.suggestion?.id || session.suggestionId; if (!suggestionId || worldResult.value?.kind === "core_entity") return
  const submittedDraft = JSON.stringify(session.pageProposalDraft)
  applyPending.value = true; const scope = owner.begin()
  try { const response = await api.generate.applyWorldPageDraft(suggestionId, payload, props.projectId, { signal: scope.controller.signal }); if (JSON.stringify(session.pageProposalDraft) === submittedDraft) { discardPageProposalDraft(); persist() } if (!owner.isActive(scope)) return; writeCreativeContinuation(props.projectId, { destination: "world_bible_draft", route: { draft_id: response.draft.id, page_id: response.draft.page_id || null } }); toast("提案已应用到工作稿，尚未发布", "success"); const query = new URLSearchParams({ draft_id: response.draft.id }); if (response.draft.page_id) query.set("page_id", response.draft.page_id); router.navigate("world", "bible", true, query) }
  catch (err) { if (!owner.isActive(scope)) return; toast(err?.status === 409 ? "来源工作稿已变更，本次提案未覆盖新修改。请重新生成。" : `应用失败：${err?.message || "未知错误"}`, err?.status === 409 ? "warning" : "error") }
  finally { owner.finish(scope); applyPending.value = false }
}
function selectTarget(kind) { if (kind === props.targetKind) return; if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并切换目标吗？")) return; persist(); const query = new URLSearchParams({ tab: "world", target: kind }); if (props.sourcePageId) query.set("source_page_id", props.sourcePageId); router.navigate("generate", null, true, query) }
function returnToWorldBible() { if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并离开吗？")) return; persist(); const query = new URLSearchParams(); if (props.sourcePageId) query.set("page_id", props.sourcePageId); router.navigate("world", "bible", true, query) }
function openStoryOutline() { if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并前往故事总览吗？")) return; persist(); router.navigate("outline", "story-outline") }
function openSourceRevision() { const query = new URLSearchParams(); if (props.sourcePageId) query.set("page_id", props.sourcePageId); router.navigate("world", "bible", true, query) }
function openReview() { router.navigate("world", "review-objects", true) }

async function changePovChapter(value) { const chapterIndex = value ? Number(value) : null; const generation = ++povSceneGeneration; povForm.value = { ...povForm.value, chapterIndex, sceneId: "", viewpointCharacterId: "" }; povSubmission.value = null; pov.scenes = []; if (!chapterIndex) return; const scope = owner.begin(); try { const data = await api.outline.listScenesByChapter(props.projectId, chapterIndex); if (generation === povSceneGeneration && Number(povForm.value.chapterIndex) === chapterIndex && owner.isActive(scope)) pov.scenes = Array.isArray(data) ? data : data?.items || [] } catch (err) { if (generation === povSceneGeneration && Number(povForm.value.chapterIndex) === chapterIndex && owner.isActive(scope)) pov.warning = `加载场景失败：${err?.message || "未知错误"}` } finally { owner.finish(scope) } }
function changePovScene(id) { const scene = pov.scenes.find((item) => item.id === id); povForm.value = { ...povForm.value, sceneId: id || "", viewpointCharacterId: scene?.pov_character_id || "" }; povSubmission.value = null }
function abortableDelay(ms, signal) { return new Promise((resolve, reject) => { const timer = setTimeout(resolve, ms); signal.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")) }, { once: true }) }) }
async function waitForPovTask(taskId, scope) { while (owner.isActive(scope)) { let task; try { task = await api.tasks.get(taskId, props.projectId) } catch (err) { if (!owner.isActive(scope)) throw new DOMException("Aborted", "AbortError"); if (Number(err?.status) === 404) { clearActiveWorkflow(taskId, receiptStorage); throw new Error("未找到原任务，请重新开始。") } await abortableDelay(1500, scope.controller.signal); continue } if (!owner.isActive(scope)) throw new DOMException("Aborted", "AbortError"); povProgress.value = Number(task?.progress || 0); if (task?.status === "done") { if (!task.result?.draft_id) throw new Error("任务已完成，但正文建议未能加载"); return task } if (task?.status === "failed") { clearActiveWorkflow(taskId, receiptStorage); throw new Error(task.error_message || task.result?.error_message || "角色视角正文生成失败") } if (task?.status === "cancelled") { clearActiveWorkflow(taskId, receiptStorage); throw new Error("角色视角正文生成已取消") } await abortableDelay(1500, scope.controller.signal) } throw new DOMException("Aborted", "AbortError") }
async function generatePov() {
  if (povPending.value) return false
  const form = { ...povForm.value }; if (!form.chapterIndex) return toast("请先选择章节", "warning"); if (!form.sceneId) return toast("请先选择场景", "warning"); if (!form.viewpointCharacterId) return toast("请先选择视角角色", "warning")
  povPending.value = true; povProgress.value = null; povError.value = ""; const scope = owner.begin()
  try { const confirmation = await confirmAiReference({ novel_id: props.projectId, action: "writing.generate", task: "基于所选场景和视角角色的有限认知，生成正文建议预览", scope: "chapter", chapter_index: form.chapterIndex, scene_id: form.sceneId, reveal_mode: "character", viewpoint_character_id: form.viewpointCharacterId, character_ids: [form.viewpointCharacterId], include_pending_objects: false, budget_tokens: 0 }); if (!owner.isActive(scope)) return; const operationId = createOperationId(); const meta = { kind: "pov_prose", sessionKey: props.sessionKey, chapterIndex: form.chapterIndex, sceneId: form.sceneId, viewpointCharacterId: form.viewpointCharacterId, sceneLabel: pov.scenes.find((item) => item.id === form.sceneId)?.title || "", roleLabel: pov.characters.find((item) => characterId(item) === form.viewpointCharacterId)?.name || "" }; persistActiveWorkflow({ taskId: operationId, workflowType: "writing_generate", label: "生成角色视角正文", projectId: props.projectId, view: "generate", meta }, receiptStorage); povTaskId.value = operationId; let result; try { result = await api.writing.generate({ novel_id: props.projectId, chapter_index: form.chapterIndex, title: pov.chapters.find((item) => Number(item.chapter_index) === Number(form.chapterIndex))?.title || `第 ${form.chapterIndex} 章`, instruction: buildPovInstruction(form.instruction, confirmation.user_note), context_confirmation_id: confirmation.id, operation_id: operationId }) } catch (err) { if (Number(err?.status) >= 400 && Number(err?.status) < 500) { clearActiveWorkflow(operationId, receiptStorage); throw err } result = { task_id: operationId } } if (!owner.isActive(scope)) return; const taskId = result?.task_id || operationId; if (taskId !== operationId) { clearActiveWorkflow(operationId, receiptStorage); persistActiveWorkflow({ taskId, workflowType: "writing_generate", label: "生成角色视角正文", projectId: props.projectId, view: "generate", meta }, receiptStorage) } const task = await waitForPovTask(taskId, scope); result = { ...result, ...(task.result || {}), task_status: task.status }; if (!owner.isActive(scope)) return; povSubmission.value = { result, ...meta }; toast("角色视角正文建议已生成", "success") }
  catch (err) { if (!owner.isActive(scope) || err?.name === "AbortError") return; if (err?.message === "已取消 AI 参考资料确认") return; povError.value = err?.message || "未知错误"; toast(`角色视角正文生成失败：${povError.value}`, "error") }
  finally { owner.finish(scope); povPending.value = false; povTaskId.value = null }
}
async function cancelPovTask() { if (!povTaskId.value) return false; await api.tasks.cancel(povTaskId.value, props.projectId); return true }
async function recoverPovTask(workflow) { povPending.value = true; povProgress.value = null; povError.value = ""; povTaskId.value = workflow.taskId; const scope = owner.begin(); try { const task = await waitForPovTask(workflow.taskId, scope); if (!owner.isActive(scope)) return; povSubmission.value = { result: task.result || {}, ...(workflow.meta || {}) }; toast("已恢复角色视角正文建议", "success") } catch (err) { if (owner.isActive(scope) && err?.name !== "AbortError") { povError.value = err?.message || "未知错误"; toast(`角色视角正文生成失败：${povError.value}`, "error") } } finally { owner.finish(scope); povPending.value = false; povTaskId.value = null } }
function openPovResult(submission) { const draftId = submission?.result?.draft_id || submission?.result?.draft?.id || ""; const workflow = recoverActiveWorkflows(props.projectId, receiptStorage).find((item) => item.workflowType === "writing_generate" && item.view === "generate" && item.meta?.kind === "pov_prose" && item.meta?.sessionKey === props.sessionKey); if (workflow) clearActiveWorkflow(workflow.taskId, receiptStorage); appState.viewStates.writing = { projectId: props.projectId, currentChapter: submission.chapterIndex, currentDraftId: draftId || null, isReadonly: Boolean(draftId) }; const query = new URLSearchParams({ chapter_index: String(submission.chapterIndex) }); if (draftId) query.set("draft_id", draftId); router.navigate("writing", null, true, query) }
function openPovWriting() { router.navigate("writing") }

function selectTaskPreset(key) { if (!TASK_PRESETS[key]) return; taskPreset.value = key; taskForm.value = applyTaskPreset(taskForm.value, key) }
async function compileTask(silent) { if (taskPending.value) return false; const payload = buildTaskPayload(props.projectId, taskForm.value); const error = validateTaskPayload(payload); if (error) return toast(error, "warning"); lastContextRequest.value = payload; lastContextSource.value = "task"; lastContextMarkdown.value = ""; taskPending.value = true; taskError.value = ""; const scope = owner.begin(); try { const data = await api.context.compile(payload, { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; lastContextBundle.value = data; activeTab.value = "preview" } catch (err) { if (!owner.isActive(scope)) return; taskError.value = `编译失败：${err?.message || "未知错误"}`; if (!silent) toast(taskError.value, "error") } finally { owner.finish(scope); taskPending.value = false } }
async function renderTaskMarkdown() { if (taskPending.value) return false; const payload = lastContextRequest.value || buildTaskPayload(props.projectId, taskForm.value); const error = validateTaskPayload(payload); if (error) return toast(error, "warning"); taskPending.value = true; taskError.value = ""; const scope = owner.begin(); try { const data = await api.context.render(payload, { signal: scope.controller.signal }); if (owner.isActive(scope)) lastContextMarkdown.value = data?.markdown || "" } catch (err) { if (owner.isActive(scope)) taskError.value = `渲染失败：${err?.message || "未知错误"}` } finally { owner.finish(scope); taskPending.value = false } }
function copyTaskMarkdown() { if (!lastContextMarkdown.value) return; navigator.clipboard.writeText(lastContextMarkdown.value).then(() => toast("上下文 Markdown 已复制到剪贴板", "success")).catch(() => toast("复制失败，请手动选择复制", "warning")) }
function exportTaskMarkdown() { if (!lastContextMarkdown.value) return; const url = URL.createObjectURL(new Blob([lastContextMarkdown.value], { type: "text/markdown;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `context-${projectTitle.value || "project"}-${Date.now()}.md`; link.click(); URL.revokeObjectURL(url); toast("上下文已导出为 Markdown 文件", "success") }
async function applyTaskToChat() { if (!taskForm.value.task) return toast("当前没有任务内容", "warning"); session.messages.push({ role: "user", content: taskForm.value.task }); if (lastContextBundle.value?.sections?.length) session.messages.push({ role: "assistant", content: `已加载 ${lastContextBundle.value.sections.length} 段上下文，共 ${lastContextBundle.value.total_tokens || 0} tokens。` }); activeTab.value = "world"; await ensureWorld() }

function captureModalOwner(control = null) {
  const body = document.getElementById("modal-body")
  const overlay = document.getElementById("modal-overlay")
  return { generation: modalGeneration, body, root: body?.firstChild || null, overlay, visible: overlay ? !overlay.classList.contains("hidden") : null, control }
}
function modalStateUnchanged(modalOwner) {
  const body = document.getElementById("modal-body")
  const overlay = document.getElementById("modal-overlay")
  return Boolean(modalOwner && body
    && modalOwner.generation === modalGeneration
    && modalOwner.body === body
    && modalOwner.root === body.firstChild
    && modalOwner.overlay === overlay
    && modalOwner.visible === (overlay ? !overlay.classList.contains("hidden") : null))
}
function ownsModal(modalOwner) {
  return modalStateUnchanged(modalOwner)
    && modalOwner.root?.isConnected
    && (!modalOwner.control || (modalOwner.control.isConnected && modalOwner.body.contains(modalOwner.control)))
    && (!modalOwner.overlay || modalOwner.visible)
}
function openOwnedModal(title, body, buttons, options) { modalGeneration += 1; showModalHtml(title, body, buttons, options); ownedModal = captureModalOwner() }
function templateEditorBody(item) { return `<div class="generate-template-editor"><div><label for="generate-template-editor-select">现有模板</label><select class="form-select" id="generate-template-editor-select">${templates.value.map((entry) => `<option value="${esc(entry.value)}" ${entry.value === item.value ? "selected" : ""}>${esc(entry.is_builtin ? entry.label : `自定义 · ${entry.label}`)}</option>`).join("")}</select></div><div><label for="generate-template-editor-name">模板名称</label><input class="form-input" id="generate-template-editor-name" value="${esc(item.label)}" maxlength="80" /></div><div><label for="generate-template-editor-prompt">提示词</label><textarea class="form-textarea" id="generate-template-editor-prompt" maxlength="8000">${esc(item.prompt || "")}</textarea></div><p class="generate-template-editor-help">${item.is_builtin ? "内置模板为只读；点击“保存模板”会创建项目级副本。" : "修改自定义模板会生成新版本。"}</p><button class="btn btn-sm" id="generate-template-history-load" type="button" ${item.is_builtin ? "hidden" : ""}>版本历史</button><div id="generate-template-history" class="generate-template-history"></div></div>` }
function selectedEditorTemplate() { const value = document.getElementById("generate-template-editor-select")?.value || session.selectedTemplateId; return templates.value.find((item) => item.value === value) || templates.value[0] }
function editorValues() { return { item: selectedEditorTemplate(), name: document.getElementById("generate-template-editor-name")?.value?.trim() || "", prompt: document.getElementById("generate-template-editor-prompt")?.value?.trim() || "" } }
async function saveTemplate() {
  if (templateMutationPending) return false
  const modalOwner = captureModalOwner(document.getElementById("generate-template-editor-select"))
  const { item, name, prompt } = editorValues()
  if (!prompt) return toast("请输入模板提示词", "warning"), false
  templateMutationPending = true
  const scope = owner.begin()
  try {
    let updated
    if (item.is_builtin) {
      const copied = copiedBuiltinTemplate?.sourceId === item.id
        ? copiedBuiltinTemplate.template
        : await api.generate.copyPromptTemplate(item.id, { novel_id: props.projectId, name: item.label })
      copiedBuiltinTemplate = { sourceId: item.id, template: copied }
      updated = await api.generate.updatePromptTemplate(copied.id, props.projectId, { prompt_text: prompt, template_version: copied.version_number })
      copiedBuiltinTemplate = null
    } else {
      if (!name) return toast("请输入模板名称", "warning"), false
      updated = await api.generate.updatePromptTemplate(item.id, props.projectId, { name, prompt_text: prompt, template_version: item.version_number })
    }
    if (!owner.isActive(scope) || !ownsModal(modalOwner)) return true
    const normalized = normalizeTemplate(updated)
    templates.value = item.is_builtin ? [...templates.value, normalized] : templates.value.map((entry) => entry.id === item.id ? normalized : entry)
    session.selectedTemplateId = normalized.value
    toast("模板已保存", "success")
    return true
  } catch (err) {
    if (!owner.isActive(scope) || !ownsModal(modalOwner)) return true
    toast(`保存模板失败：${err?.message || "未知错误"}`, "error")
    return false
  } finally { owner.finish(scope); templateMutationPending = false }
}
async function createTemplate() {
  if (templateMutationPending) return false
  const modalOwner = captureModalOwner(document.getElementById("generate-template-editor-select"))
  const { name, prompt } = editorValues()
  if (!name) return toast("请输入模板名称", "warning"), false
  if (!prompt) return toast("请输入模板提示词", "warning"), false
  templateMutationPending = true
  const scope = owner.begin()
  try {
    const created = await api.generate.createPromptTemplate({ novel_id: props.projectId, name, object_template: "custom", prompt_text: prompt })
    if (!owner.isActive(scope) || !ownsModal(modalOwner)) return true
    const normalized = normalizeTemplate(created)
    templates.value = [...templates.value, normalized]
    session.selectedTemplateId = normalized.value
    toast("新模板已创建", "success")
    return true
  } catch (err) {
    if (!owner.isActive(scope) || !ownsModal(modalOwner)) return true
    toast(`创建模板失败：${err?.message || "未知错误"}`, "error")
    return false
  } finally { owner.finish(scope); templateMutationPending = false }
}
function bindTemplateModal() { const select = document.getElementById("generate-template-editor-select"); select?.addEventListener("change", () => { const item = templates.value.find((entry) => entry.value === select.value); if (!item) return; document.getElementById("generate-template-editor-name").value = item.label; document.getElementById("generate-template-editor-prompt").value = item.prompt || ""; document.getElementById("generate-template-history-load").hidden = item.is_builtin; document.getElementById("generate-template-history")?.replaceChildren() }); document.getElementById("generate-template-history-load")?.addEventListener("click", loadTemplateHistory) }
async function loadTemplateHistory() {
  const item = selectedEditorTemplate()
  const select = document.getElementById("generate-template-editor-select")
  const container = document.getElementById("generate-template-history")
  if (!container || item.is_builtin) return
  const selectedValue = select?.value
  const modalOwner = captureModalOwner(container)
  container.textContent = "加载版本历史…"
  const scope = owner.begin()
  try {
    const data = await api.generate.listPromptTemplateRevisions(item.id, props.projectId)
    if (!owner.isActive(scope) || !ownsModal(modalOwner) || select?.value !== selectedValue) return
    const revisions = Array.isArray(data) ? data : data?.items || []
    container.replaceChildren(...revisions.map((revision) => {
      const article = document.createElement("article"); article.className = "generate-template-revision"
      const title = document.createElement("strong"); title.textContent = `v${revision.version_number || "-"}`
      const pre = document.createElement("pre"); pre.textContent = String(revision.prompt_text || "").slice(0, 800)
      const button = document.createElement("button"); button.className = "btn btn-sm"; button.textContent = "载入到编辑器"
      button.addEventListener("click", () => { if (ownsModal(modalOwner) && select?.value === selectedValue) document.getElementById("generate-template-editor-prompt").value = revision.prompt_text || "" })
      article.append(title, pre, button)
      return article
    }))
  } catch (err) {
    if (owner.isActive(scope) && ownsModal(modalOwner) && select?.value === selectedValue) container.textContent = `版本历史加载失败：${err?.message || "未知错误"}`
  } finally { owner.finish(scope) }
}
function openTemplateEditor() { const item = templates.value.find((entry) => entry.value === session.selectedTemplateId) || templates.value[0]; openOwnedModal("编辑模板", templateEditorBody(item), [{ text: "保存模板", class: "btn-primary", handler: saveTemplate }, { text: "新建模板", class: "btn", handler: createTemplate }, { text: "关闭", class: "btn-ghost", handler: closeModal }]); bindTemplateModal() }

async function runInBatches(items, size, fn) { const output = []; for (let index = 0; index < items.length; index += size) output.push(...await Promise.all(items.slice(index, index + size).map(fn))); return output }
async function openChapterPicker() {
  const modalOwner = captureModalOwner()
  const scope = owner.begin()
  try {
    const data = await api.writing.listChapters(props.projectId)
    if (!owner.isActive(scope) || !modalStateUnchanged(modalOwner)) return
    const summaries = data?.chapters || []
    if (!summaries.length) return toast("当前项目还没有正文，可直接聊天或粘贴外部对话生成建议", "info")
    const previews = await runInBatches(summaries, 5, async (item) => {
      try {
        const draft = item.id ? await api.writing.get(item.id, props.projectId) : await api.writing.getDraft(item.chapter_index, props.projectId)
        return { chapter_index: item.chapter_index, title: draft.title || item.title || `第${item.chapter_index}章`, excerpt: String(draft.content || "").replace(/\s+/g, " ").trim().slice(0, 120) }
      } catch { return { chapter_index: item.chapter_index, title: item.title || `第${item.chapter_index}章`, excerpt: "" } }
    })
    if (!owner.isActive(scope) || !modalStateUnchanged(modalOwner)) return
    const selected = new Set(session.selectedChapters.map((item) => item.chapter_index))
    const body = `<div class="generate-chapter-list">${previews.map((item) => `<label class="generate-chapter-card"><input id="generate-chapter-${esc(item.chapter_index)}" type="checkbox" ${selected.has(item.chapter_index) ? "checked" : ""}/><span><span class="generate-chapter-title">第 ${esc(item.chapter_index)} 章 · ${esc(item.title)}</span><span class="generate-chapter-excerpt">${esc(item.excerpt || "暂无正文摘录")}</span></span></label>`).join("")}</div>`
    openOwnedModal("选择附带正文", body, [{ text: "取消", class: "btn-ghost", handler: closeModal }, { text: "确认选择", class: "btn-primary", handler: () => { const next = previews.filter((item) => document.getElementById(`generate-chapter-${item.chapter_index}`)?.checked); if (next.length > AI_SELECTED_CHAPTER_LIMIT) return toast(`每次最多附带 ${AI_SELECTED_CHAPTER_LIMIT} 章正文`, "warning"), false; session.selectedChapters = next; closeModal() } }])
  } catch (err) {
    if (owner.isActive(scope) && modalStateUnchanged(modalOwner)) toast(`加载章节失败：${err?.message || "未知错误"}`, "error")
  } finally { owner.finish(scope) }
}
function viewGenerationContext(kind) { const usage = kind === "chat" ? chatContextUsage.value : entityContextUsage.value; if (!usage) return toast("本次生成没有返回可审计的上下文记录", "warning"); const body = `<div class="generate-context-header"><span class="generate-context-stat">${esc(usage.section_key || "world_bible_synopsis")}</span><span class="generate-context-meta">状态：${esc(usage.status || "unknown")}</span><span class="generate-context-meta">Tokens：${esc(usage.token_count || 0)}</span></div><table class="data-table"><tbody><tr><th>Revision</th><td>${esc(usage.revision_id || "确定性降级/未包含")}</td></tr><tr><th>Source hash</th><td>${esc(usage.source_hash || "-")}</td></tr><tr><th>Block hash</th><td>${esc(usage.block_hash || "-")}</td></tr><tr><th>Context snapshot</th><td>${esc(usage.context_snapshot_id || "-")}</td></tr><tr><th>Stale</th><td>${usage.stale ? "是" : "否"}</td></tr><tr><th>Fallback</th><td>${usage.fallback ? "是" : "否"}</td></tr></tbody></table>`; openOwnedModal("本次实际使用的上下文", body, [], { size: "large" }) }

const recoveredWorldTask = recoverActiveWorkflows(props.projectId, receiptStorage).find((item) => item.workflowType === "world_generation_suggestion" && item.meta?.session_key === props.sessionKey)
if (recoveredWorldTask) startWorldTaskPolling(recoveredWorldTask.taskId, recoveredWorldTask.meta)
const recoveredPovTask = recoverActiveWorkflows(props.projectId, receiptStorage).find((item) => item.workflowType === "writing_generate" && item.view === "generate" && item.meta?.kind === "pov_prose" && item.meta?.sessionKey === props.sessionKey)
if (recoveredPovTask) void recoverPovTask(recoveredPovTask)

onBeforeUnmount(() => { disarmBeforeUnload(); persist(); worldTaskPoller?.stop(); owner.dispose(); if (ownsModal(ownedModal)) closeModal() })
</script>
