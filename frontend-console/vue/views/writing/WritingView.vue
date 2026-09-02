<!-- Writing Vue island：Vue owns every workspace node; no legacy HTML injection. -->
<template>
  <template v-if="vm.homeMode.value">
    <WritingHomeView v-bind="homeProps" :on-open-ai="openOwnerAi" />
    <OwnerAiDrawer
      :open="aiDrawerOpen"
      :owner="aiDrawerOwner"
      :initial-mode="props.ownerAiMode || null"
      :project-id="props.projectId"
      :source-page-id="aiDrawerSourcePageId"
      :target-kind="aiDrawerTargetKind"
      :preset="aiDrawerPreset"
      :checkpoint-id="aiDrawerCheckpointId"
      :chapter="vm.selectedChapter.value"
      :scene-id="vm.currentScene.value?.id || null"
      :writing-actions="{ generateDraft: vm.generateDraft, generateContinuation: vm.generateContinuation, generatePovDraft: vm.generatePovDraft, saveDraft: vm.saveMobileNote }"
      :writing-busy="vm.generationLoading.value"
      :writing-context="writingAiContext"
      @close="aiDrawerOpen = false"
    />
  </template>
  <template v-else>
  <header v-if="vm.focusMode.value" class="writing-focus-header" aria-label="专注写作">
    <div class="writing-focus-header__context">
      <span>专注写作</span>
      <strong>{{ focusChapterLabel }}</strong>
      <span v-if="hasEditableChapter" class="writing-focus-header__save" aria-live="polite">{{ vm.saveStatus.value }}</span>
    </div>
    <button
      id="writing-focus-exit"
      type="button"
      class="btn btn-sm"
      aria-keyshortcuts="Escape"
      @click="exitFocusMode"
    >退出专注 <kbd aria-hidden="true">Esc</kbd></button>
  </header>
  <div v-else class="view-header writing-toolbar">
    <div class="view-header__title">
      <button type="button" class="btn btn-sm btn-ghost writing-home-back" data-action="open-writing-home" @click="openWritingHome">← 写作首页</button>
      <span>写作</span>
      <span class="view-header__count">共 {{ vm.chapterList.value.length }} 章</span>
    </div>
    <div class="view-header__actions">
      <button
        v-if="vm.isNarrow.value && vm.forceDesktop.value && vm.editorState.status !== 'candidate'"
        id="mobile-editor-mode-toggle"
        ref="quickModeButton"
        type="button"
        class="btn btn-sm btn-ghost"
        @click="returnToQuickNote"
      >返回速记</button>
      <details ref="viewMenuEl" class="writing-page-menu" @toggle="onViewMenuToggle" @keydown="onViewMenuKeydown">
        <summary
          class="btn btn-sm"
          aria-controls="writing-page-menu-body"
          :aria-expanded="String(viewMenuOpen)"
        >写作视图 <span class="writing-page-menu__chevron" aria-hidden="true">⌄</span></summary>
        <div id="writing-page-menu-body" class="writing-page-menu__body" @click="closeViewMenuAfterAction">
          <button v-if="vm.mobileMode.value" type="button" class="btn btn-sm" :disabled="!hasEditableChapter" @click="toggleFocusMode">进入专注</button>
          <button type="button" class="btn btn-sm" data-action="toggle-outline-float" @click="vm.toggleOutlineFloat">故事结构浮窗</button>
          <button type="button" class="btn btn-sm" @click="vm.navigateOutline">打开故事结构</button>
        </div>
      </details>
      <button v-if="vm.mobileMode.value" type="button" class="btn btn-sm" data-action="open-owner-ai-drawer" @click="openOwnerAi({ owner: 'writing' })">AI 工具</button>
      <button type="button" class="btn btn-sm" :disabled="!vm.selectedChapter.value" @click="addChapterTask">添加到计划中的任务</button>
    </div>
  </div>

  <MobileQuickNote
    v-if="vm.mobileMode.value"
    :state="vm.editorState"
    :chapter="vm.selectedChapter.value"
    :scenes="vm.chapterScenes.value"
    :selected-scene-id="vm.selectedSceneId.value"
    :scene="vm.currentScene.value"
    :lens="vm.sceneLens"
    :today-words="vm.todayWords.value"
    :attach="vm.attachEditor"
    :detach="vm.detachEditor"
    @select-scene="vm.selectScene"
    @load-lens="vm.loadSceneLens"
    @save="vm.saveMobileNote"
    @publish="vm.publish"
    @desktop="openCompleteEditor"
    @retry-load="vm.retryChapterLoad"
  />

  <WritingWorkflowBars
    :publish="vm.publishProgress"
    :conflict="vm.conflictState"
    :deep-import="vm.deepImportState"
    :deep-import-has-scenes="vm.deepImportHasScenes.value"
    :generation="vm.generationTask"
    :conflict-task="vm.conflictTask"
    :show-conflict="false"
    @cancel="vm.cancelDeepImport"
    @resume="vm.resumeDeepImport"
    @abandon="vm.abandonDeepImport"
    @dismiss="vm.dismissDeepImport"
    @open-audit="vm.deepAuditOpen.value = true"
    @open-scenes="vm.openSceneWorkbench"
    @open-conflict="vm.openConflictDialog"
    @retry-publish="vm.retryPublish"
    @dismiss-publish="vm.dismissPublishError"
    @open-generation="vm.openGenerationResult"
    @cancel-generation="vm.cancelGeneration"
    @dismiss-generation="vm.dismissGeneration"
    @retry-stale-story-script="vm.retryUsingStaleStoryScript"
    @cancel-conflict-task="vm.cancelConflictTask"
    @dismiss-conflict-task="vm.dismissConflictTask"
  />

  <div
    v-if="!vm.mobileMode.value"
    class="writing-workspace-layout"
    :class="{ 'writing-workspace-layout--candidate': vm.editorState.status === 'candidate' }"
  >
    <aside
      class="workspace-rail writing-tree-rail workspace-rail--left"
      :class="{ 'is-collapsed': !leftRailOpen }"
      aria-label="章节"
    >
      <div id="writing-tree-container">
        <ChapterTree
          :chapter-list="vm.chapterList.value"
          :chapters="vm.chapters"
          :selected-chapter="vm.selectedChapter.value"
          :load-error="vm.chapterLoadError.value"
          :collapsed="!leftRailOpen"
          @select="vm.selectChapter"
          @create="vm.createChapter"
          @delete-selected="vm.deleteChapters"
          @toggle-collapse="toggleRail('chapters')"
        />
      </div>
    </aside>

    <main id="writing-editor-container" :data-watermark="watermarkChar">
      <WritingEditor
        :state="vm.editorState"
        :target-chapter="vm.selectedChapter.value"
        :has-chapters="vm.chapterList.value.length > 0"
        :save-status="vm.saveStatus.value"
        :editor-font="effectiveEditorFont"
        :daily-goal="authorPreferences.dailyGoal"
        :focus-mode="vm.focusMode.value"
        :generation-loading="vm.generationLoading.value"
        :conflict-loading="vm.conflictState.loading"
        :review-result="vm.generationTask.result"
        :candidate-comparison-available="vm.candidateComparisonAvailable.value"
        :attach="vm.attachEditor"
        :detach="vm.detachEditor"
        @autosave="vm.autosave"
        @checkpoint="vm.checkpoint"
        @conflict-check="vm.requestConflictCheck"
        @publish="vm.publish"
        @discard="vm.discardChanges"
        @generate-draft="vm.generateDraft"
        @generate-continuation="vm.generateContinuation"
        @generate-pov="vm.generatePovDraft"
        @auto-extract="vm.openAutoExtraction"
        @open-deep-import-settings="vm.openDeepImportSettings"
        @open-ai-tools="openOwnerAi({ owner: 'writing' })"
        @adopt="adoptCandidate"
        @reject="rejectCandidate"
        @semantic-review="vm.reviewCandidate"
        @targeted-revision="vm.reviseCandidate"
        @compare-candidate="vm.compareCandidateWithWorkingDraft"
        @export="vm.exportChapter"
        @retry-load="vm.retryChapterLoad"
      >
        <template #context-actions>
          <div v-if="vm.activeVersions.value.length" id="writing-versions-container" class="writing-version-bar writing-version-bar--compact">
            <label class="writing-version-label" for="version-selector">版本</label>
            <span class="writing-version-select-wrap">
              <select
                id="version-selector"
                class="writing-version-select"
                aria-label="选择章节版本"
                :value="vm.editorState.draftId || ''"
                @change="vm.switchVersion($event.target.value)"
              >
                <option
                  v-for="(version, index) in vm.activeVersions.value"
                  :key="version.id"
                  :value="version.id"
                  :data-version="version.version_number"
                  :data-latest="index === 0 ? 1 : 0"
                >v{{ version.version_number }} · {{ version.status === 'published' ? '正式正文' : version.status === 'candidate' ? '待处理' : version.status === 'deprecated' ? '历史' : '工作稿' }}</option>
              </select>
            </span>
            <span id="publish-status-dot" class="publish-status-dot" :class="{ active: vm.publishProgress.active }" />
            <button class="btn btn-sm writing-btn-compact" @click="vm.openVersionHistory">版本历史</button>
          </div>
          <div
            v-if="vm.conflictState.latest || vm.conflictState.error"
            id="writing-conflict-strip"
            class="writing-conflict-strip writing-conflict-strip--compact"
            :role="vm.conflictState.latest ? 'button' : 'status'"
            :tabindex="vm.conflictState.latest ? 0 : null"
            :title="conflictSummary"
            @click="vm.conflictState.latest && vm.openConflictDialog()"
            @keydown.enter.prevent="vm.conflictState.latest && vm.openConflictDialog()"
            @keydown.space.prevent="vm.conflictState.latest && vm.openConflictDialog()"
          >
            <strong>{{ vm.conflictState.error ? '检查失败' : '最近检查' }}</strong>
            <span>{{ conflictSummary }}</span>
          </div>
        </template>
      </WritingEditor>

      <p v-if="vm.versionLoadError.value" class="writing-empty-hint" role="alert">{{ vm.versionLoadError.value }}</p>
    </main>

    <aside
      class="workspace-rail writing-panel-rail workspace-rail--right"
      :class="{ 'is-collapsed': !rightRailOpen }"
      aria-label="写作副驾驶"
    >
      <div id="writing-panel-container">
        <SceneCockpit
          :project-id="projectId"
          :chapter="vm.selectedChapter.value"
          :scene="vm.currentScene.value"
          :scenes="vm.chapterScenes.value"
          :all-scenes="vm.activeScenes.value"
          :associate-scene="vm.associateScene"
          :create-scene="vm.createSceneForChapter"
          :loading="vm.sceneState.loading"
          :alert-error="vm.conflictState.error"
          :alerts="vm.sceneState.alerts"
          :people="vm.sceneState.people"
          :location="vm.sceneState.location"
          :lens="vm.sceneLens"
          :conflict="vm.conflictState"
          :rail-collapsed="!rightRailOpen"
          @run-conflict="vm.requestConflictCheck"
          @open-conflict="vm.openConflictDialog"
          @insert-text="vm.insertText"
          @select-scene="vm.selectScene"
          @load-lens="vm.loadSceneLens"
          @organize="vm.navigateSceneWorkbench"
          @toggle-collapse="toggleRail('reference')"
        />
      </div>
    </aside>

    <footer class="writing-statusbar">
      <div id="writing-wordcount-bar" class="writing-wordcount-bar">
        <span><strong>{{ statusWordCount.toLocaleString() }}</strong> 字</span>
        <span v-if="dailyGoalNumber" class="wc-daily-goal">
          日目标 {{ vm.todayWords.value.toLocaleString() }} / {{ dailyGoalNumber.toLocaleString() }}
          <span class="wc-goal-progress" aria-hidden="true"><span class="wc-goal-fill" :style="{ width: `${goalPercent}%` }" /></span>
        </span>
        <span>{{ statusParagraphCount }} 段</span>
        <span>约 {{ statusReadMinutes }} 分钟阅读</span>
      </div>
      <div class="writing-statusbar__right">
        <span v-if="hasEditableChapter" id="writing-version-info" class="writing-version-badge">{{ versionLabel }}</span>
        <span v-if="hasEditableChapter" id="writing-save-status" class="writing-save-badge" :class="saveBadgeClass">{{ vm.saveStatus.value }}</span>
        <button
          type="button"
          class="writing-statusbar__font"
          aria-label="切换正文字体"
          :title="`正文字体：${editorFontLabel}（跟随创作偏好，点此临时切换）`"
          @click="cycleEditorFont"
        >字体 · {{ editorFontLabel }}</button>
        <button type="button" class="writing-statusbar__focus" :disabled="!hasEditableChapter" @click="toggleFocusMode">专注模式</button>
      </div>
    </footer>
  </div>

  <OutlineFloat
    :model="vm.outlineFloat"
    :current-chapter="vm.selectedChapter.value"
    @close="vm.toggleOutlineFloat"
    @select="vm.selectChapter"
  />
  <AutoExtractionDialog :model="vm.autoExtraction" @submit="vm.submitAutoExtraction" />
  <ConflictOptionsDialog :model="vm.conflictOptions" @submit="vm.runConflictCheck" />
  <ConflictDetailDialog
    :model="vm.conflictDialog"
    @close="vm.closeConflictDialog"
    @status="vm.updateConflictStatus"
    @ai-review="vm.runConflictAiReview"
    @suggestion="vm.requestConflictSuggestion"
    @apply="vm.applyConflictSuggestion"
    @locate="vm.locateConflictItem"
    @source="vm.openConflictSource"
    @dismiss-source="vm.conflictDialog.sourcePreview = null"
  />
  <DeepImportAuditDialog :open="vm.deepAuditOpen.value" :progress="vm.deepImportState.progress" @close="vm.deepAuditOpen.value = false" />
  <VersionHistoryDialog
    :model="vm.versionDialog"
    :versions="vm.versions.value"
    :current-id="vm.editorState.draftId"
    @preview="previewVersion"
    @restore="vm.restoreVersion"
    @delete="vm.deleteVersion"
    @compare="vm.compareVersions"
  />
  <OwnerAiDrawer
    :open="aiDrawerOpen"
    :owner="aiDrawerOwner"
    :initial-mode="props.ownerAiMode || null"
    :project-id="props.projectId"
    :source-page-id="aiDrawerSourcePageId"
    :target-kind="aiDrawerTargetKind"
    :preset="aiDrawerPreset"
    :checkpoint-id="aiDrawerCheckpointId"
    :chapter="vm.selectedChapter.value"
    :scene-id="vm.currentScene.value?.id || null"
    :writing-actions="{ generateDraft: vm.generateDraft, generateContinuation: vm.generateContinuation, generatePovDraft: vm.generatePovDraft, saveDraft: vm.saveMobileNote }"
    :writing-busy="vm.generationLoading.value"
    :writing-context="writingAiContext"
    @close="aiDrawerOpen = false"
  />
  </template>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import ChapterTree from "./components/ChapterTree.vue"
import AutoExtractionDialog from "./components/AutoExtractionDialog.vue"
import ConflictDetailDialog from "./components/ConflictDetailDialog.vue"
import ConflictOptionsDialog from "./components/ConflictOptionsDialog.vue"
import DeepImportAuditDialog from "./components/DeepImportAuditDialog.vue"
import MobileQuickNote from "./components/MobileQuickNote.vue"
import OutlineFloat from "./components/OutlineFloat.vue"
import SceneCockpit from "./components/SceneCockpit.vue"
import VersionHistoryDialog from "./components/VersionHistoryDialog.vue"
import WritingEditor from "./components/WritingEditor.vue"
import WritingWorkflowBars from "./components/WritingWorkflowBars.vue"
import WritingHomeView from "./home/WritingHomeView.vue"
import { authorTaskPanelQuery } from "./home/authorTaskSource.js"
import OwnerAiDrawer from "../../components/OwnerAiDrawer.vue"
import { getRouter } from "../../bridge/index.js"
import { useWritingWorkspace } from "./useWritingWorkspace.js"
import "./writing-desk.css"
import "./writing-decorations.css"

const props = defineProps({
  projectId: { type: String, default: null },
  chapterList: { type: Array, default: () => [] },
  chapters: { type: Object, default: () => ({}) },
  scenes: { type: Array, default: () => [] },
  chapterLoadError: { type: String, default: null },
  authorPreferences: { type: Object, default: () => ({ dailyGoal: null, editorFont: "system", defaultFocusMode: false }) },
  requestedLocation: { type: Object, default: null },
  homeMode: { type: Boolean, default: false },
  homeProps: { type: Object, default: () => ({}) },
  ownerAiOpen: { type: Boolean, default: false },
  ownerAiMode: { type: String, default: "writing" },
})

const vm = useWritingWorkspace(props)
const router = getRouter()
const quickModeButton = ref(null)
const viewMenuEl = ref(null)
const viewMenuOpen = ref(false)
let focusOrigin = null
const aiDrawerOpen = ref(Boolean(props.ownerAiOpen))
const aiDrawerOwner = ref(props.ownerAiMode === "world" ? "world" : "writing")
const aiDrawerSourcePageId = ref(null)
const aiDrawerTargetKind = ref(null)
const aiDrawerPreset = ref(null)
const aiDrawerCheckpointId = ref(null)
function openOwnerAi(context = {}) {
  aiDrawerOwner.value = context.owner || "writing"
  aiDrawerSourcePageId.value = context.sourcePageId || null
  aiDrawerTargetKind.value = context.targetKind || null
  aiDrawerPreset.value = context.preset || null
  aiDrawerCheckpointId.value = context.checkpointId || null
  aiDrawerOpen.value = true
  return true
}

function addChapterTask() {
  if (!vm.selectedChapter.value) return
  router.navigate("writing", null, true, authorTaskPanelQuery({
    kind: "writing_chapter",
    id: String(vm.selectedChapter.value),
    title: vm.editorState.title || `第 ${vm.selectedChapter.value} 章`,
  }))
}
function openWritingHome() {
  router.navigate("writing", null, true, new URLSearchParams({ home: "1" }))
}
const conflictSummary = computed(() => (
  vm.conflictState.error
  || vm.conflictState.latest?.summary_json?.message
  || vm.conflictState.latest?.status
  || "已完成"
))

/* 状态栏：纯展示派生，不触发任何请求 */
const hasEditableChapter = computed(() => Number.isInteger(Number(vm.selectedChapter.value))
  && Number(vm.selectedChapter.value) > 0
  && !vm.editorState.loading
  && !vm.editorState.loadError)
const statusWordCount = computed(() => String(vm.editorState.content || "").length)
const statusParagraphCount = computed(() => String(vm.editorState.content || "").replace(/\r\n?/g, "\n").split(/\n+/).filter((item) => item.trim()).length)
const statusReadMinutes = computed(() => Math.max(1, Math.ceil(statusWordCount.value / 400)))
const dailyGoalNumber = computed(() => {
  const goal = Number(props.authorPreferences?.dailyGoal)
  return Number.isFinite(goal) && goal > 0 ? goal : null
})
const goalPercent = computed(() => (
  dailyGoalNumber.value ? Math.min(100, Math.round((vm.todayWords.value / dailyGoalNumber.value) * 100)) : 0
))
const versionLabel = computed(() => (
  vm.editorState.versionNumber ? `v${vm.editorState.versionNumber}${vm.editorState.readonly ? "（只读）" : ""}` : "未选择版本"
))
const backupUnavailable = computed(() => (
  vm.editorState.dirty && vm.editorState.backupComplete === false
))
const saveBadgeClass = computed(() => ({
  "writing-save-badge--saving": Boolean(vm.editorState.saving),
  "writing-save-badge--error": !vm.editorState.saving && (Boolean(vm.editorState.saveError) || backupUnavailable.value),
  "writing-save-badge--readonly": !vm.editorState.saving && !vm.editorState.saveError && !backupUnavailable.value && vm.editorState.readonly,
  "writing-save-badge--unsaved": !vm.editorState.saving && !vm.editorState.saveError && !backupUnavailable.value && !vm.editorState.readonly && vm.editorState.dirty,
  "writing-save-badge--saved": !vm.editorState.saving && !vm.editorState.saveError && !backupUnavailable.value && !vm.editorState.readonly && !vm.editorState.dirty,
}))
const focusChapterLabel = computed(() => {
  const chapter = Number(vm.selectedChapter.value)
  const title = String(vm.editorState.title || vm.chapters?.[chapter]?.title || "").trim()
  if (!Number.isInteger(chapter) || chapter < 1) return "选择章节后开始"
  return `第 ${chapter} 章${title ? ` · ${title}` : ""}`
})
const writingAiContext = computed(() => {
  const content = String(vm.editorState.content || "")
  const scene = vm.currentScene.value
  return {
    chapterTitle: String(vm.editorState.title || vm.chapters?.[vm.selectedChapter.value]?.title || "").trim(),
    hasContent: Boolean(content.trim()),
    hasUnsavedContent: content !== String(vm.editorState.lastSavedContent || "") || (!vm.editorState.draftId && Boolean(content.trim())),
    readonly: Boolean(vm.editorState.readonly),
    saving: Boolean(vm.editorState.saving),
    saveError: vm.editorState.saveError || "",
    sceneTitle: String(scene?.title || "").trim(),
    hasPovCharacter: Boolean(scene?.pov_character_id),
  }
})

/* 正文字体：默认跟随创作偏好，状态栏按钮只做本次会话的临时切换，不写入偏好存储 */
const editorFontChoices = ["system", "serif", "sans", "mono"]
const editorFontLabels = { system: "默认", serif: "衬线", sans: "无衬线", mono: "等宽" }
const editorFontOverride = ref(null)
const effectiveEditorFont = computed(() => editorFontOverride.value || props.authorPreferences?.editorFont || "system")
const editorFontLabel = computed(() => editorFontLabels[effectiveEditorFont.value] || "默认")
function cycleEditorFont() {
  const index = editorFontChoices.indexOf(effectiveEditorFont.value)
  editorFontOverride.value = editorFontChoices[(index + 1) % editorFontChoices.length]
}

/* ink 主题水印字：取当前章标题首字，无标题则为空（CSS 不渲染） */
const watermarkChar = computed(() => {
  const chapter = vm.selectedChapter.value
  const meta = chapter != null ? vm.chapters?.[chapter] : null
  const title = String(vm.editorState.title || meta?.title || "").trim()
  return title ? title.slice(0, 1) : ""
})
const stored = (rail, fallback) => {
  try {
    const value = sessionStorage.getItem(`workspace-rail:${props.projectId}:writing:${rail}`)
    return value ? value === "open" : fallback
  } catch { return fallback }
}
const leftRailOpen = ref(
  vm.selectedChapter.value == null
  || stored(
    "chapters",
    vm.chapterList.value.length === 0 || typeof window === "undefined" || window.innerWidth > 760,
  ),
)
const rightRailOpen = ref(stored("reference", typeof window === "undefined" || window.innerWidth > 1099))

function openCompleteEditor() {
  leftRailOpen.value = false
  rightRailOpen.value = false
  vm.switchDesktopMode()
  nextTick(() => quickModeButton.value?.focus())
}

function returnToQuickNote() {
  vm.switchMobileMode()
  nextTick(() => document.querySelector("#mobile-note-editor")?.focus())
}

function focusWritingEditor() {
  document.querySelector(vm.mobileMode.value ? "#mobile-note-editor" : "#writing-editor")?.focus()
}

function setFocusMode(active) {
  if (active) focusOrigin = document.activeElement
  if (!vm.setFocusMode(active)) return false
  nextTick(() => {
    if (active) {
      focusWritingEditor()
      return
    }
    const originHidden = focusOrigin?.closest?.("details:not([open])")
    const originWasViewMenu = focusOrigin?.closest?.(".writing-page-menu")
    const fallback = document.querySelector(originWasViewMenu
      ? ".writing-page-menu > summary"
      : ".writing-statusbar__focus") || document.querySelector(".writing-page-menu > summary")
    if (focusOrigin?.isConnected && !originHidden && !focusOrigin.disabled) focusOrigin.focus()
    else fallback?.focus()
  })
  return true
}

function toggleFocusMode() {
  if (viewMenuEl.value?.open) closeViewMenu(true)
  return setFocusMode(!vm.focusMode.value)
}
function exitFocusMode() { return setFocusMode(false) }
function onFocusKeydown(event) {
  if (event.key !== "Escape" || !vm.focusMode.value) return
  event.preventDefault()
  exitFocusMode()
}

onMounted(() => {
  window.addEventListener("keydown", onFocusKeydown)
  document.addEventListener("pointerdown", onDocumentPointerdown)
})
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onFocusKeydown)
  document.removeEventListener("pointerdown", onDocumentPointerdown)
})

watch([vm.focusMode, vm.mobileMode], ([active]) => {
  if (active) nextTick(focusWritingEditor)
})
watch([() => vm.editorState.status, vm.isNarrow], ([status, narrow]) => {
  if (status === "candidate" && narrow) leftRailOpen.value = false
})

function closeViewMenu(restoreFocus = false) {
  if (!viewMenuEl.value) return
  viewMenuEl.value.open = false
  viewMenuOpen.value = false
  if (restoreFocus) viewMenuEl.value.querySelector(":scope > summary")?.focus()
}

function onViewMenuToggle(event) {
  viewMenuOpen.value = event.currentTarget.open
}

function closeViewMenuAfterAction(event) {
  const button = event.target.closest?.("button")
  if (button && !button.disabled) closeViewMenu(true)
}

function onViewMenuKeydown(event) {
  if (event.key !== "Escape" || !viewMenuEl.value?.open) return
  event.preventDefault()
  event.stopPropagation()
  closeViewMenu(true)
}

function onDocumentPointerdown(event) {
  if (viewMenuEl.value && !viewMenuEl.value.contains(event.target)) closeViewMenu()
}

function toggleRail(rail) {
  const current = rail === "chapters" ? leftRailOpen : rightRailOpen
  current.value = !current.value
  try { sessionStorage.setItem(`workspace-rail:${props.projectId}:writing:${rail}`, current.value ? "open" : "closed") } catch { /* noop */ }
}

async function adoptCandidate() {
  const result = await vm.adoptCandidate()
  if (result && vm.selectedChapter.value) await vm.selectChapter(vm.selectedChapter.value, { draftId: result.id })
}

async function rejectCandidate() {
  if (await vm.rejectCandidate()) await vm.selectChapter(vm.selectedChapter.value)
}

async function previewVersion(draftId) {
  if (!await vm.switchVersion(draftId)) return
  vm.versionDialog.open = false
  await nextTick()
  requestAnimationFrame(focusWritingEditor)
}
</script>
