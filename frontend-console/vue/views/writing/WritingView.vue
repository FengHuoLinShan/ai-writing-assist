<!-- Writing Vue island：Vue owns every workspace node; no legacy HTML injection. -->
<template>
  <div class="view-header writing-toolbar">
    <div class="view-header__title">
      写作
      <span class="view-header__count">共 {{ vm.chapterList.value.length }} 章</span>
    </div>
    <div class="view-header__actions">
      <button class="btn btn-sm btn-primary" @click="vm.createChapter">新建章节</button>
      <details class="writing-page-menu">
        <summary class="btn btn-sm">写作视图</summary>
        <div class="writing-page-menu__body" @click="closeViewMenu">
          <button class="btn btn-sm" @click="vm.toggleFocusMode">{{ vm.focusMode.value ? '退出专注' : '进入专注' }}</button>
          <button class="btn btn-sm" data-action="toggle-outline-float" @click="vm.toggleOutlineFloat">故事结构浮窗</button>
          <button class="btn btn-sm" @click="vm.navigateOutline">打开故事结构</button>
        </div>
      </details>
    </div>
  </div>

  <MobileQuickNote
    v-if="vm.mobileMode.value"
    :state="vm.editorState"
    :attach="vm.attachEditor"
    :detach="vm.detachEditor"
    @save="vm.saveMobileNote"
    @publish="vm.publish"
    @desktop="vm.switchDesktopMode"
  />

  <div v-else class="writing-workspace-layout">
    <aside
      class="workspace-rail writing-tree-rail workspace-rail--left"
      :class="{ 'is-collapsed': !leftRailOpen }"
      aria-label="章节"
    >
      <div id="writing-tree-container">
        <ChapterTree
          :chapter-list="vm.chapterList.value"
          :chapters="vm.chapters"
          :scenes="vm.scenes.value"
          :selected-chapter="vm.selectedChapter.value"
          :selected-scene-id="vm.selectedSceneId.value"
          :load-error="vm.chapterLoadError.value"
          :collapsed="!leftRailOpen"
          @select="vm.selectChapter"
          @select-scene="selectScene"
          @create="vm.createChapter"
          @delete-selected="vm.deleteChapters"
          @toggle-collapse="toggleRail('chapters')"
        />
      </div>
    </aside>

    <main id="writing-editor-container" :data-watermark="watermarkChar">
      <WritingEditor
        :state="vm.editorState"
        :has-chapters="vm.chapterList.value.length > 0"
        :save-status="vm.saveStatus.value"
        :editor-font="effectiveEditorFont"
        :daily-goal="authorPreferences.dailyGoal"
        :focus-mode="vm.focusMode.value"
        :generation-loading="vm.generationLoading.value"
        :conflict-loading="vm.conflictState.loading"
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
        @adopt="adoptCandidate"
        @reject="rejectCandidate"
        @export="vm.exportChapter"
        @toggle-focus="vm.toggleFocusMode"
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
            <button class="btn btn-sm writing-btn-compact" title="版本历史" @click="vm.openVersionHistory">历史</button>
            <button v-if="vm.versions.value.length >= 2" class="btn btn-sm writing-btn-compact" title="比较两个版本" @click="openVersionDiff">比较</button>
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
      <WritingWorkflowBars
        :publish="vm.publishProgress"
        :conflict="vm.conflictState"
        :deep-import="vm.deepImportState"
        :generation="vm.generationTask"
        :conflict-task="vm.conflictTask"
        :show-conflict="false"
        @cancel="vm.cancelDeepImport"
        @resume="vm.resumeDeepImport"
        @abandon="vm.abandonDeepImport"
        @dismiss="vm.dismissDeepImport"
        @open-audit="vm.deepAuditOpen.value = true"
        @open-conflict="vm.openConflictDialog"
        @retry-publish="vm.retryPublish"
        @dismiss-publish="vm.dismissPublishError"
        @open-generation="vm.openGenerationResult"
        @cancel-generation="vm.cancelGeneration"
        @dismiss-generation="vm.dismissGeneration"
        @cancel-conflict-task="vm.cancelConflictTask"
        @dismiss-conflict-task="vm.dismissConflictTask"
      />
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
          :loading="vm.sceneState.loading"
          :alert-error="vm.conflictState.error"
          :alerts="vm.sceneState.alerts"
          :people="vm.sceneState.people"
          :location="vm.sceneState.location"
          :conflict="vm.conflictState"
          :rail-collapsed="!rightRailOpen"
          @run-conflict="vm.requestConflictCheck"
          @open-conflict="vm.openConflictDialog"
          @insert-text="vm.insertText"
          @organize="vm.navigateSceneWorkbench"
          @toggle-collapse="toggleRail('reference')"
        />
      </div>
    </aside>

    <footer class="writing-statusbar">
      <div id="writing-wordcount-bar" class="writing-wordcount-bar">
        <span><strong>{{ statusWordCount.toLocaleString() }}</strong> 字</span>
        <span v-if="dailyGoalNumber" class="wc-daily-goal">
          日目标 {{ statusWordCount.toLocaleString() }} / {{ dailyGoalNumber.toLocaleString() }}
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
        <button type="button" class="writing-statusbar__focus" @click="vm.toggleFocusMode">{{ vm.focusMode.value ? '退出专注' : '专注模式' }}</button>
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
    @preview="vm.switchVersion"
    @restore="vm.restoreVersion"
    @delete="vm.deleteVersion"
    @compare="vm.compareVersions"
  />
</template>

<script setup>
import { computed, ref } from "vue"
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
})

const vm = useWritingWorkspace(props)
const conflictSummary = computed(() => (
  vm.conflictState.error
  || vm.conflictState.latest?.summary_json?.message
  || vm.conflictState.latest?.status
  || "已完成"
))

/* 状态栏：纯展示派生，不触发任何请求 */
const hasEditableChapter = computed(() => Number.isInteger(Number(vm.editorState.chapter)) && Number(vm.editorState.chapter) > 0)
const statusWordCount = computed(() => String(vm.editorState.content || "").length)
const statusParagraphCount = computed(() => String(vm.editorState.content || "").replace(/\r\n?/g, "\n").split(/\n+/).filter((item) => item.trim()).length)
const statusReadMinutes = computed(() => Math.max(1, Math.ceil(statusWordCount.value / 400)))
const dailyGoalNumber = computed(() => {
  const goal = Number(props.authorPreferences?.dailyGoal)
  return Number.isFinite(goal) && goal > 0 ? goal : null
})
const goalPercent = computed(() => (
  dailyGoalNumber.value ? Math.min(100, Math.round((statusWordCount.value / dailyGoalNumber.value) * 100)) : 0
))
const versionLabel = computed(() => (
  vm.editorState.versionNumber ? `v${vm.editorState.versionNumber}${vm.editorState.readonly ? "（只读）" : ""}` : "未选择版本"
))
const saveBadgeClass = computed(() => ({
  "writing-save-badge--saving": Boolean(vm.editorState.saving),
  "writing-save-badge--unsaved": !vm.editorState.saving && vm.editorState.dirty,
  "writing-save-badge--saved": !vm.editorState.saving && !vm.editorState.dirty,
}))

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
const leftRailOpen = ref(stored("chapters", typeof window === "undefined" || window.innerWidth > 760))
const rightRailOpen = ref(stored("reference", typeof window === "undefined" || window.innerWidth > 1099))

function closeViewMenu(event) {
  event.currentTarget.closest("details").open = false
}

function toggleRail(rail) {
  const current = rail === "chapters" ? leftRailOpen : rightRailOpen
  current.value = !current.value
  try { sessionStorage.setItem(`workspace-rail:${props.projectId}:writing:${rail}`, current.value ? "open" : "closed") } catch { /* noop */ }
}

async function selectScene(sceneId) {
  const scene = vm.scenes.value.find((item) => item.id === sceneId)
  const chapter = (scene?.chapter_ids || []).map(Number).find((item) => vm.chapterList.value.includes(item))
  if (chapter) await vm.selectChapter(chapter, { sceneId })
}

async function adoptCandidate() {
  const result = await vm.adoptCandidate()
  if (result && vm.selectedChapter.value) await vm.selectChapter(vm.selectedChapter.value, { draftId: result.id })
}

async function rejectCandidate() {
  if (await vm.rejectCandidate()) await vm.selectChapter(vm.selectedChapter.value)
}

function openVersionDiff() {
  vm.openVersionHistory()
  vm.compareVersions()
}
</script>
