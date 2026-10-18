<!-- Writing Vue island：Vue owns every workspace node; no legacy HTML injection. -->
<template>
  <template v-if="props.publicDemo && !vm.homeMode.value">
    <header class="writing-toolbar writing-document-toolbar public-demo-reader__toolbar">
      <div class="view-header__title">
        <button type="button" class="btn btn-sm btn-ghost writing-home-back" @click="openWritingHome">← 返回演示首页</button>
        <span class="view-header__count">正式正文 · 只读</span>
      </div>
      <span>{{ vm.chapterList.value.length }} 章</span>
    </header>
    <div class="public-demo-reader">
      <nav class="public-demo-reader__chapters" aria-label="正文目录">
        <strong>正文目录</strong>
        <p v-if="vm.chapterLoadError.value" role="alert">{{ vm.chapterLoadError.value }}</p>
        <button
          v-for="chapter in vm.chapterList.value"
          :key="chapter"
          type="button"
          :aria-current="chapter === vm.selectedChapter.value ? 'page' : undefined"
          @click="vm.selectChapter(chapter)"
        >
          <span>第 {{ chapter }} 章</span>
          <span>{{ vm.chapters[chapter]?.title || '' }}</span>
        </button>
      </nav>
      <main class="public-demo-reader__document">
        <p v-if="vm.editorState.loading" role="status">正在加载正文…</p>
        <p v-else-if="vm.editorState.loadError" role="alert">{{ vm.editorState.loadError }}</p>
        <article v-else-if="vm.selectedChapter.value" aria-labelledby="public-demo-chapter-title">
          <p>第 {{ vm.selectedChapter.value }} 章 · 正式正文</p>
          <h1 id="public-demo-chapter-title">{{ vm.editorState.title || `第 ${vm.selectedChapter.value} 章` }}</h1>
          <div class="public-demo-reader__content">{{ vm.editorState.content }}</div>
        </article>
        <p v-else>{{ vm.chapterList.value.length ? "请选择一章开始阅读。" : "演示项目暂无可阅读的正式正文。" }}</p>
      </main>
    </div>
  </template>
  <template v-else-if="vm.homeMode.value">
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
  <div v-else class="writing-toolbar writing-document-toolbar">
    <div class="view-header__title">
      <button type="button" class="btn btn-sm btn-ghost writing-home-back" data-action="open-writing-home" @click="openWritingHome">← 写作首页</button>
      <span class="view-header__count">共 {{ vm.chapterList.value.length }} 章</span>
    </div>
    <div class="view-header__actions">
      <button type="button" class="btn btn-sm" :aria-expanded="leftRailOpen" @click="toggleRail('chapters', $event)">章节</button>
      <button v-if="!isBlankWork" type="button" class="btn btn-sm" :aria-expanded="rightRailOpen" @click="toggleRail('reference', $event)">本章资料</button>
      <button ref="chapterMapTriggerEl" type="button" class="btn btn-sm" :disabled="!hasEditableChapter" data-action="open-chapter-map" @click="openChapterMap()">本章地图</button>
      <details ref="viewMenuEl" class="writing-page-menu" @toggle="onViewMenuToggle" @keydown="onViewMenuKeydown">
        <summary
          class="btn btn-sm"
          aria-controls="writing-page-menu-body"
          :aria-expanded="String(viewMenuOpen)"
        >写作视图 <span class="writing-page-menu__chevron" aria-hidden="true">⌄</span></summary>
        <div id="writing-page-menu-body" class="writing-page-menu__body" @click="closeViewMenuAfterAction">
          <button type="button" class="btn btn-sm" :disabled="!hasEditableChapter" @click="toggleFocusMode">进入专注</button>
          <button type="button" class="btn btn-sm" data-action="toggle-outline-float" @click="vm.toggleOutlineFloat">故事结构浮窗</button>
          <button type="button" class="btn btn-sm" @click="vm.navigateOutline">打开故事结构</button>
          <button type="button" class="btn btn-sm" :disabled="!vm.selectedChapter.value" @click="addChapterTask">添加到计划中的任务</button>
        </div>
      </details>
    </div>
  </div>

  <section v-if="props.semanticReview" aria-label="深度审稿报告"><AssistantReviewResult :result="props.semanticReview" /><p>问题由你决定如何处理；可就地修改正文，保存后重新审稿。</p><button class="btn btn-sm" :disabled="vm.editorState.dirty || vm.editorState.saving" @click="openDeepReview">重新深度审稿</button></section>
  <nav v-if="!vm.focusMode.value && !isBlankWork" class="writing-task-paths" aria-label="写作任务">
    <button type="button" class="btn btn-sm" :disabled="!hasEditableChapter" @click="openWritingTask('lookup')">查这里</button>
    <button type="button" class="btn btn-sm" :disabled="!hasEditableChapter || vm.editorState.readonly" @click="openWritingTask('revise')">修改这里</button>
    <button type="button" class="btn btn-sm" :disabled="!hasEditableChapter" @click="openWritingTask('forecast')">想下一步</button>
    <button type="button" class="btn btn-sm" :disabled="!hasEditableChapter" @click="openWritingTask('comments')">检查本章</button>
  </nav>
  <WritingWorkflowBars
    :publish="vm.publishProgress"
    :conflict="vm.conflictState"
    :deep-import="vm.deepImportState"
    :deep-import-has-scenes="vm.deepImportHasScenes.value"
    :generation="vm.generationTask"
    :conflict-task="vm.conflictTask"
    @cancel="vm.cancelDeepImport"
    @resume="vm.resumeDeepImport"
    @abandon="vm.abandonDeepImport"
    @dismiss="vm.dismissDeepImport"
    @open-audit="vm.deepAuditOpen.value = true"
    @open-review-resolution="openReviewResolution"
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

  <WritingFlowHost :controller="flowHost" />

  <div
    class="writing-workspace-layout"
    :class="{ 'writing-workspace-layout--candidate': vm.editorState.status === 'candidate', 'writing-workspace-layout--blank': isBlankWork }"
  >
    <WorkspaceDrawer :mobile="vm.isNarrow.value" :open="leftRailOpen" title="章节" @close="leftRailOpen = false">
    <aside
      class="workspace-rail writing-tree-rail workspace-rail--left"
      :class="{ 'is-collapsed': !leftRailOpen }"
      aria-label="章节"
    >
      <div id="writing-tree-container">
        <button
          v-if="leftRailOpen"
          type="button"
          class="btn btn-sm writing-chapter-order-open"
          :disabled="vm.editorState.readonly || vm.editorState.dirty || vm.editorState.saving || !vm.chapterList.value.length"
          @click="chapterOrderOpen = true"
        >调整章节顺序</button>
        <ChapterTree
          :chapter-list="vm.chapterList.value"
          :chapters="vm.chapters"
          :selected-chapter="vm.selectedChapter.value"
          :load-error="vm.chapterLoadError.value"
          :collapsed="!leftRailOpen"
          @select="selectChapterFromTree"
          @create="vm.createChapter"
          @delete-selected="vm.deleteChapters"
          @toggle-collapse="toggleRail('chapters')"
        />
      </div>
    </aside>
    </WorkspaceDrawer>

    <main id="writing-editor-container">
      <WritingEditor
        ref="writingEditorRef"
        :project-id="props.projectId"
        :deep-review-available="deepReviewAvailable"
        :editorial-available="editorialAvailable"
        :exporting-adopted="Boolean(vm.exportingAdopted.value)"
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
        :comments="writingComments.comments.value"
        :candidate-comparison-available="vm.candidateComparisonAvailable.value"
        :attach="vm.attachEditor"
        :detach="vm.detachEditor"
        @open-chapters="leftRailOpen = true"
        @create-chapter="vm.createChapter"
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
        @adopt="vm.adoptCandidate"
        @reject="rejectCandidate"
        @semantic-review="vm.reviewCandidate"
        @deep-review="openDeepReview"
        @editorial-ready="markEditorialReady"
        @editorial-open="openEditorialDesk"
        @targeted-revision="vm.reviseCandidate"
        @regenerate-candidate="vm.regenerateCandidate"
        @compare-candidate="vm.compareCandidateWithWorkingDraft"
        @open-candidate="openFlowCandidate({ draft_id: $event })"
        @export="vm.exportChapter"
        @export-book="vm.exportWholeBook"
        @retry-load="vm.retryChapterLoad"
        @reload-server="reloadServerDraft"
        @composition="setComposition"
        @focus-context="forecastFocus = $event"
        @add-comment="openWritingComment"
        @save-example="openExampleDialog"
      >
        <template #context-actions>
          <div v-if="versionChoices.length" id="writing-versions-container" class="writing-version-bar writing-version-bar--compact">
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
                  v-for="version in versionChoices"
                  :key="version.id"
                  :value="version.id"
                  :data-version="version.version_number"
                  :data-latest="version.id === vm.activeVersions.value[0]?.id ? 1 : 0"
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
          <p
            v-if="vm.editorialReviewNotice.value"
            id="writing-editorial-review-notice"
            class="writing-editorial-review-notice"
            role="status"
          >本章正在接受编辑审读；保存修改后，本次审读会失效（已读部分保留）。</p>
        </template>
      </WritingEditor>

      <p v-if="vm.versionLoadError.value" class="writing-empty-hint" role="alert">{{ vm.versionLoadError.value }}</p>
    </main>

    <WorkspaceDrawer v-if="!isBlankWork" :mobile="vm.isCompact.value" :open="rightRailOpen" title="本章资料" @close="rightRailOpen = false">
    <aside
      class="workspace-rail writing-panel-rail workspace-rail--right"
      :class="{ 'is-collapsed': !rightRailOpen }"
      aria-label="本章资料"
    >
      <div id="writing-panel-container">
        <div class="writing-reference-tabs" role="group" aria-label="资料与当前任务">
          <button class="btn btn-sm" :aria-pressed="referenceMode === 'reference'" @click="referenceMode = 'reference'">本场与参考</button>
          <button class="btn btn-sm" :aria-pressed="referenceMode === 'comments'" @click="referenceMode = 'comments'">批注</button>
          <button class="btn btn-sm" :aria-pressed="referenceMode === 'forecast'" @click="referenceMode = 'forecast'">前瞻</button>
        </div>
        <WritingReferenceSearch v-show="referenceMode === 'reference'" :project-id="props.projectId" :selection="referenceSearchSelection" :chapter-index="vm.selectedChapter.value" @open-object="openWorldObject" />
        <WritingCommentsPanel
          v-show="referenceMode === 'comments'"
          :comments="writingComments.comments.value"
          :selection="writingComments.selection.value"
          :task="writingComments.task.value"
          :busy="writingComments.busy.value"
          :error="writingComments.error.value"
          :can-run="commentCanRun"
          @save-comment="writingComments.create($event)"
          @cancel-comment="writingComments.selection.value = null"
          @run-review="writingComments.run($event, true)"
          @run-comments="writingComments.run($event, false)"
          @refresh-task="writingComments.poll($event)"
          @locate="locateWritingComment"
          @set-status="writingComments.setStatus"
          @open-candidate="writingComments.openCandidate($event)"
          @open-proposals="writingComments.openProposals($event)"
        />
        <ForecastDock
          v-show="referenceMode === 'forecast'"
          v-if="vm.editorState.draftId && !vm.editorState.readonly && !vm.editorState.loading && !vm.editorState.loadError"
          data-writing-forecast-dock
          :project-id="props.projectId"
          :context="{ page: 'writing', draft_id: vm.editorState.draftId, ...(forecastFocus?.draft_id === vm.editorState.draftId ? forecastFocus : {}), scene_id: vm.currentScene.value?.id || null }"
          :editor="vm.editorState"
          :composing="forecastComposing"
          :active="rightRailOpen && referenceMode === 'forecast'"
        />
        <SceneCockpit
          v-show="referenceMode === 'reference'"
          :project-id="projectId"
          :chapter="vm.selectedChapter.value"
          :scene="vm.currentScene.value"
          :scenes="vm.chapterScenes.value"
          :all-scenes="vm.activeScenes.value"
          :associate-scene="vm.associateScene"
          :create-scene="vm.createSceneForChapter"
          :unsaved="vm.editorState.dirty || vm.editorState.saving"
          :read-only="props.publicDemo || vm.editorState.readonly"
          :lens="vm.sceneLens"
          :evidence-refs="vm.focusedSelection.refs.value"
          :director-reference-ids="vm.directorReferenceIds.value"
          :rail-collapsed="!rightRailOpen"
          @select-scene="vm.selectScene"
          @load-lens="vm.loadSceneLens"
          @start-trial="startStateTrial"
          @pin-evidence="vm.focusedSelection.add"
          @clear-evidence="vm.focusedSelection.clear"
          @update:director-reference-ids="vm.setDirectorReferenceIds"
          @organize="vm.navigateSceneWorkbench"
          @open-notice="openCockpitNotice"
          @open-world-object="openWorldObject"
          @toggle-collapse="toggleRail('reference')"
        />
      </div>
    </aside>
    </WorkspaceDrawer>

    <footer v-if="!isBlankWork" class="writing-statusbar">
      <div id="writing-wordcount-bar" class="writing-wordcount-bar">
        <span><strong>{{ statusWordCount.toLocaleString() }}</strong> 字</span>
        <span v-if="dailyGoalNumber" class="wc-daily-goal">
          日目标 {{ vm.todayWords.value.toLocaleString() }} / {{ dailyGoalNumber.toLocaleString() }}
          <span class="wc-goal-progress" aria-hidden="true"><span class="wc-goal-fill" :style="{ width: `${goalPercent}%` }" /></span>
        </span>
        <span v-if="vm.isNarrow.value" id="writing-today-words" class="writing-today-count">今日 {{ vm.todayWords.value.toLocaleString() }} 字</span>
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

  <ChapterMapDialog
    v-if="props.projectId && vm.selectedChapter.value"
    :open="chapterMapOpen"
    :project-id="props.projectId"
    :chapter="vm.selectedChapter.value"
    :entity-id="chapterMapEntityId"
    @close="chapterMapOpen = false"
  />
  <OutlineFloat
    :model="vm.outlineFloat"
    :current-chapter="vm.selectedChapter.value"
    :current-scene="vm.currentScene.value"
    :public-demo="props.publicDemo"
    @close="vm.toggleOutlineFloat"
    @select="selectChapterFromTree"
    @refresh-arcs="vm.loadOutlineArcComparisons"
    @update-arc-draft="vm.updateArcDraft"
    @preview-arc="vm.previewCharacterArcPlan"
    @confirm-arc="vm.confirmCharacterArcPlan"
    @cancel-arc-preview="vm.cancelCharacterArcPreview"
    @toggle-arc-history="vm.toggleCharacterArcHistory"
    @preview-restore-arc="vm.previewRestoreCharacterArcPlan"
    @confirm-restore-arc="vm.confirmRestoreCharacterArcPlan"
    @preview-unarchive="vm.previewUnarchiveCharacterArcPlan"
    @confirm-unarchive="vm.confirmUnarchiveCharacterArcPlan"
    @preview-archive="vm.previewArchiveCharacterArcPlan"
    @confirm-archive="vm.confirmArchiveCharacterArcPlan"
    @cancel-arc-management-preview="vm.cancelCharacterArcManagementPreview"
  />
  <AutoExtractionDialog :project-id="props.projectId" :model="vm.autoExtraction" @submit="vm.submitAutoExtraction" />
  <ConflictOptionsDialog :model="vm.conflictOptions" @submit="vm.runConflictCheck" />
  <ConflictDetailDialog
    :model="vm.conflictDialog"
    @rerun="vm.runConflictCheck({ force: true })"
    @close="vm.closeConflictDialog"
    @status="vm.updateConflictStatus"
    @confirm-continuity="vm.confirmContinuityFact"
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
  <AuthorExampleDialog
    :open="exampleDialogOpen"
    :project-id="props.projectId"
    :draft="exampleDraft"
    @close="exampleDialogOpen = false"
    @saved="onExampleSaved"
  />
  <ChapterOrderDialog
    :open="chapterOrderOpen"
    :project-id="props.projectId"
    :chapter-list="vm.chapterList.value"
    :chapters="vm.chapters"
    :selected-chapter="vm.selectedChapter.value"
    :blocked="vm.editorState.readonly || vm.editorState.dirty || vm.editorState.saving"
    @close="chapterOrderOpen = false"
    @completed="onChapterOrderCompleted"
  />
  </template>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import AssistantReviewResult from "../../components/AssistantReviewResult.vue"
import WritingReferenceSearch from './components/WritingReferenceSearch.vue'
import { readWritingObjectReturn, rememberWritingObjectReturn, writingContentHash } from "../../shared/writingObjectReturn.js"
import ForecastDock from "../../components/ForecastDock.vue"
import ChapterTree from "./components/ChapterTree.vue"
import ChapterOrderDialog from "./components/ChapterOrderDialog.vue"
import ChapterMapDialog from "./components/ChapterMapDialog.vue"
import AutoExtractionDialog from "./components/AutoExtractionDialog.vue"
import ConflictDetailDialog from "./components/ConflictDetailDialog.vue"
import ConflictOptionsDialog from "./components/ConflictOptionsDialog.vue"
import DeepImportAuditDialog from "./components/DeepImportAuditDialog.vue"
import WorkspaceDrawer from "../../components/WorkspaceDrawer.vue"
import OutlineFloat from "./components/OutlineFloat.vue"
import SceneCockpit from "./components/SceneCockpit.vue"
import VersionHistoryDialog from "./components/VersionHistoryDialog.vue"
import WritingEditor from "./components/WritingEditor.vue"
import WritingCommentsPanel from "./components/WritingCommentsPanel.vue"
import WritingWorkflowBars from "./components/WritingWorkflowBars.vue"
import WritingFlowHost from "./components/WritingFlowHost.vue"
import { createGuidedFlowController } from "./controllers/guidedFlowController.js"
import AuthorExampleDialog from "./components/AuthorExampleDialog.vue"
import WritingHomeView from "./home/WritingHomeView.vue"
import { authorTaskPanelQuery } from "./home/authorTaskSource.js"
import OwnerAiDrawer from "../../components/OwnerAiDrawer.vue"
import { getRouter, getApi, getToast, getRouteQuery, getAssistantWorkContext, getLocalDraftAccountScope, openProjectAssistant, setForecastComposing } from "../../bridge/index.js"
import { useWritingWorkspace } from "./useWritingWorkspace.js"
import { useWritingComments } from "./useWritingComments.js"
import { normalizeInvalidationNotice } from "./invalidationModel.js"
import "./writing-desk.css"

const props = defineProps({
  projectId: { type: String, default: null },
  chapterList: { type: Array, default: () => [] },
  chapters: { type: Object, default: () => ({}) },
  scenes: { type: Array, default: () => [] },
  chapterLoadError: { type: String, default: null },
  authorPreferences: { type: Object, default: () => ({ dailyGoal: null, editorFont: "system", defaultFocusMode: false }) },
  requestedLocation: { type: Object, default: null },
  homeMode: { type: Boolean, default: false },
  publicDemo: { type: Boolean, default: false },
  homeProps: { type: Object, default: () => ({}) },
  ownerAiOpen: { type: Boolean, default: false },
  ownerAiMode: { type: String, default: "writing" },
  semanticReview: { type: Object, default: null },
})

async function startStateTrial(stateTrial = null) {
  rightRailOpen.value = false
  await nextTick()
  try {
    await openProjectAssistant({ projectId: props.projectId, creative: true, stateTrial })
  } catch (error) {
    getToast()(error.message || "试改面板暂时无法打开", "error")
  }
}
const vm = useWritingWorkspace(props)
let viewDisposed = false
/* 空白作品：没有章节时右侧资料栏与状态栏无内容可展示，切换为单栏欢迎布局 */
const isBlankWork = computed(() => !props.publicDemo
  && !vm.homeMode.value
  && vm.chapterList.value.length === 0
  && !vm.chapterLoadError.value)
const writingEditorRef = ref(null)
const writingComments = useWritingComments(
  props.projectId, vm.editorState, vm.selectChapter, vm.selectRange,
  start => writingEditorRef.value?.scrollCommentIntoView(start),
)
const commentCanRun = computed(() => Boolean(
  vm.editorState.draftId && vm.editorState.contentHash && !vm.editorState.readonly
  && !vm.editorState.dirty && !vm.editorState.saving && !vm.editorState.loading
))
function openWritingComment(focus) {
  if (writingComments.prepare(focus)) { referenceMode.value = 'comments'; rightRailOpen.value = true }
}
const referenceMode = ref('reference')
const taskKey = () => {
  const account = getLocalDraftAccountScope()
  return account && vm.selectedChapter.value ? `workspace-task:${account}:${props.projectId}:writing:${vm.selectedChapter.value}` : null
}
watch(taskKey, key => {
  try {
    const saved = key ? sessionStorage.getItem(key) : null
    referenceMode.value = ['reference', 'comments', 'forecast'].includes(saved) ? saved : 'reference'
  } catch { referenceMode.value = 'reference' }
}, { immediate: true, flush: 'sync' })
watch(referenceMode, value => {
  const key = taskKey()
  try { if (key) sessionStorage.setItem(key, value) } catch { /* This preference contains no author input. */ }
}, { flush: 'sync' })
const referenceSearchSelection = ref('')
async function openWritingTask(task) {
  if (task === 'revise') {
    try {
      const context = { ...getAssistantWorkContext(props.projectId, 'writing'), task_hint: 'revise' }
      await openProjectAssistant({ projectId: props.projectId, context,
        message: '请围绕当前选区准备修改建议。先和我明确修改意图与必须保留的内容，再准备可比较的方案。' })
    } catch (error) { getToast()(error.message || '暂时无法打开修改讨论。', 'warning') }
    return
  }
  referenceMode.value = task === 'lookup' ? 'reference' : task
  if (task === 'lookup') referenceSearchSelection.value = forecastFocus.value?.selection || ''
  rightRailOpen.value = true
}

/* 作者写作示例（B3 few-shot）：candidate 卡片与正文选区就地存例 */
const exampleDialogOpen = ref(false)
const exampleDraft = ref(null)
const chapterOrderOpen = ref(false)
function openExampleDialog(payload) {
  const origin = payload?.origin || "selection"
  const chapterTitle = String(vm.editorState.title || vm.chapters?.[vm.selectedChapter.value]?.title || "")
  exampleDraft.value = {
    content: String(payload?.content ?? vm.editorState.content ?? "").slice(0, 2000),
    chapterIndex: Number(vm.selectedChapter.value) || null,
    title: chapterTitle,
    candidateId: origin === "candidate" ? (vm.editorState.draftId || null) : null,
    contentLocked: false,
  }
  exampleDialogOpen.value = true
}

async function onChapterOrderCompleted({ result, restored, projectId, selectedChapter }) {
  if (!projectId || projectId !== props.projectId) return
  const currentChapter = Number(selectedChapter) || null
  const chapterMap = result?.chapter_map || {}
  const targetChapter = restored
    ? Number(Object.entries(chapterMap).find(([, target]) => Number(target) === currentChapter)?.[0] || currentChapter)
    : Number(chapterMap[currentChapter] || currentChapter)
  const [chaptersReloaded, scenesReloaded] = await Promise.all([vm.reloadChapters(), vm.reloadScenes()])
  if (viewDisposed) return
  if (!chaptersReloaded || !scenesReloaded) {
    getToast()("章节顺序已更新，但页面刷新失败，请重新打开写作页。", "warning")
    return
  }
  if (targetChapter && vm.chapterList.value.includes(targetChapter)) {
    await vm.selectChapter(targetChapter)
  }
  if (viewDisposed) return
  await vm.loadOutlineArcComparisons({ force: true })
  getToast()(restored ? "章节顺序已恢复" : "章节顺序已更新", "success")
}
async function onExampleSaved() {
  try {
    const toggle = await getApi().projects.authorExamplesForWriting(props.projectId)
    if (!toggle.enabled) getToast()("示例已保存。到「项目设置 → 写作示例」开启后，之后的生成才会参考。", "info")
  } catch { /* 提示失败不阻断保存结果 */ }
}
async function locateWritingComment(item) {
  if (vm.isNarrow.value) {
    rightRailOpen.value = false
    await nextTick()
  }
  writingComments.locate(item)
}
const versionChoices = computed(() => vm.versions.value.filter(version => version.status !== "deprecated" || version.id === vm.editorState.draftId))
const router = getRouter()
const deepReviewAvailable = ref(false)
const editorialAvailable = ref(false)
const guidedFlowAvailable = ref(false)
const forecastComposing = ref(false)
const forecastFocus = ref(null)
function setComposition(value) { forecastComposing.value = value; setForecastComposing(props.projectId, value) }

/* 引导流程宿主（ADR-0032）：只在能力可用时探测活动流程，否则整体隐藏。 */
const flowHost = createGuidedFlowController({
  api: getApi(),
  toast: (message, kind) => getToast()(message, kind),
  getProjectId: () => props.projectId,
  getSceneId: () => vm.currentScene.value?.id || null,
  onOpenCandidate: openFlowCandidate,
})
async function openFlowCandidate(candidate) {
  const chapter = Number(candidate.chapter_index) || vm.selectedChapter.value
  if (!chapter || !candidate.draft_id) return
  if (vm.isNarrow.value) rightRailOpen.value = false
  await vm.selectChapter(chapter, { draftId: candidate.draft_id, isReadonly: true })
}
watch(() => [props.projectId, guidedFlowAvailable.value, vm.homeMode.value], async ([projectId, available, homeMode]) => {
  flowHost.reset()
  if (!projectId || !available || homeMode || props.publicDemo) return
  const flowRunId = getRouteQuery()?.get("flow")
  if (flowRunId) await flowHost.attachRun(flowRunId)
  else await flowHost.probeActive()
}, { immediate: true })

watch(() => props.projectId, async projectId => {
  deepReviewAvailable.value = false
  editorialAvailable.value = false
  guidedFlowAvailable.value = false
  try {
    const value = await getApi().assistant.capabilities(projectId)
    if (projectId === props.projectId) {
      deepReviewAvailable.value = value.collaboration?.some(item => item.id === "deep_review" && item.available) === true
      editorialAvailable.value = value.editorial?.available === true
      guidedFlowAvailable.value = value.guided_flows?.available === true
    }
  } catch { /* ordinary writing remains available */ }
}, { immediate: true })
async function openEditorialDesk({ issueId = null, chapterIndex = null } = {}) {
  try {
    await openProjectAssistant({
      projectId: props.projectId,
      editorial: true,
      issueId,
      chapterIndex: Number(chapterIndex) || vm.selectedChapter.value,
    })
  }
  catch (error) { getToast()(error.message || "暂时无法打开编辑台。", "error") }
}

async function openRecomputePanel(action) {
  if (props.publicDemo || vm.editorState.readonly) {
    getToast()("当前为只读视图，不能打开重算处置。", "info")
    return
  }
  const targetChapter = Number(action?.chapter_index) || vm.selectedChapter.value
  if (!targetChapter) return
  const projectId = props.projectId
  if (Number(targetChapter) !== Number(vm.selectedChapter.value)) {
    await vm.selectChapter(targetChapter)
  }
  if (projectId !== props.projectId || Number(targetChapter) !== Number(vm.selectedChapter.value)) return
  const existingNotice = vm.editorState.invalidationNotice
  if (!existingNotice || (action?.receipt_id && existingNotice.receiptId !== action.receipt_id)) {
    try {
      const result = await getApi().evolution.pendingInvalidations(projectId, {
        chapterIndex: Number(targetChapter),
        limit: 100,
      })
      if (projectId !== props.projectId || Number(targetChapter) !== Number(vm.selectedChapter.value)) return
      const raw = (result?.items || []).find((item) => (
        action?.receipt_id ? item?.receipt_id === action.receipt_id : true
      ))
      const notice = normalizeInvalidationNotice(raw, { chapterIndex: Number(targetChapter) })
      if (!notice) {
        getToast()("这项重算提示已消解；请重新读取提醒。", "info")
        return
      }
      vm.editorState.invalidationNotice = notice
    } catch (error) {
      getToast()(error?.message || "重算选项暂时无法读取。", "error")
      return
    }
  }
  await nextTick()
  writingEditorRef.value?.openInvalidationPanel?.()
}

async function focusForecastDock() {
  referenceMode.value = 'forecast'
  rightRailOpen.value = true
  await nextTick()
  const dock = document.querySelector("[data-writing-forecast-dock]")
  if (!dock) {
    getToast()("当前没有可打开的前瞻面板；请切换到可编辑的工作稿。", "info")
    return
  }
  dock.scrollIntoView?.({ block: "nearest", behavior: "smooth" })
  dock.querySelector("button:not([disabled])")?.focus({ preventScroll: true })
}

async function openWorldObject(entityId) {
  if (!entityId) return
  const editor = document.getElementById('writing-editor')
  if (!editor || vm.editorState.loading || vm.editorState.saving) return
  const content = editor.value
  try {
    const location = { entityId, chapterIndex: Number(vm.selectedChapter.value), draftId: vm.editorState.draftId,
      contentHash: await writingContentHash(content), start: editor.selectionStart, end: editor.selectionEnd }
    if (viewDisposed || editor.value !== content) throw new Error('正文已变化，请重新打开对象。')
    rememberWritingObjectReturn(props.projectId, location)
    await router?.navigate("world", "objects", true, new URLSearchParams({ entity_id: entityId }))
  } catch (error) { getToast()(error.message || '无法保存原文位置，正文仍保留。', 'warning') }
}

let objectReturnHandled = false
watch(() => [vm.editorState.loading, vm.editorState.draftId], async () => {
  if (objectReturnHandled || vm.editorState.loading || !vm.editorState.draftId) return
  const entityId = getRouteQuery().get('return_from_object')
  if (!entityId) return
  objectReturnHandled = true
  const location = readWritingObjectReturn(props.projectId, entityId)
  const content = vm.editorState.content
  if (!location || location.chapterIndex !== Number(vm.selectedChapter.value)) return
  try {
    const contentHash = await writingContentHash(content)
    if (viewDisposed || vm.editorState.content !== content) return
    if (vm.editorState.draftId !== location.draftId || contentHash !== location.contentHash) {
      getToast()('原文已变化，当前输入已保留；请核对后重新定位。', 'info')
      return
    }
    await nextTick()
    await writingEditorRef.value?.restoreObjectPosition(location)
  } catch { getToast()('无法核对原文位置，当前正文仍保留。', 'warning') }
}, { flush: 'post' })

let sourceLocationHandled = null
watch(() => [props.requestedLocation, vm.editorState.loading, vm.editorState.draftId, vm.editorState.contentHash], async () => {
  const requested = props.requestedLocation
  if (vm.editorState.loading || !vm.editorState.draftId
    || !Number.isInteger(requested?.editorialOffset) || requested.editorialOffset < 0
    || !requested.editorialHash || Number(requested.chapter) !== Number(vm.selectedChapter.value)
    || (requested.draftId && requested.draftId !== vm.editorState.draftId)) return
  const key = `${props.projectId}:${requested.chapter}:${requested.draftId}:${requested.editorialHash}:${requested.editorialOffset}`
  if (sourceLocationHandled === key) return
  sourceLocationHandled = key
  const content = vm.editorState.content
  const draftId = vm.editorState.draftId
  try {
    const hash = await writingContentHash(content)
    if (viewDisposed || props.requestedLocation !== requested || vm.editorState.content !== content || vm.editorState.draftId !== draftId) return
    if (hash !== requested.editorialHash) { getToast()('这条来源引用的正文已变化，请重新读取当前依据。', 'info'); return }
    const start = Array.from(content).slice(0, requested.editorialOffset).join('').length
    await nextTick()
    if (!viewDisposed && props.requestedLocation === requested && vm.editorState.content === content && vm.editorState.draftId === draftId) await writingEditorRef.value?.restoreObjectPosition({ start, end: start })
  } catch { getToast()('无法核对来源位置，当前正文仍保留。', 'warning') }
}, { flush: 'post' })

async function openCockpitNotice(item) {
  const action = (item?.actions || []).find((value) => value?.kind === "navigate") || {}
  const projectId = props.projectId
  const chapterIndex = Number(action.chapter_index || item?.target?.chapter_index) || null
  if (chapterIndex && Number(chapterIndex) !== Number(vm.selectedChapter.value)) {
    await vm.selectChapter(chapterIndex)
  }
  if (projectId !== props.projectId) return
  const targetSceneId = action.scene_id || item?.target?.scene_id
  if (targetSceneId && vm.currentScene.value?.id !== targetSceneId) {
    const selected = await vm.selectScene(targetSceneId)
    if (!selected || projectId !== props.projectId) return
  }
  if (item?.source_id === "assistant.forecast") {
    await focusForecastDock()
    return
  }
  if (item?.source_id === "assistant.editorial") {
    await openEditorialDesk({
      issueId: action.issue_id || null,
      chapterIndex: chapterIndex || vm.selectedChapter.value,
    })
    return
  }
  if (item?.source_id === "assistant.proactive" && action.editorial === true) {
    await openEditorialDesk({
      issueId: action.issue_id || null,
      chapterIndex: chapterIndex || vm.selectedChapter.value,
    })
    return
  }
  if (item?.source_id === "evolution.reading" && action.open_evolution_reading === true) {
    vm.autoExtraction.open = true
    return
  }
  if (item?.source_id === "writing.invalidation") {
    await openRecomputePanel(action)
    return
  }
  if (item?.source_id === "writing.conflict") {
    const checkId = action.check_id || item?.target?.check_id
    const itemId = action.item_id || item?.target?.item_id || null
    if (checkId) await vm.openConflictDialog({ id: checkId }, itemId)
    else if (vm.conflictState.latest) await vm.openConflictDialog(vm.conflictState.latest, itemId)
    else vm.requestConflictCheck()
    return
  }
  if (item?.source_id === "world.map_source" || action.page === "map") {
    const query = new URLSearchParams()
    if (action.node_id) query.set("node_id", action.node_id)
    router?.navigate("map", null, true, query)
    return
  }
  if (item?.source_id === "story.structure" || action.page === "outline") {
    const query = new URLSearchParams()
    if (action.scene_id || item?.target?.scene_id) query.set("scene_id", action.scene_id || item.target.scene_id)
    if (action.scene_field) query.set("scene_field", action.scene_field)
    router?.navigate("outline", "scenes", true, query)
    return
  }
  if (action.page === "writing" && action.scene_id) {
    router?.navigate("writing", null, true, new URLSearchParams({ scene_id: action.scene_id }))
    return
  }
  getToast()("该来源没有可直接打开的详细入口。", "info")
}
async function markEditorialReady() {
  const state = vm.editorState
  if (!state.draftId || state.status !== "draft" || state.dirty || state.saving || !state.content.trim()) return
  const draftId = state.draftId
  const chapter = vm.selectedChapter.value
  const content = state.lastSavedContent
  try {
    const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content)))
    const expectedHash = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("")
    const saved = await getApi().writing.markEditorialReady(draftId, props.projectId, expectedHash)
    if (draftId === state.draftId && chapter === vm.selectedChapter.value && !state.dirty && state.lastSavedContent === content) {
      state.editorialReadyHash = saved.editorial_ready_hash
      state.contentHash = saved.content_hash
    }
    getToast()("这版工作稿已交编辑；可在编辑台查看或开始审读。", "success")
  } catch (error) { getToast()(error.message || "交给编辑失败，工作稿仍保留。", "error"); return }
  await openEditorialDesk()
}
async function openDeepReview() {
  if (vm.editorState.dirty || vm.editorState.saving) return
  try {
    const capabilities = await getApi().assistant.capabilities(props.projectId)
    const capability = capabilities.collaboration?.find(item => item.id === "deep_review")
    if (!capability?.available) throw new Error(capability?.reason || "深度审稿尚未开启。")
    const confirmation = vm.editorState.provenanceJson?.context_confirmation_id || vm.editorState.provenanceJson?.source_confirmation_id
    await openProjectAssistant({ projectId: props.projectId, blueprint: "deep_review",
      context: { page: "writing", scope: "current", chapter_index: vm.selectedChapter.value,
        draft_id: vm.editorState.draftId, scene_id: vm.currentScene.value?.id || null,
        ...(confirmation ? { context_confirmation_id: confirmation, context_confirmation_action: "writing.generate" } : {}) },
      message: "深度审稿这一章：独立核对事实规则、人物动机与知识、叙事和读者信息。保留有意留白，列明证据、反证与未检查范围。",
    })
  } catch (error) { getToast()(error.message || "暂时无法打开深度审稿。", "error") }
}
function openReviewResolution(taskId) { router?.navigate("world", "review", true, new URLSearchParams(taskId ? { review_task_id: taskId } : {})) }
const viewMenuEl = ref(null)
const viewMenuOpen = ref(false)
const chapterMapOpen = ref(false)
const chapterMapEntityId = ref(null)
const chapterMapTriggerEl = ref(null)
async function openChapterMap(entityId = null) {
  if (!hasEditableChapter.value) return
  const chapter = vm.selectedChapter.value
  chapterMapEntityId.value = entityId
  if (vm.isCompact.value && rightRailOpen.value) {
    rightRailOpen.value = false
    await nextTick()
    chapterMapTriggerEl.value?.focus()
  }
  if (vm.selectedChapter.value !== chapter) return
  chapterMapOpen.value = true
}
watch(() => [props.projectId, vm.selectedChapter.value, vm.currentScene.value?.id], () => {
  chapterMapOpen.value = false
  chapterMapEntityId.value = null
})
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
  || ({ completed: "规则检查已完成", degraded: "检查覆盖不完整", running: "检查中", failed: "检查失败" })[vm.conflictState.latest?.status]
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
const stored = (rail, fallback) => {
  try {
    const value = sessionStorage.getItem(`workspace-rail:${props.projectId}:writing:${rail}`)
    return value ? value === "open" : fallback
  } catch { return fallback }
}
const leftRailOpen = ref(
  !vm.isNarrow.value && stored(
    "chapters",
    vm.chapterList.value.length === 0 || typeof window === "undefined" || window.innerWidth > 760,
  ),
)
const referenceDefault = () => props.scenes.some(scene => ["draft", "canonical"].includes(scene.status))
const rightRailOpen = ref(!vm.isCompact.value && stored("reference", referenceDefault()))

async function reloadServerDraft() {
  if (!await vm.reloadServerDraft()) return
  await nextTick()
  focusWritingEditor()
}

function focusWritingEditor() {
  document.querySelector("#writing-editor")?.focus()
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
  viewDisposed = true
  window.removeEventListener("keydown", onFocusKeydown)
  document.removeEventListener("pointerdown", onDocumentPointerdown)
  flowHost.dispose()
})

watch(vm.focusMode, (active) => {
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

async function selectChapterFromTree(chapter) {
  if (await vm.selectChapter(chapter) !== false && vm.isNarrow.value) leftRailOpen.value = false
}
watch(vm.isNarrow, (narrow) => { leftRailOpen.value = !narrow && stored("chapters", true) })
watch(vm.isCompact, (compact) => { rightRailOpen.value = !compact && stored("reference", referenceDefault()) })

function toggleRail(rail, event) {
  const current = rail === "chapters" ? leftRailOpen : rightRailOpen
  if (!current.value) event?.currentTarget?.focus({ preventScroll: true })
  current.value = !current.value
  if (rail === 'chapters' ? vm.isNarrow.value : vm.isCompact.value) return
  try { sessionStorage.setItem(`workspace-rail:${props.projectId}:writing:${rail}`, current.value ? "open" : "closed") } catch { /* noop */ }
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

<style scoped>
.writing-task-paths,.writing-reference-tabs{display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px;border-bottom:1px solid var(--border-color,var(--border))}
.writing-task-paths .btn,.writing-reference-tabs .btn{min-height:40px}
.writing-reference-tabs [aria-pressed=true]{background:var(--bg-muted);font-weight:600}
</style>
