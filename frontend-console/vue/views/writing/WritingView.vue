<!-- Writing Vue island：Vue owns every workspace node; no legacy HTML injection. -->
<template>
  <div class="view-header writing-toolbar">
    <div class="view-header__title">
      手动工作台
      <span class="view-header__count">共 {{ vm.chapterList.value.length }} 章</span>
    </div>
    <div class="view-header__actions">
      <button class="btn btn-sm btn-primary" @click="vm.createChapter">新建章节</button>
      <button class="btn btn-sm" @click="vm.toggleFocusMode">{{ vm.focusMode.value ? '退出专注' : '聚焦模式' }}</button>
      <button class="btn btn-sm" data-action="toggle-outline-float" @click="vm.toggleOutlineFloat">大纲浮窗</button>
      <button class="btn btn-sm" @click="vm.navigateOutline">打开大纲</button>
    </div>
  </div>

  <MobileQuickNote
    v-if="vm.mobileMode.value"
    :state="vm.editorState"
    :attach="vm.attachEditor"
    :detach="vm.detachEditor"
    @save="vm.saveMobileNote"
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

    <main id="writing-editor-container">
      <WritingEditor
        :state="vm.editorState"
        :has-chapters="vm.chapterList.value.length > 0"
        :save-status="vm.saveStatus.value"
        :editor-font="authorPreferences.editorFont"
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
        @open-map="vm.openMap"
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
                >v{{ version.version_number }} · {{ version.status === 'published' ? '已发布' : version.status === 'candidate' ? '待处理' : version.status === 'deprecated' ? '历史' : '工作稿' }}</option>
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
        :show-conflict="false"
        @cancel="vm.cancelDeepImport"
        @resume="vm.resumeDeepImport"
        @abandon="vm.abandonDeepImport"
        @dismiss="vm.dismissDeepImport"
        @map-next="vm.runDeepImportNextStep"
        @retry-map="vm.retryDeepImportMapNext"
        @open-audit="vm.deepAuditOpen.value = true"
        @open-conflict="vm.openConflictDialog"
        @retry-publish="vm.retryPublish"
        @dismiss-publish="vm.dismissPublishError"
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
          :map-summary="vm.sceneState.mapSummary"
          :error="vm.sceneState.error"
          :alert-error="vm.conflictState.error"
          :alerts="vm.sceneState.alerts"
          :people="vm.sceneState.people"
          :location="vm.sceneState.location"
          :conflict="vm.conflictState"
          :rail-collapsed="!rightRailOpen"
          @open-map="vm.openMap"
          @run-conflict="vm.requestConflictCheck"
          @open-conflict="vm.openConflictDialog"
          @insert-text="vm.insertText"
          @organize="vm.navigateSceneWorkbench"
          @toggle-collapse="toggleRail('reference')"
        />
      </div>
    </aside>
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
const stored = (rail, fallback) => {
  try {
    const value = sessionStorage.getItem(`workspace-rail:${props.projectId}:writing:${rail}`)
    return value ? value === "open" : fallback
  } catch { return fallback }
}
const leftRailOpen = ref(stored("chapters", typeof window === "undefined" || window.innerWidth > 760))
const rightRailOpen = ref(stored("reference", typeof window === "undefined" || window.innerWidth > 1099))

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
