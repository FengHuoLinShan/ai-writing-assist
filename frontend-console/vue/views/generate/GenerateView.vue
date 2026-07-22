<template>
  <div class="view-header view-header--with-tabs generate-toolbar">
    <div class="subnav generate-subtabs" role="tablist" aria-label="生成模式">
      <button v-for="item in tabs" :key="item.key" class="generate-subtab" :class="{ active: activeTab === item.key }" data-action="switch-generate-subtab" :data-subtab="item.key" @click="switchTab(item.key)">{{ item.label }}</button>
    </div>
    <div class="view-header__actions">
      <span v-if="projectTitle" class="view-toolbar__project" :title="projectTitle">{{ projectTitle }}</span>
      <template v-if="activeTab === 'world'">
        <button class="btn btn-sm" data-action="send-chat-message" :disabled="worldBusy" @click="sendChat">发送</button>
        <button class="btn btn-sm btn-primary" data-action="generate-world-suggestion" :disabled="worldBusy" @click="generateWorldSuggestion">{{ generateLabel }}</button>
      </template>
      <button v-else-if="activeTab === 'pov_prose'" class="btn btn-sm btn-primary" data-action="generate-pov-prose" :disabled="povPending" @click="generatePov">生成角色视角正文</button>
      <template v-else-if="activeTab === 'task'">
        <button class="btn btn-sm btn-primary" data-action="run-task" :disabled="taskPending" @click="compileTask(false)">编译上下文</button>
        <button class="btn btn-sm" data-action="preview-task-context" :disabled="taskPending" @click="compileTask(true)">预览上下文</button>
        <button class="btn btn-sm" data-action="render-task-md" :disabled="taskPending" @click="renderTaskMarkdown">渲染 Markdown</button>
        <button class="btn btn-sm" data-action="apply-to-chat" @click="applyTaskToChat">应用到聊天</button>
      </template>
    </div>
  </div>

  <WorldWorkspace v-if="activeTab === 'world'"
    :project-id="projectId" :source-page-id="sourcePageId" :target-kind="targetKind" :source-page="world.sourcePage" :source-draft="world.sourceDraft"
    :warning="world.warning" :templates="templates" :activation-profiles="activationProfiles" :categories="world.categories" :page-templates="world.pageTemplates"
    :scenes="world.scenes" :threads="world.threads" :characters="world.characters" :entities="world.entities" :result="worldResult"
    :chat-context-usage="chatContextUsage" :entity-context-usage="entityContextUsage" :busy="worldBusy" :loading-result="suggestionPending" :result-error="worldError"
    v-model:selected-template-id="session.selectedTemplateId" v-model:messages="session.messages" v-model:composer="composer"
    v-model:quality-mode="session.qualityMode" v-model:include-world-synopsis="session.includeWorldSynopsis" v-model:activation-profile-id="session.activationProfileId"
    v-model:selected-chapters="session.selectedChapters" v-model:selected-scene-id="session.selectedSceneId" v-model:selected-thread-ids="session.selectedThreadIds"
    v-model:selected-character-ids="session.selectedCharacterIds" v-model:selected-entity-ids="session.selectedEntityIds"
    v-model:new-page-type="session.newPageType" v-model:new-page-template-key="session.newPageTemplateKey"
    @select-target="selectTarget" @edit-templates="openTemplateEditor" @return-world-bible="returnToWorldBible" @select-chapters="openChapterPicker"
    @apply-page="applyWorldPage" @proposal-dirty="pageProposalDirty = $event" @clear-result="clearWorldResult" @open-review="openReview" @view-context="viewGenerationContext" />
  <PovProseTab v-else-if="activeTab === 'pov_prose'" v-model:form="povForm" :chapters="pov.chapters" :scenes="pov.scenes" :characters="pov.characters" :warning="pov.warning" :submission="povSubmission" :pending="povPending" :progress="povProgress" :error="povError" @change-chapter="changePovChapter" @change-scene="changePovScene" @open-result="openPovResult" />
  <TaskContextTab v-else-if="activeTab === 'task'" v-model:form="taskForm" :project-id="projectId" :preset="taskPreset" :bundle="lastContextBundle" :markdown="lastContextMarkdown" :pending="taskPending" :error="taskError" @select-preset="selectTaskPreset" @copy-markdown="copyTaskMarkdown" @export-markdown="exportTaskMarkdown" />
  <ContextPreviewTab v-else :bundle="lastContextBundle" :markdown="lastContextMarkdown" :source-text="contextSourceText" :busy="taskPending" @render-markdown="renderTaskMarkdown" @copy-markdown="copyTaskMarkdown" @export-markdown="exportTaskMarkdown" @return="switchTab(lastContextSource === 'world' ? 'world' : 'task')" />
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { getApi, getAppState, getCloseModal, getConfirm, getEsc, getRouter, getShowModalHtml, getToast } from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import WorldWorkspace from "./components/WorldWorkspace.vue"
import PovProseTab from "./components/PovProseTab.vue"
import TaskContextTab from "./components/TaskContextTab.vue"
import ContextPreviewTab from "./components/ContextPreviewTab.vue"
import { createGenerateRequestOwner } from "./requestOwner.js"
import {
  readGenerateComposerDraft,
  readGenerateContextPreview,
  writeGenerateComposerDraft,
  writeGenerateContextPreview,
  writeGenerateSession,
} from "./generateSession.js"
import {
  AI_SELECTED_CHAPTER_LIMIT, OBJECT_TEMPLATES, PAGE_SIZE, TASK_PRESETS, applyTaskPreset,
  buildPovInstruction, buildTaskPayload, buildWorldPayload, characterId, createDefaultTaskForm,
  listItems, normalizeTemplate, validateTaskPayload,
} from "./logic/generateLogic.js"

const props = defineProps({
  projectId: { type: String, default: null }, tab: { type: String, default: "world" }, preset: { type: String, default: "custom" },
  sourcePageId: { type: String, default: null }, targetKind: { type: String, default: "core_entity" }, sessionKey: { type: String, required: true },
  initialSession: { type: Object, required: true }, templates: { type: Array, default: () => [] }, activationProfiles: { type: Array, default: () => [] },
  sourcePage: Object, sourceDraft: Object, worldCategories: { type: Array, default: () => [] }, worldPageTemplates: { type: Array, default: () => [] },
  worldScenes: { type: Array, default: () => [] }, worldThreads: { type: Array, default: () => [] }, worldCharacters: { type: Array, default: () => [] }, worldEntities: { type: Array, default: () => [] },
  worldWorkspaceWarning: String, restoredWorldResult: Object, povChapters: { type: Array, default: () => [] }, povCharacters: { type: Array, default: () => [] }, povLoadWarning: String,
})

const api = getApi(); const appState = getAppState(); const router = getRouter(); const toast = getToast(); const confirm = getConfirm()
const showModalHtml = getShowModalHtml(); const closeModal = getCloseModal(); const esc = getEsc()
const owner = createGenerateRequestOwner({ projectId: props.projectId, sessionKey: props.sessionKey })
const notices = new Set()
const session = reactive({ ...props.initialSession })
const composer = ref(readGenerateComposerDraft(props.sessionKey))
const templates = ref(props.templates.length ? props.templates : [...OBJECT_TEMPLATES])
const activationProfiles = ref(props.activationProfiles)
const activeTab = ref(props.tab)
const taskPreset = ref(TASK_PRESETS[props.preset] ? props.preset : "custom")
const taskForm = ref(applyTaskPreset(createDefaultTaskForm(), taskPreset.value))
const restoredContext = readGenerateContextPreview(props.projectId)
const lastContextBundle = ref(restoredContext.bundle); const lastContextMarkdown = ref(restoredContext.markdown); const lastContextSource = ref(restoredContext.source); const lastContextRequest = ref(restoredContext.request)
const taskPending = ref(false); const taskError = ref("")
const pageProposalDirty = ref(false)
const worldResult = ref(props.restoredWorldResult); const chatContextUsage = ref(null); const entityContextUsage = ref(null); const worldError = ref("")
const chatPending = ref(false); const suggestionPending = ref(false); const applyPending = ref(false)
const world = reactive({ sourcePage: props.sourcePage, sourceDraft: props.sourceDraft, categories: props.worldCategories, pageTemplates: props.worldPageTemplates, scenes: props.worldScenes, threads: props.worldThreads, characters: props.worldCharacters, entities: props.worldEntities, warning: props.worldWorkspaceWarning, loaded: props.tab === "world" })
const pov = reactive({ chapters: props.povChapters, scenes: [], characters: props.povCharacters, warning: props.povLoadWarning, loaded: props.tab === "pov_prose" })
const povForm = ref({ chapterIndex: null, sceneId: "", viewpointCharacterId: "", instruction: "" })
const povSubmission = ref(null); const povPending = ref(false); const povProgress = ref(null); const povError = ref("")
let ownedModal = false

const tabs = [{ key: "world", label: "世界设定" }, { key: "pov_prose", label: "角色视角正文" }, { key: "task", label: "任务" }, { key: "preview", label: "上下文预览" }]
const projectTitle = computed(() => appState?.currentProject?.title || appState?.currentProject?.name || "")
const generateLabel = computed(() => ({ core_entity: "生成世界对象建议", world_bible_page: "生成整页提案", world_bible_new_page: "生成新页提案" })[props.targetKind] || "生成建议")
const worldBusy = computed(() => chatPending.value || suggestionPending.value || applyPending.value)
const contextSourceText = computed(() => lastContextSource.value === "world" ? "世界设定共创" : lastContextSource.value === "task" ? `任务：${TASK_PRESETS[taskPreset.value]?.label || "自定义任务"}` : "")

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
  writeGenerateComposerDraft(props.sessionKey, composer.value)
  return writeGenerateSession(props.sessionKey, session, { notify: notifyOnce })
}
watch(session, persist, { deep: true }); watch(composer, (value) => writeGenerateComposerDraft(props.sessionKey, value))
watch(
  [lastContextBundle, lastContextMarkdown, lastContextSource, lastContextRequest],
  persistContextPreview,
  { deep: true },
)

function confirmDiscard(message) { if (!pageProposalDirty.value) return true; const accepted = confirm(message); if (accepted) pageProposalDirty.value = false; return accepted }
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
    world.categories = listItems(categories); world.pageTemplates = listItems(pageTemplates); world.scenes = listItems(scenes); world.threads = listItems(threads); world.characters = characters
    const characterIds = new Set(characters.flatMap((item) => [item.id, item.entity_id].filter(Boolean)))
    world.entities = entities.filter((item) => item.entity_type !== "character" && !characterIds.has(item.id)); world.loaded = true; world.warning = null
  } catch (err) { if (owner.isActive(scope)) world.warning = `生成上下文加载不完整：${err?.message || "未知错误"}` } finally { owner.finish(scope) }
}
async function ensurePov() {
  if (pov.loaded) return
  const scope = owner.begin()
  try { const [chapters, characters] = await Promise.all([api.writing.listChapters(props.projectId), loadAll((skip) => api.world.listCharacters({ novel_id: props.projectId, skip, limit: PAGE_SIZE }))]); if (!owner.isActive(scope)) return; pov.chapters = chapters?.chapters || []; pov.characters = characters; pov.warning = null; pov.loaded = true }
  catch (err) { if (owner.isActive(scope)) pov.warning = `加载章节或角色失败：${err?.message || "未知错误"}` } finally { owner.finish(scope) }
}

async function switchTab(tab) { if (!tabs.some((item) => item.key === tab) || tab === activeTab.value) return; if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并切换标签吗？")) return; activeTab.value = tab; if (tab === "world") await ensureWorld(); if (tab === "pov_prose") await ensurePov() }
function currentWorldPayload() { return buildWorldPayload({ ...session, projectId: props.projectId, sourcePageId: props.sourcePageId, targetKind: props.targetKind, sourcePage: world.sourcePage, sourceDraft: world.sourceDraft, templates: templates.value, activationProfiles: activationProfiles.value, worldPageTemplates: world.pageTemplates }) }
function captureComposer() { const text = composer.value.trim(); if (!text) return false; session.messages.push({ role: "user", content: text }); composer.value = ""; return true }

async function sendChat() {
  if (worldBusy.value) return false
  if (!composer.value.trim()) return toast("请输入要聊的内容", "warning")
  captureComposer(); const pending = reactive({ role: "assistant", content: "正在思考...", pending: true }); session.messages.push(pending); chatPending.value = true; const scope = owner.begin()
  try { const response = await api.generate.worldChat(currentWorldPayload(), { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; chatContextUsage.value = response?.context_usage || null; pending.content = response?.reply || "生成完成，但没有返回回复。"; pending.pending = false }
  catch (err) { if (!owner.isActive(scope)) return; pending.content = `聊天失败：${err?.message || "未知错误"}`; pending.pending = false; pending.error = true; toast(pending.content, "error") }
  finally { owner.finish(scope); chatPending.value = false }
}
async function generateWorldSuggestion() {
  if (worldBusy.value) return false
  if (!session.messages.length && !composer.value.trim()) return toast("请先聊天或粘贴已有对话到输入框", "warning")
  if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃并重新生成吗？")) return
  captureComposer(); suggestionPending.value = true; worldError.value = ""; const scope = owner.begin()
  try { const response = await api.generate.generateWorldSuggestion(currentWorldPayload(), { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; worldResult.value = response?.result || null; session.suggestionId = response?.result?.suggestion?.id || null; entityContextUsage.value = response?.context_usage || null; pageProposalDirty.value = false; toast(worldResult.value?.kind === "core_entity" ? "世界对象建议已进入待处理" : "世界书整页提案已进入待处理", "success") }
  catch (err) { if (!owner.isActive(scope)) return; worldError.value = `生成失败：${err?.message || "未知错误"}`; toast(worldError.value, "error") }
  finally { owner.finish(scope); suggestionPending.value = false }
}
async function applyWorldPage(payload) {
  if (worldBusy.value) return false
  const suggestionId = worldResult.value?.suggestion?.id || session.suggestionId; if (!suggestionId || worldResult.value?.kind === "core_entity") return
  applyPending.value = true; const scope = owner.begin()
  try { const response = await api.generate.applyWorldPageDraft(suggestionId, payload, props.projectId, { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; pageProposalDirty.value = false; toast("提案已应用到工作稿，尚未发布", "success"); const query = new URLSearchParams({ draft_id: response.draft.id }); if (response.draft.page_id) query.set("page_id", response.draft.page_id); router.navigate("world", "bible", true, query) }
  catch (err) { if (!owner.isActive(scope)) return; toast(err?.status === 409 ? "来源工作稿已变更，本次提案未覆盖新修改。请重新生成。" : `应用失败：${err?.message || "未知错误"}`, err?.status === 409 ? "warning" : "error") }
  finally { owner.finish(scope); applyPending.value = false }
}
function clearWorldResult() { if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃并清空结果吗？")) return; worldResult.value = null; session.suggestionId = null; entityContextUsage.value = null; worldError.value = "" }
function selectTarget(kind) { if (kind === props.targetKind) return; if (!confirmDiscard("整页提案仍有未应用的编辑，确定放弃修改并切换目标吗？")) return; persist(); const query = new URLSearchParams({ tab: "world", target: kind }); if (props.sourcePageId) query.set("source_page_id", props.sourcePageId); router.navigate("generate", null, true, query) }
function returnToWorldBible() { const query = new URLSearchParams(); if (props.sourcePageId) query.set("page_id", props.sourcePageId); router.navigate("world", "bible", true, query) }
function openReview() { router.navigate("world", "review-objects", true) }

async function changePovChapter(value) { povForm.value = { ...povForm.value, chapterIndex: value ? Number(value) : null, sceneId: "", viewpointCharacterId: "" }; povSubmission.value = null; pov.scenes = []; if (!value) return; const scope = owner.begin(); try { const data = await api.outline.listScenesByChapter(props.projectId, Number(value)); if (owner.isActive(scope)) pov.scenes = Array.isArray(data) ? data : data?.items || [] } catch (err) { if (owner.isActive(scope)) pov.warning = `加载 Scene 失败：${err?.message || "未知错误"}` } finally { owner.finish(scope) } }
function changePovScene(id) { const scene = pov.scenes.find((item) => item.id === id); povForm.value = { ...povForm.value, sceneId: id || "", viewpointCharacterId: scene?.pov_character_id || "" }; povSubmission.value = null }
function abortableDelay(ms, signal) { return new Promise((resolve, reject) => { const timer = setTimeout(resolve, ms); signal.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")) }, { once: true }) }) }
async function waitForPovTask(taskId, scope) { while (owner.isActive(scope)) { let task; try { task = await api.tasks.get(taskId, props.projectId) } catch (err) { if (!owner.isActive(scope)) throw new DOMException("Aborted", "AbortError"); await abortableDelay(1500, scope.controller.signal); continue } if (!owner.isActive(scope)) throw new DOMException("Aborted", "AbortError"); povProgress.value = Number(task?.progress || 0); if (task?.status === "done") { if (!task.result?.draft_id) throw new Error("任务已完成，但未返回正文建议 ID"); return task } if (task?.status === "failed") throw new Error(task.error_message || task.result?.error_message || "角色视角正文生成失败"); if (task?.status === "cancelled") throw new Error("角色视角正文生成已取消"); await abortableDelay(1500, scope.controller.signal) } throw new DOMException("Aborted", "AbortError") }
async function generatePov() {
  if (povPending.value) return false
  const form = povForm.value; if (!form.chapterIndex) return toast("请先选择章节", "warning"); if (!form.sceneId) return toast("请先选择 Scene", "warning"); if (!form.viewpointCharacterId) return toast("请先选择视角角色", "warning")
  povPending.value = true; povProgress.value = null; povError.value = ""; const scope = owner.begin()
  try { const confirmation = await confirmAiReference({ novel_id: props.projectId, action: "writing.generate", task: "基于所选 Scene 和 POV 角色有限认知，生成正文建议预览", scope: "chapter", chapter_index: form.chapterIndex, scene_id: form.sceneId, reveal_mode: "character", viewpoint_character_id: form.viewpointCharacterId, character_ids: [form.viewpointCharacterId], include_pending_objects: false, budget_tokens: 0 }); if (!owner.isActive(scope)) return; let result = await api.writing.generate({ novel_id: props.projectId, chapter_index: form.chapterIndex, title: pov.chapters.find((item) => Number(item.chapter_index) === Number(form.chapterIndex))?.title || `第 ${form.chapterIndex} 章`, instruction: buildPovInstruction(form.instruction, confirmation.user_note), context_confirmation_id: confirmation.id }); if (!owner.isActive(scope)) return; if (result?.task_id && !result?.draft_id) { const task = await waitForPovTask(result.task_id, scope); result = { ...result, ...(task.result || {}), task_status: task.status } } if (!owner.isActive(scope)) return; povSubmission.value = { result, chapterIndex: form.chapterIndex, sceneId: form.sceneId, viewpointCharacterId: form.viewpointCharacterId }; toast(`角色视角正文建议已生成：${result.draft_id || result.id || result.task_id || ""}`, "success") }
  catch (err) { if (!owner.isActive(scope) || err?.name === "AbortError") return; if (err?.message === "已取消 AI 参考资料确认") return; povError.value = err?.message || "未知错误"; toast(`角色视角正文生成失败：${povError.value}`, "error") }
  finally { owner.finish(scope); povPending.value = false }
}
function openPovResult(submission) { const draftId = submission?.result?.draft_id || submission?.result?.draft?.id || ""; appState.viewStates.writing = { projectId: props.projectId, currentChapter: submission.chapterIndex, currentDraftId: draftId || null, isReadonly: Boolean(draftId) }; const query = new URLSearchParams({ chapter_index: String(submission.chapterIndex) }); if (draftId) query.set("draft_id", draftId); router.navigate("writing", null, true, query) }

function selectTaskPreset(key) { if (!TASK_PRESETS[key]) return; taskPreset.value = key; taskForm.value = applyTaskPreset(taskForm.value, key) }
async function compileTask(silent) { if (taskPending.value) return false; const payload = buildTaskPayload(props.projectId, taskForm.value); const error = validateTaskPayload(payload); if (error) return toast(error, "warning"); lastContextRequest.value = payload; lastContextSource.value = "task"; lastContextMarkdown.value = ""; taskPending.value = true; taskError.value = ""; const scope = owner.begin(); try { const data = await api.context.compile(payload, { signal: scope.controller.signal }); if (!owner.isActive(scope)) return; lastContextBundle.value = data; activeTab.value = "preview" } catch (err) { if (!owner.isActive(scope)) return; taskError.value = `编译失败：${err?.message || "未知错误"}`; if (!silent) toast(taskError.value, "error") } finally { owner.finish(scope); taskPending.value = false } }
async function renderTaskMarkdown() { if (taskPending.value) return false; const payload = lastContextRequest.value || buildTaskPayload(props.projectId, taskForm.value); const error = validateTaskPayload(payload); if (error) return toast(error, "warning"); taskPending.value = true; taskError.value = ""; const scope = owner.begin(); try { const data = await api.context.render(payload, { signal: scope.controller.signal }); if (owner.isActive(scope)) lastContextMarkdown.value = data?.markdown || "" } catch (err) { if (owner.isActive(scope)) taskError.value = `渲染失败：${err?.message || "未知错误"}` } finally { owner.finish(scope); taskPending.value = false } }
function copyTaskMarkdown() { if (!lastContextMarkdown.value) return; navigator.clipboard.writeText(lastContextMarkdown.value).then(() => toast("上下文 Markdown 已复制到剪贴板", "success")).catch(() => toast("复制失败，请手动选择复制", "warning")) }
function exportTaskMarkdown() { if (!lastContextMarkdown.value) return; const url = URL.createObjectURL(new Blob([lastContextMarkdown.value], { type: "text/markdown;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `context-${projectTitle.value || "project"}-${Date.now()}.md`; link.click(); URL.revokeObjectURL(url); toast("上下文已导出为 Markdown 文件", "success") }
async function applyTaskToChat() { if (!taskForm.value.task) return toast("当前没有任务内容", "warning"); session.messages.push({ role: "user", content: taskForm.value.task }); if (lastContextBundle.value?.sections?.length) session.messages.push({ role: "assistant", content: `已加载 ${lastContextBundle.value.sections.length} 段上下文，共 ${lastContextBundle.value.total_tokens || 0} tokens。` }); activeTab.value = "world"; await ensureWorld() }

function openOwnedModal(title, body, buttons, options) { ownedModal = true; showModalHtml(title, body, buttons, options) }
function templateEditorBody(item) { return `<div class="generate-template-editor"><div><label for="generate-template-editor-select">现有模板</label><select class="form-select" id="generate-template-editor-select">${templates.value.map((entry) => `<option value="${esc(entry.value)}" ${entry.value === item.value ? "selected" : ""}>${esc(entry.is_builtin ? entry.label : `自定义 · ${entry.label}`)}</option>`).join("")}</select></div><div><label for="generate-template-editor-name">模板名称</label><input class="form-input" id="generate-template-editor-name" value="${esc(item.label)}" maxlength="80" /></div><div><label for="generate-template-editor-prompt">提示词</label><textarea class="form-textarea" id="generate-template-editor-prompt" maxlength="8000">${esc(item.prompt || "")}</textarea></div><p class="generate-template-editor-help">${item.is_builtin ? "内置模板为只读；点击“保存模板”会创建项目级副本。" : "修改自定义模板会生成新版本。"}</p><button class="btn btn-sm" id="generate-template-history-load" type="button" ${item.is_builtin ? "hidden" : ""}>版本历史</button><div id="generate-template-history" class="generate-template-history"></div></div>` }
function selectedEditorTemplate() { const value = document.getElementById("generate-template-editor-select")?.value || session.selectedTemplateId; return templates.value.find((item) => item.value === value) || templates.value[0] }
function editorValues() { return { item: selectedEditorTemplate(), name: document.getElementById("generate-template-editor-name")?.value?.trim() || "", prompt: document.getElementById("generate-template-editor-prompt")?.value?.trim() || "" } }
async function saveTemplate() { const { item, name, prompt } = editorValues(); if (!prompt) return toast("请输入模板提示词", "warning"), false; const scope = owner.begin(); try { let updated; if (item.is_builtin) { const copied = await api.generate.copyPromptTemplate(item.id, { novel_id: props.projectId, name: item.label }); updated = await api.generate.updatePromptTemplate(copied.id, props.projectId, { prompt_text: prompt }) } else { if (!name) return toast("请输入模板名称", "warning"), false; updated = await api.generate.updatePromptTemplate(item.id, props.projectId, { name, prompt_text: prompt }) } if (!owner.isActive(scope)) return false; const normalized = normalizeTemplate(updated); templates.value = item.is_builtin ? [...templates.value, normalized] : templates.value.map((entry) => entry.id === item.id ? normalized : entry); session.selectedTemplateId = normalized.value; toast("模板已保存", "success") } catch (err) { if (owner.isActive(scope)) toast(`保存模板失败：${err?.message || "未知错误"}`, "error"); return false } finally { owner.finish(scope) } }
async function createTemplate() { const { name, prompt } = editorValues(); if (!name) return toast("请输入模板名称", "warning"), false; if (!prompt) return toast("请输入模板提示词", "warning"), false; const scope = owner.begin(); try { const created = await api.generate.createPromptTemplate({ novel_id: props.projectId, name, object_template: "custom", prompt_text: prompt }); if (!owner.isActive(scope)) return false; const normalized = normalizeTemplate(created); templates.value = [...templates.value, normalized]; session.selectedTemplateId = normalized.value; toast("新模板已创建", "success") } catch (err) { if (owner.isActive(scope)) toast(`创建模板失败：${err?.message || "未知错误"}`, "error"); return false } finally { owner.finish(scope) } }
function bindTemplateModal() { const select = document.getElementById("generate-template-editor-select"); select?.addEventListener("change", () => { const item = templates.value.find((entry) => entry.value === select.value); if (!item) return; document.getElementById("generate-template-editor-name").value = item.label; document.getElementById("generate-template-editor-prompt").value = item.prompt || ""; document.getElementById("generate-template-history-load").hidden = item.is_builtin }); document.getElementById("generate-template-history-load")?.addEventListener("click", loadTemplateHistory) }
async function loadTemplateHistory() { const item = selectedEditorTemplate(); const container = document.getElementById("generate-template-history"); if (!container || item.is_builtin) return; container.textContent = "加载版本历史…"; const scope = owner.begin(); try { const data = await api.generate.listPromptTemplateRevisions(item.id, props.projectId); if (!owner.isActive(scope) || !container.isConnected) return; const revisions = Array.isArray(data) ? data : data?.items || []; container.replaceChildren(...revisions.map((revision) => { const article = document.createElement("article"); article.className = "generate-template-revision"; const title = document.createElement("strong"); title.textContent = `v${revision.version_number || "-"}`; const pre = document.createElement("pre"); pre.textContent = String(revision.prompt_text || "").slice(0, 800); const button = document.createElement("button"); button.className = "btn btn-sm"; button.textContent = "载入到编辑器"; button.addEventListener("click", () => { document.getElementById("generate-template-editor-prompt").value = revision.prompt_text || "" }); article.append(title, pre, button); return article })) } catch (err) { if (owner.isActive(scope) && container.isConnected) container.textContent = `版本历史加载失败：${err?.message || "未知错误"}` } finally { owner.finish(scope) } }
function openTemplateEditor() { const item = templates.value.find((entry) => entry.value === session.selectedTemplateId) || templates.value[0]; openOwnedModal("编辑模板", templateEditorBody(item), [{ text: "保存模板", class: "btn-primary", handler: saveTemplate }, { text: "新建模板", class: "btn", handler: createTemplate }, { text: "关闭", class: "btn-ghost", handler: closeModal }]); bindTemplateModal() }

async function runInBatches(items, size, fn) { const output = []; for (let index = 0; index < items.length; index += size) output.push(...await Promise.all(items.slice(index, index + size).map(fn))); return output }
async function openChapterPicker() { const scope = owner.begin(); try { const data = await api.writing.listChapters(props.projectId); const summaries = data?.chapters || []; if (!summaries.length) return toast("当前项目还没有正文，可直接聊天或粘贴外部对话生成建议", "info"); const previews = await runInBatches(summaries, 5, async (item) => { try { const draft = item.id ? await api.writing.get(item.id, props.projectId) : await api.writing.getDraft(item.chapter_index, props.projectId); return { chapter_index: item.chapter_index, title: draft.title || item.title || `第${item.chapter_index}章`, excerpt: String(draft.content || "").replace(/\s+/g, " ").trim().slice(0, 120) } } catch { return { chapter_index: item.chapter_index, title: item.title || `第${item.chapter_index}章`, excerpt: "" } } }); if (!owner.isActive(scope)) return; const selected = new Set(session.selectedChapters.map((item) => item.chapter_index)); const body = `<div class="generate-chapter-list">${previews.map((item) => `<label class="generate-chapter-card"><input id="generate-chapter-${esc(item.chapter_index)}" type="checkbox" ${selected.has(item.chapter_index) ? "checked" : ""}/><span><span class="generate-chapter-title">第 ${esc(item.chapter_index)} 章 · ${esc(item.title)}</span><span class="generate-chapter-excerpt">${esc(item.excerpt || "暂无正文摘录")}</span></span></label>`).join("")}</div>`; openOwnedModal("选择附带正文", body, [{ text: "取消", class: "btn-ghost", handler: closeModal }, { text: "确认选择", class: "btn-primary", handler: () => { const next = previews.filter((item) => document.getElementById(`generate-chapter-${item.chapter_index}`)?.checked); if (next.length > AI_SELECTED_CHAPTER_LIMIT) return toast(`每次最多附带 ${AI_SELECTED_CHAPTER_LIMIT} 章正文`, "warning"), false; session.selectedChapters = next; closeModal() } }]) } catch (err) { if (owner.isActive(scope)) toast(`加载章节失败：${err?.message || "未知错误"}`, "error") } finally { owner.finish(scope) } }
function viewGenerationContext(kind) { const usage = kind === "chat" ? chatContextUsage.value : entityContextUsage.value; if (!usage) return toast("本次生成没有返回可审计的上下文记录", "warning"); const body = `<div class="generate-context-header"><span class="generate-context-stat">${esc(usage.section_key || "world_bible_synopsis")}</span><span class="generate-context-meta">状态：${esc(usage.status || "unknown")}</span><span class="generate-context-meta">Tokens：${esc(usage.token_count || 0)}</span></div><table class="data-table"><tbody><tr><th>Revision</th><td>${esc(usage.revision_id || "确定性降级/未包含")}</td></tr><tr><th>Source hash</th><td>${esc(usage.source_hash || "-")}</td></tr><tr><th>Block hash</th><td>${esc(usage.block_hash || "-")}</td></tr><tr><th>Context snapshot</th><td>${esc(usage.context_snapshot_id || "-")}</td></tr><tr><th>Stale</th><td>${usage.stale ? "是" : "否"}</td></tr><tr><th>Fallback</th><td>${usage.fallback ? "是" : "否"}</td></tr></tbody></table>`; openOwnedModal("本次实际使用的上下文", body, [], { size: "large" }) }

onBeforeUnmount(() => { persist(); owner.dispose(); if (ownedModal) closeModal() })
</script>

<style>
.topbar-generate-note{margin-left:10px;color:var(--text-secondary);font-size:12px;font-style:italic;white-space:nowrap}.generate-chatbox{display:grid;grid-template-columns:minmax(0,78fr) minmax(180px,22fr);gap:12px;align-items:stretch;height:calc(100vh - 180px);min-height:480px;overflow:hidden}.generate-chatbox:has(.generate-side-rail:not([open])){grid-template-columns:minmax(0,1fr) var(--workspace-rail-collapsed)}.generate-chat-main{min-height:0;overflow:hidden}.generate-chat-panel{display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden}.generate-chat-side{min-height:0;max-height:100%;overflow:auto;padding-right:2px}.generate-settings-card{margin-bottom:12px}.generate-card-title-row,.generate-side-options,.generate-template-row,.generate-result-actions,.generate-world-targets{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.generate-card-title-row{justify-content:space-between;margin-bottom:10px}.generate-quality-toggle{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted)}.generate-chat-messages{flex:1 1 auto;min-height:0;overflow:auto;border:1px solid var(--border);border-radius:var(--radius-md);padding:18px;background:var(--bg);margin-bottom:12px}.generate-chat-message{margin-bottom:10px;max-width:92%}.generate-chat-message.assistant{margin-left:auto}.generate-chat-role,.generate-result-meta,.generate-empty-copy{color:var(--text-dim);font-size:12px}.generate-chat-bubble{white-space:pre-wrap;border:1px solid var(--border);border-radius:var(--radius-md);padding:10px 12px;background:var(--panel);font-size:13px;line-height:1.55}.generate-chat-message.error .generate-chat-bubble,.generate-error-text{color:var(--danger)}.generate-composer{flex:0 0 auto;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--panel);padding:8px}.generate-chat-input{width:100%;min-height:72px;resize:vertical;border:0;outline:0;background:transparent;color:var(--text);font:inherit}.generate-template-row--toolbar{margin-bottom:var(--space-2)}.generate-template-btn,.generate-world-target,.generate-subtab{border:1px solid var(--border);background:var(--panel);color:var(--text);border-radius:var(--radius-sm);padding:6px 10px;cursor:pointer}.generate-template-btn.active,.generate-world-target.active,.generate-subtab.active{border-color:var(--accent);background:var(--selected);color:var(--accent)}.generate-result-card{border:1px solid var(--accent);border-radius:var(--radius-sm);padding:12px;background:var(--panel)}.generate-result-title{font-weight:600;margin-bottom:6px}.generate-result-actions{margin-top:10px}.generate-world-source-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;padding:9px 12px}.generate-world-source-label{color:var(--text-dim);font-size:12px;margin-right:8px}.generate-world-config{display:flex;align-items:end;gap:10px;padding:8px 10px;margin-bottom:8px;border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-muted);font-size:12px}.generate-world-context-panel{display:grid;gap:8px;margin-top:10px;border-top:1px solid var(--border);padding-top:8px}.generate-world-context-panel label,.generate-page-result label,.generate-pov-form label{display:grid;gap:4px;color:var(--text-muted);font-size:12px;margin-top:7px}.generate-page-result{display:grid;gap:8px}.generate-json-editor{font:11px/1.45 var(--font-mono)}.generate-task-workspace{display:grid;grid-template-columns:minmax(190px,22fr) minmax(0,78fr);gap:12px;align-items:start}.generate-task-cards{display:grid;gap:8px}.generate-task-card{border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 10px;cursor:pointer;text-align:left;background:var(--panel);color:var(--text)}.generate-task-card.active{border-color:var(--accent);background:var(--selected)}.generate-task-card h4{margin:0 0 2px}.generate-task-card p{margin:0;color:var(--text-dim);font-size:12px}.generate-task-form .form-group{margin-bottom:10px}.generate-pov-workspace{display:grid;grid-template-columns:minmax(0,72fr) minmax(200px,28fr);gap:12px}.generate-pov-form{display:grid;gap:10px}.generate-form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.generate-template-warning,.generate-pov-note{border:1px solid var(--warning);border-radius:var(--radius-sm);color:var(--warning);padding:8px;font-size:12px}.generate-chapter-list{display:grid;gap:8px;max-height:460px;overflow:auto}.generate-chapter-card{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;border:1px solid var(--border);padding:8px}.generate-chapter-title{display:block;font-weight:600}.generate-chapter-excerpt{display:block;color:var(--text-dim);font-size:12px}.generate-template-editor{display:grid;gap:10px}.generate-template-editor label{display:block}.generate-template-editor textarea{min-height:180px}.generate-template-history{display:grid;gap:8px;max-height:320px;overflow:auto}.generate-template-revision{display:grid;gap:6px;border:1px solid var(--border);padding:8px}.generate-template-revision pre{white-space:pre-wrap;max-height:120px;overflow:auto}.generate-context-header,.generate-context-tags{display:flex;gap:8px;flex-wrap:wrap}.generate-context-meta,.generate-context-hint{color:var(--text-muted);font-size:12px}.generate-context-tag{border:1px solid var(--border);padding:2px 5px}.generate-markdown-pre{white-space:pre-wrap}.generate-pov-summary{display:grid;gap:5px;margin-top:12px;color:var(--text-dim);font-size:12px}@media(max-width:900px){.generate-chatbox,.generate-chatbox:has(.generate-side-rail:not([open])),.generate-task-workspace,.generate-pov-workspace,.generate-form-grid{grid-template-columns:1fr;height:auto;min-height:0;overflow:visible}.generate-side-rail{grid-column:1/-1}.topbar-generate-note{display:none}.generate-world-source-bar,.generate-world-config{align-items:stretch;flex-direction:column}}
</style>
