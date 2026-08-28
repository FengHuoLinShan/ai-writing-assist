<template>
  <div class="outline-scene-layout">
    <OutlineHeader sub-view="scenes" :item-count="total">
      <template #actions>
        <span class="scene-view-mode-toggle" role="group" aria-label="场景浏览模式">
          <button type="button" class="btn btn-sm" :aria-pressed="viewMode === 'normal'" data-action="set-scene-view-mode" data-mode="normal" @click="runAfterDiscard(() => setViewMode('normal'))">普通</button>
          <button type="button" class="btn btn-sm" :aria-pressed="viewMode === 'hot'" data-action="set-scene-view-mode" data-mode="hot" @click="runAfterDiscard(() => setViewMode('hot'))">热点</button>
        </span>
        <button type="button" class="btn btn-sm btn-primary" data-action="ai-create-planned-scene" @click="createPlannedScene">AI 创作细纲</button>
        <details class="scene-workbench-tools">
          <summary class="btn btn-sm">整理工具</summary>
          <div class="scene-workbench-tools__menu">
            <button type="button" class="btn btn-sm" data-action="scene-auto-extract" :disabled="autoExtractionBusy" @click="showAutoExtractForm">{{ autoExtractionBusy ? "整理中..." : "从正文整理场景" }}</button>
            <span data-role="smart-dedup-action"></span>
          </div>
        </details>
      </template>
    </OutlineHeader>

    <section v-if="hasAnyTaskProgress" class="outline-task-status" aria-labelledby="scene-active-tasks-title">
      <h3 id="scene-active-tasks-title" class="outline-task-status__title">AI 任务</h3>
      <div data-outline-generate-slot>
        <OutlineGenerateProgressCard />
      </div>
      <SceneAutoExtractProgressCard @cancel="cancelAutoExtraction" @dismiss="dismissAutoExtraction" />

      <div v-if="fusionTask.progress" class="scene-progress-card-wrap" data-role="scene-fusion-preview-progress">
        <WorkflowProgressCard
          :progress="fusionTask.progress"
          title="场景融合预览"
          :message="fusionTask.progress.message || ''"
          :collapsible="true"
          :show-task-id="false"
        >
          <div class="workflow-progress__actions">
            <button v-if="fusionTask.preview" class="btn btn-sm btn-primary" data-action="view-scene-fusion-preview" @click="modalController.showCompletedFusionPreview()">查看预览</button>
            <button v-if="!fusionTask.progress.terminal" class="btn btn-sm" data-action="cancel-scene-fusion-preview" @click="modalController.cancelFusionTask()">取消任务</button>
            <button v-else class="btn btn-sm" data-action="dismiss-scene-fusion-preview" @click="modalController.dismissFusionTask()">关闭</button>
          </div>
        </WorkflowProgressCard>
      </div>
    </section>

    <div class="scene-workbench-shell">
      <div v-if="pendingSuggestionCount" class="scene-fusion-queue" role="status">
        <div>
          <strong>{{ pendingSuggestionCount }} 条场景建议待处理</strong>
          <span>包含场景合并决定或受保护内容的替换检查，刷新后仍可继续。</span>
        </div>
        <button class="btn btn-sm btn-primary" data-action="show-fusion-suggestions" @click="modalController.showSuggestions()">逐条处理</button>
        <button v-if="dismissibleSuggestionCount" class="btn btn-sm" data-action="dismiss-fusion-suggestions" @click="modalController.dismissAllSuggestions()">忽略融合建议</button>
      </div>

      <div v-if="loading && !workbench" class="loading-skeleton" role="status" aria-live="polite" aria-busy="true">
        <span class="sr-only">场景工作台加载中...</span>
        <div class="skeleton loading-skeleton__heading" aria-hidden="true"></div>
        <div class="skeleton loading-skeleton__line" aria-hidden="true"></div>
        <div class="skeleton loading-skeleton__line loading-skeleton__line--medium" aria-hidden="true"></div>
      </div>
      <div v-else-if="loadError && !workbench" class="empty-state" role="alert">
        <div class="empty-icon">!</div>
        <p>场景工作台暂不可用。</p>
        <p>{{ loadError }}</p>
        <button class="btn btn-sm" data-action="retry-scene-workbench" @click="refresh()">重新加载</button>
      </div>
      <div v-else-if="workbench" class="scene-runtime-shell" :class="{ 'is-narrow': narrow }">
        <SceneRuntimeTabs :active-tab="storyWorkspace.activeTab" @select="storyWorkspace.selectTab" />
        <div v-if="storyWorkspace.activeTab === 'management'" id="scene-runtime-panel-management" class="scene-runtime-management" role="tabpanel" aria-labelledby="scene-runtime-tab-management">
        <div class="scene-workbench" :class="{ 'is-narrow': narrow }">
        <section class="scene-workbench__organize" :aria-busy="loading ? 'true' : 'false'">
          <div v-if="loading" class="scene-workbench-refresh" role="status" aria-live="polite">
            <strong>正在更新场景列表…</strong>
            <span>完成前保留当前内容。</span>
          </div>
          <div v-else-if="loadError" class="scene-workbench-refresh scene-workbench-refresh--error" role="alert">
            <span><strong>场景列表未能更新</strong>当前内容仍保留，可以重试。</span>
            <button type="button" class="btn btn-sm" data-action="retry-scene-refresh" @click="refresh()">重试</button>
          </div>
          <div class="scene-workbench__content" :inert="loading ? '' : undefined">
          <details ref="filterPanel" class="outline-structure-filters scene-workbench-filters" aria-label="场景筛选">
            <summary>
              <span class="outline-structure-filters__label">搜索与筛选</span>
              <span class="outline-structure-filters__summary">{{ filterSummary }}</span>
            </summary>
            <div class="scene-management-filters" aria-label="场景筛选条件">
              <label class="scene-filter-field scene-filter-field--wide"><span>搜索</span><input id="scene-filter-q" v-model="filterForm.q" class="form-input" placeholder="标题 / 目标 / 冲突" /></label>
              <label class="scene-filter-field"><span>起始章</span><input id="scene-filter-chapter-from" v-model="filterForm.chapter_from" class="form-input" type="number" min="1" /></label>
              <label class="scene-filter-field"><span>结束章</span><input id="scene-filter-chapter-to" v-model="filterForm.chapter_to" class="form-input" type="number" min="1" /></label>
              <label class="scene-filter-field"><span>状态</span><select id="scene-filter-status" v-model="filterForm.status" class="form-select"><option value="">全部状态</option><option v-for="[value, label] in STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
              <label class="scene-filter-field"><span>来源</span><select id="scene-filter-source" v-model="filterForm.source" class="form-select"><option value="">全部来源</option><option v-for="[value, label] in SOURCE_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
              <label class="scene-filter-field"><span>注意</span><select id="scene-filter-needs-review" v-model="filterForm.needs_review" class="form-select"><option value="">全部注意原因</option><option value="true">需要人工检查</option><option value="false">无注意项</option></select></label>
              <details class="outline-structure-diagnostic-filters scene-workbench-more-filters" :open="advancedFiltersOpen" @toggle="syncAdvancedFilters">
                <summary data-action="toggle-advanced-scene-filters">更多筛选{{ advancedFilterCount ? `（${advancedFilterCount} 项）` : "" }}</summary>
                <div class="scene-workbench-more-filters__fields">
                  <label class="scene-filter-field scene-filter-field--wide"><span>整理批次</span><input id="scene-filter-workflow-id" v-model="filterForm.workflow_id" class="form-input" data-diagnostic-field placeholder="需要排查某次整理时填写" /></label>
                  <label class="scene-filter-field"><span>范围状态</span><select id="scene-filter-boundary-status" v-model="filterForm.boundary_status" class="form-select"><option value="">全部范围</option><option v-for="[value, label] in BOUNDARY_STATUS_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
                  <label class="scene-filter-field"><span>整理阶段</span><select id="scene-filter-phase" v-model="filterForm.phase" class="form-select"><option value="">全部阶段</option><option v-for="[value, label] in PHASE_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
                  <label class="scene-filter-field"><span>AI 判断把握</span><select id="scene-filter-confidence-band" v-model="filterForm.confidence_band" class="form-select"><option value="">全部</option><option v-for="[value, label] in CONFIDENCE_BAND_OPTIONS" :key="value" :value="value">{{ label }}</option></select></label>
                  <label class="scene-filter-checkbox"><input id="scene-filter-phase1a-fallback" v-model="filterForm.phase1a_fallback" type="checkbox" /><span>仅看正文切分降级结果</span></label>
                </div>
              </details>
              <div class="scene-filter-actions">
                <button type="button" class="btn btn-sm btn-primary" data-action="apply-scene-filters" @click="runAfterDiscard(applyFilters)">应用</button>
                <button type="button" class="btn btn-sm" data-action="reset-scene-filters" @click="runAfterDiscard(resetFilters)">重置</button>
              </div>
            </div>
          </details>

          <details class="scene-workbench-overview" aria-label="场景概况" :open="!narrow">
            <summary data-action="toggle-scene-overview">
              <strong>场景概况</strong>
              <span>{{ overviewSummary }}</span>
            </summary>
            <div class="scene-workbench-overview__body">
              <section v-if="viewMode === 'hot' && workbench.progress" class="scene-progress-panel" aria-label="剧情进度">
                <div class="scene-progress-panel__heading"><strong>当前剧情定位</strong><span>{{ workbench.progress.as_of_chapter == null ? '尚无有效章节' : `截至第 ${workbench.progress.as_of_chapter} 章` }}</span></div>
                <div class="scene-progress-bar">
                  <button v-for="[key, label] in PROGRESS_ITEMS" :key="key" type="button" class="scene-progress-filter" :class="[`scene-progress-filter--${key}`, { active: filters.segment === key }]" :aria-pressed="filters.segment === key" data-action="filter-progress-segment" :data-segment="key" @click="runAfterDiscard(() => toggleSegment(key))"><span>{{ label }}</span><strong>{{ workbench.progress[key] ?? 0 }}</strong></button>
                </div>
              </section>

              <div class="scene-health-bar">
                <button v-for="[key, fallback] in HEALTH_ORDER" :key="key" class="scene-health-filter" :class="{ active: (filters.health || activeHealth) === key }" data-action="filter-health" :data-id="key" @click="runAfterDiscard(() => toggleHealth(key))">
                  <span>{{ healthLabel(key) || fallback }}</span><strong>{{ workbench.health?.[key]?.count ?? 0 }}</strong>
                  <small v-if="key === 'needs_organize' && healthBreakdownText">{{ healthBreakdownText }}</small>
                </button>
              </div>
              <p v-if="healthBreakdownText" class="scene-health-count-note" role="note">待整理总数按场景去重；结构、正文定位和合并等原因可能同时出现在同一场景。</p>
            </div>
          </details>

          <div v-if="selectedIds.size" class="scene-fusion-toolbar" aria-label="场景批量操作">
            <div class="scene-fusion-toolbar__status" role="status" aria-atomic="true"><strong>{{ selectedIds.size }}</strong><span>个场景已选</span><span class="scene-fusion-toolbar__hint">{{ selectionHint }}</span></div>
            <button class="btn btn-sm" data-action="toggle-visible-fusion-selection" :disabled="visibleIds.length === 0" :title="allVisibleSelected ? '取消选择当前列表中的场景' : '选择当前列表中的全部场景'" @click="toggleVisibleSelection">{{ allVisibleSelected ? '取消全选' : '全选当前列表' }}</button>
            <button class="btn btn-sm btn-primary" data-action="handle-selected-context-actions" :disabled="selectedIds.size === 0" @click="runSelectedContextActions">{{ batchLabel }}</button>
            <button v-if="selectedIds.size >= 2" class="btn btn-sm" data-action="start-selected-merge" @click="modalController.startSelectedMerge(Array.from(selectedIds))">机械合并</button>
            <button v-if="selectedIds.size >= 2" class="btn btn-sm" data-action="start-ai-fusion-draft" @click="modalController.startFusion(Array.from(selectedIds))">AI 融合建议</button>
            <button class="btn btn-sm btn-text" data-action="clear-fusion-selection" @click="clearSelection">退出选择</button>
          </div>

          <div v-if="items.length || visibleUnassignedChapters.length" class="scene-workbench-list">
            <article v-for="item in items" :key="item.scene?.id" class="scene-workbench-row" :class="{ 'is-selected': selectedItem?.scene?.id === item.scene?.id }" :data-id="item.scene?.id">
              <label class="scene-fusion-select selection-checkbox" title="选择用于批量操作"><input type="checkbox" data-action="toggle-fusion-selection" :data-id="item.scene?.id" aria-label="选择用于批量操作" :checked="selectedIds.has(item.scene?.id)" @change="toggleSelection(item.scene?.id, $event.target.checked)" /></label>
              <div class="scene-workbench-row__content">
                <button class="scene-workbench-row__main" data-action="select-workbench-scene" :data-id="item.scene?.id" @click="selectSceneSafely(item.scene?.id)">
                  <div class="scene-workbench-row__meta"><span>#{{ sceneIndex(item.scene) }}</span><span>{{ sceneStatusLabel(item.scene) }}</span><span>{{ sceneSourceLabel(item.scene) }}</span><span>{{ item.chapter_range || '未关联章节' }}</span><span v-if="segmentLabel(item.segment)" class="scene-progress-chip" :class="`scene-progress-chip--${item.segment}`">{{ segmentLabel(item.segment) }}</span></div>
                  <div class="scene-workbench-row__title">{{ item.scene?.title || '未命名场景' }}</div>
                  <div class="scene-workbench-row__summary">{{ item.summary || item.scene?.goal || '暂无目标' }}</div>
                  <div v-if="rowSpanSummary(item)" class="scene-workbench-row__mapping" aria-label="场景正文范围">{{ rowSpanSummary(item) }}</div>
                  <div v-if="rowOverlapSummary(item)" class="scene-workbench-row__overlap" aria-label="场景正文范围重叠">{{ rowOverlapSummary(item) }}</div>
                </button>
                <div class="scene-workbench-row__health"><button v-for="health in item.health || []" :key="health" class="scene-health-chip" data-action="handle-scene-health" :data-id="item.scene?.id" :data-health="health" :title="sceneContextAction(item, health).label" @click="runContextActionSafely(item, sceneContextAction(item, health))">{{ healthLabel(health) }}</button></div>
              </div>
              <div class="scene-workbench-row__actions">
                <button class="btn btn-sm scene-context-action" :class="{ 'btn-primary': sceneContextAction(item).key !== 'edit' }" :data-action="sceneContextAction(item).action" :data-id="item.scene?.id" @click="runContextActionSafely(item)">{{ sceneContextAction(item).label }}</button>
                <button v-if="firstOverlap(item)?.counterpart_scene_id" class="btn btn-sm scene-overlap-shortcut" data-action="open-overlap-scene" :data-id="firstOverlap(item).counterpart_scene_id" @click="openOverlapSafely(firstOverlap(item).counterpart_scene_id)">查看「{{ overlapCounterpartLabel(firstOverlap(item)) }}」</button>
                <button v-if="sceneContextAction(item).key !== 'edit'" class="btn btn-sm scene-secondary-action" data-action="edit-workbench-scene" :data-id="item.scene?.id" @click="selectSceneSafely(item.scene?.id)">编辑</button>
                <ActionMenu :menu-id="`scene-actions-${item.scene?.id}`" :label="`${item.scene?.title || '未命名场景'}的更多操作`" :items="menuItems(item)" @select="handleMenu(item, $event)" />
              </div>
            </article>
            <article v-for="chapter in visibleUnassignedChapters" :key="`unassigned-${chapter}`" class="scene-workbench-row scene-workbench-row--unassigned">
              <div class="scene-workbench-row__main"><div class="scene-workbench-row__meta"><span>未归类章节</span></div><div class="scene-workbench-row__title">第 {{ chapter }} 章</div><div class="scene-workbench-row__summary">尚未分配到场景</div></div>
              <div class="scene-workbench-row__actions"><button class="btn btn-sm" data-action="assign-unassigned-chapter" :data-chapter="chapter" @click="modalController.assignChapter(chapter)">分配场景</button></div>
            </article>
          </div>
          <div v-else class="empty-state scene-workbench-empty">
            <h2>{{ hasActiveFilters ? '没有找到符合条件的场景' : '还没有场景' }}</h2>
            <p>{{ hasActiveFilters ? '当前筛选可能过窄，清除后可以查看全部场景。' : '可以从已有正文整理情节，也可以让 AI 辅助设计第一个场景细纲。' }}</p>
            <div class="actions">
              <button v-if="hasActiveFilters" type="button" class="btn btn-primary" data-action="clear-scene-empty-filters" @click="runAfterDiscard(resetFilters)">清除筛选</button>
              <template v-else>
                <button type="button" class="btn btn-primary" data-action="empty-scene-auto-extract" :disabled="autoExtractionBusy" @click="showAutoExtractForm">从正文整理场景</button>
                <button type="button" class="btn" data-action="empty-ai-create-planned-scene" @click="createPlannedScene">AI 创作细纲</button>
              </template>
            </div>
          </div>

          <div v-if="total > filters.limit" class="scene-workbench-pagination">
            <button class="btn btn-sm" data-action="prev-scene-page" :disabled="filters.skip <= 0" @click="runAfterDiscard(() => changePage(-1))">上一页</button>
            <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条</span>
            <button class="btn btn-sm" data-action="next-scene-page" :disabled="filters.skip + filters.limit >= total" @click="runAfterDiscard(() => changePage(1))">下一页</button>
          </div>
          </div>
        </section>

        <details v-if="!narrow && selectedItem" class="workspace-rail scene-detail-rail workspace-rail--right" :data-workspace-rail-key="railKey" :open="railOpen" @toggle="onRailToggle">
          <summary class="workspace-rail__summary" :aria-label="`${railOpen ? '收起' : '展开'}场景详情`"><span class="workspace-rail__title">场景详情</span><span class="workspace-rail__chevron" aria-hidden="true"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg></span></summary>
          <div class="workspace-rail__body"><aside class="scene-workbench__detail"><SceneDetailPanel :project-id="projectId" :item="selectedItem" :draft="detailDraft" :dirty="detailDirty" :narrow="false" :saving="savingSceneId === selectedItem?.scene?.id" :save-error="sceneSaveError" @close="closeDesktopDetail" @context="runContextAction(selectedItem)" @save="saveScene(selectedItem?.scene?.id, detailDraft)" @merge="modalController.startMerge(selectedItem?.scene?.id)" @split="modalController.startSplit(selectedItem?.scene?.id)" @replacement="openOverlap" /></aside></div>
        </details>

        <div v-if="narrow && mobileDetailOpen && selectedItem" ref="mobileDrawerOverlayRef" class="scene-workbench-drawer" @keydown="onMobileDrawerKeydown" @focusin="onMobileDrawerFocusin" @click.self="requestCloseMobileDetail">
          <div ref="mobileDrawerDialogRef" class="scene-workbench-drawer__dialog" role="dialog" aria-modal="true" :aria-label="`编辑场景：${selectedItem.scene?.title || '未命名场景'}`" :aria-busy="savingSceneId === selectedItem.scene.id" tabindex="-1">
            <SceneDetailPanel :project-id="projectId" :item="selectedItem" :draft="detailDraft" :dirty="detailDirty" :narrow="true" :saving="savingSceneId === selectedItem.scene.id" :save-error="sceneSaveError" @close="requestCloseMobileDetail" @context="runContextAction(selectedItem)" @save="saveScene(selectedItem.scene.id, detailDraft)" @merge="modalController.startMerge(selectedItem.scene.id)" @split="modalController.startSplit(selectedItem.scene.id)" @replacement="openOverlap" />
          </div>
        </div>
        </div>
        </div>

        <CharacterCardsPanel
          v-else-if="storyWorkspace.activeTab === 'characters'"
          :scene="storyWorkspace.scene"
          :characters="storyWorkspace.characters"
          :notes="storyWorkspace.notes"
          :selected-id="storyWorkspace.selectedCharacterId"
          :card-draft="storyWorkspace.cardDraft"
          :card-history="storyWorkspace.cardHistory"
          :generated-card="storyWorkspace.generatedCard"
          :card-saving="storyWorkspace.cardSaving"
          :card-generating="storyWorkspace.characterCardRunning"
          :card-history-loading="storyWorkspace.cardHistoryLoading"
          :loading="storyWorkspace.loading"
          :error="storyWorkspace.loadError"
          @retry="storyWorkspace.loadWorkspace"
          @return-management="storyWorkspace.selectTab('management')"
          @select="storyWorkspace.selectCharacter"
          @note="storyWorkspace.updateNote"
          @edit="storyWorkspace.editCharacter"
          @update-card="storyWorkspace.updateCardDraft"
          @save-card="storyWorkspace.saveCharacterCard"
          @generate-card="storyWorkspace.startCharacterCardGeneration"
          @apply-generated="storyWorkspace.applyGeneratedCard"
          @history="storyWorkspace.loadCardHistory"
          @restore-history="storyWorkspace.restoreCardRevision"
        />
        <SceneSimulationPanel
          v-else-if="storyWorkspace.activeTab === 'simulation'"
          :scene="storyWorkspace.scene"
          :simulation="storyWorkspace.simulation"
          :progress="storyWorkspace.simulationProgress"
          :running="storyWorkspace.simulationRunning"
          :reaction-running="storyWorkspace.reactionRunning"
          :error="storyWorkspace.loadError"
          @run="storyWorkspace.startSimulation"
          @run-reactions="storyWorkspace.startReactionGeneration"
          @cancel="storyWorkspace.cancelSimulation"
          @reaction="storyWorkspace.setReactionStatus"
        />
        <SceneScriptsPanel
          v-else
          :scene="storyWorkspace.scene"
          :draft="storyWorkspace.scriptDraft"
          :scripts="storyWorkspace.scripts"
          :active-script-file-id="storyWorkspace.activeScriptFileId"
          :new-script-title="storyWorkspace.newScriptTitle"
          :script-history="storyWorkspace.scriptHistory"
          :script-preview="storyWorkspace.scriptPreview"
          :script-generating="storyWorkspace.scriptGenerating"
          :history-loading="storyWorkspace.scriptHistoryLoading"
          :findings="storyWorkspace.validation"
          :saved-at="storyWorkspace.scriptSavedAt"
          :saving="storyWorkspace.scriptSaving"
          @update:draft="storyWorkspace.updateScript"
          @validate="storyWorkspace.validateScript"
          @save="storyWorkspace.saveScript"
          @generate="storyWorkspace.startScriptGeneration"
          @apply-preview="storyWorkspace.applyScriptPreview"
          @history="storyWorkspace.loadScriptHistory"
          @adopt-revision="storyWorkspace.adoptScriptRevision"
          @unadopt="storyWorkspace.unadoptScriptFile"
          @select-file="storyWorkspace.selectScriptFile"
          @update-new-title="storyWorkspace.updateNewScriptTitle"
          @new-file="storyWorkspace.createScriptFile"
          @open-writing="openWriting(storyWorkspace.scene)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { structureAssetDisplay, worldAssetDisplay } from "../../../shared/assetDisplayState.js"
import { confirmAsync } from "../../../shared/confirmAsync.js"
import { getApi, getConfirm, getRouter } from "../../bridge/index.js"
import ActionMenu from "../../components/ActionMenu.vue"
import WorkflowProgressCard from "../../components/WorkflowProgressCard.vue"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { useModalDialog } from "../../composables/useModalDialog.js"
import OutlineGenerateProgressCard from "../outline/ai/OutlineGenerateProgressCard.vue"
import { showOutlineLayerAiForm } from "../outline/ai/outlineAiOps.js"
import { outlineGenerateManager } from "../outline/ai/outlineWorkflowManagers.js"
import OutlineHeader from "../outline/components/OutlineHeader.vue"
import { authorTaskPanelQuery } from "../writing/home/authorTaskSource.js"
import ReferencePickerAdapter from "../generate/components/ReferencePickerAdapter.vue"
import CharacterCardsPanel from "./CharacterCardsPanel.vue"
import SceneAutoExtractProgressCard from "./SceneAutoExtractProgressCard.vue"
import { sceneAutoExtractManager } from "./sceneAutoExtractManager.js"
import SceneRuntimeTabs from "./SceneRuntimeTabs.vue"
import SceneScriptsPanel from "./SceneScriptsPanel.vue"
import SceneSimulationPanel from "./SceneSimulationPanel.vue"
import { useSceneWorkbench } from "./useSceneWorkbench.js"
import { useStorySceneWorkspace } from "./useStorySceneWorkspace.js"
import {
  BOUNDARY_STATUS_OPTIONS,
  CONFIDENCE_BAND_OPTIONS,
  HEALTH_ORDER,
  PHASE_OPTIONS,
  SCENE_FILTER_DEFAULTS,
  SOURCE_OPTIONS,
  STATUS_OPTIONS,
  TAG_OPTIONS,
  healthReasons,
  overlapCounterpartLabel,
  sceneContextAction,
  sceneReviewState,
  sceneSourceLabel,
  sceneStatusLabel,
  spanSummaryLabel,
} from "./sceneModel.js"

const PROGRESS_ITEMS = [["current", "当前"], ["upcoming", "后续"], ["past", "已写过"], ["unassigned", "未定位"]]

const props = defineProps({
  projectId: { type: String, required: true },
  workbench: { type: Object, default: null },
  fusionSuggestions: { type: Array, default: () => [] },
  viewMode: { type: String, default: "hot" },
  selectedSceneId: { type: String, default: null },
  focusedSuggestionId: { type: String, default: null },
  sceneFilters: { type: Object, default: () => ({}) },
  activeHealth: { type: String, default: null },
  advancedFiltersOpen: { type: Boolean, default: false },
  sceneLoadError: { type: String, default: null },
})
const router = getRouter()

onMounted(() => {
  document.querySelector(".outline-toolbar")?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
})

const api = getApi()
function characterReferenceItem(character) {
  const display = worldAssetDisplay(character)
  return {
    kind: "character",
    id: character?.id || character?.entity_id,
    label: character?.name || "未命名人物",
    description: ["人物", character?.summary || character?.public_info].filter(Boolean).join(" · "),
    status: display.label,
    unavailable: display.isHistory,
  }
}
const characterSource = {
  kind: "character",
  label: "人物",
  async search(query, { projectId, limit }) {
    try {
      const data = await api.world.listEntities({ novel_id: projectId, display_state: "active", entity_type: "character", q: query || undefined, skip: 0, limit })
      return (data?.items || data || []).map(characterReferenceItem)
    } catch {
      throw new Error("人物加载失败，请重试")
    }
  },
  resolve: (ids, { projectId }) => Promise.all(ids.map(async (id) => {
    try {
      return characterReferenceItem(await api.world.getEntity(id, projectId))
    } catch {
      return { kind: "character", id, label: "不可用人物", unavailable: true }
    }
  })),
}

const vm = useSceneWorkbench(props)
const filterPanel = ref(null)
const storyWorkspace = reactive(useStorySceneWorkspace({
  projectId: props.projectId,
  selectedItem: vm.selectedItem,
}))
const {
  activeHealth, advancedFiltersOpen, allVisibleSelected, applyFilters: applyWorkbenchFilters, autoExtractionBusy,
  cancelAutoExtraction, changePage, clearSelectedScene, clearSelection, dismissAutoExtraction,
  dismissibleSuggestionCount, filterForm, filters, healthLabel, items, loadError,
  loading, mobileDetailOpen, modalController, narrow, openOverlap, openWriting,
  fusionTask, pendingSuggestionCount, refresh, resetFilters: resetWorkbenchFilters, runContextAction,
  runSelectedContextActions, saveScene, savingSceneId, sceneSaveError, selectScene, selectedIds, selectedItem,
  setViewMode, showAutoExtractForm, toggleAdvanced, toggleHealth, toggleSegment,
  toggleSelection, toggleVisibleSelection, total, viewMode, visibleIds, workbench,
} = vm

const hasAnyTaskProgress = computed(() => Boolean(
  outlineGenerateManager.state.progress
  || sceneAutoExtractManager.state.progress
  || fusionTask.progress,
))
const currentPage = computed(() => Math.floor(filters.skip / filters.limit) + 1)
const totalPages = computed(() => Math.ceil(total.value / filters.limit) || 1)
const FILTER_KEYS = Object.keys(SCENE_FILTER_DEFAULTS).filter((key) => !["skip", "limit"].includes(key))
const ADVANCED_FILTER_KEYS = ["workflow_id", "boundary_status", "phase", "confidence_band", "phase1a_fallback"]
const activeFilterCount = computed(() => FILTER_KEYS.filter((key) => filters[key] !== SCENE_FILTER_DEFAULTS[key]).length)
const advancedFilterCount = computed(() => ADVANCED_FILTER_KEYS.filter((key) => filterForm[key] !== SCENE_FILTER_DEFAULTS[key]).length)
const filterDraftDirty = computed(() => FILTER_KEYS.some((key) => filterForm[key] !== filters[key]))
const filterSummary = computed(() => {
  const applied = activeFilterCount.value ? `已启用 ${activeFilterCount.value} 项` : "未启用"
  return filterDraftDirty.value ? `${applied} · 有未应用修改` : applied
})
const hasActiveFilters = computed(() => activeFilterCount.value > 0)
const visibleUnassignedChapters = computed(() => {
  const chapters = workbench.value?.unassigned_chapters || []
  if (!chapters.length && activeHealth.value !== "unassigned") return []
  if (activeHealth.value && activeHealth.value !== "unassigned") return []
  return chapters
})
const healthBreakdownText = computed(() => {
  const breakdown = workbench.value?.health?.needs_organize?.breakdown || {}
  return [
    breakdown.scene_structure ? `结构 ${breakdown.scene_structure}` : "",
    breakdown.source_mapping ? `定位 ${breakdown.source_mapping}` : "",
    breakdown.scene_fusion_suggestion ? `融合 ${breakdown.scene_fusion_suggestion}` : "",
  ].filter(Boolean).join(" · ")
})
const overviewSummary = computed(() => {
  const progress = PROGRESS_ITEMS
    .map(([key, label]) => [key, label, Number(workbench.value?.progress?.[key] || 0)])
    .filter(([, , count]) => count > 0)
  const health = HEALTH_ORDER
    .map(([key, fallback]) => [key, healthLabel(key) || fallback, Number(workbench.value?.health?.[key]?.count || 0)])
    .filter(([, , count]) => count > 0)
  const preferredProgress = progress.find(([key]) => key === filters.segment) || progress[0]
  const preferredHealth = health.find(([key]) => key === (filters.health || activeHealth.value))
    || health.reduce((largest, item) => item[2] > largest[2] ? item : largest, health[0])
  const visible = [preferredProgress, preferredHealth].filter(Boolean)
  const hiddenCount = progress.length + health.length - visible.length
  if (!visible.length) return "暂无待处理项"
  return `${visible.map(([, label, count]) => `${label} ${count}`).join(" · ")}${hiddenCount ? ` · 另 ${hiddenCount} 类` : ""}`
})
const selectionHint = computed(() => selectedIds.value.size < 2 ? `再选 ${2 - selectedIds.value.size} 个即可融合` : "已可开始融合")
const batchLabel = computed(() => {
  const selected = vm.selectedItems.value
  if (selected.length === 1) return sceneContextAction(selected[0]).label
  const kinds = new Set(selected.map((item) => sceneContextAction(item).key))
  if (kinds.size === 1) return ({
    review: "批量采用 / 标记已检查",
    source_mapping: "批量确认章节定位",
    organize: "处理选中整理项",
    suggestion: "逐项处理融合建议",
    assign: "逐项关联章节",
    missing_setup: "逐项补全设定",
    edit: "逐项编辑",
  }[sceneContextAction(selected[0]).key] || "处理选中项")
  return "分组处理"
})

const DETAIL_FIELDS = ["title", "narrative_tag", "status", "source", "goal", "core_conflict", "emotional_beat", "must_happen", "must_not_happen", "pov_character_id"]
const detailDraft = reactive({})
function sceneDraft(scene) {
  return {
    title: scene?.title || "",
    narrative_tag: scene?.narrative_tag || "draft",
    status: scene?.status || "draft",
    source: scene?.source || "manual",
    goal: scene?.goal || "",
    core_conflict: scene?.core_conflict || "",
    emotional_beat: scene?.emotional_beat || "",
    must_happen: scene?.must_happen || "",
    must_not_happen: scene?.must_not_happen || "",
    pov_character_id: scene?.pov_character_id || "",
  }
}
watch(() => selectedItem.value?.scene, (scene) => {
  Object.assign(detailDraft, sceneDraft(scene))
}, { immediate: true })

const detailDirty = computed(() => {
  const baseline = sceneDraft(selectedItem.value?.scene)
  return DETAIL_FIELDS.some((key) => detailDraft[key] !== baseline[key])
})
function confirmDiscardDetail(nextSceneId = null) {
  if (!detailDirty.value || nextSceneId === selectedItem.value?.scene?.id) return true
  return getConfirm()("当前场景有未保存修改，确定放弃并继续吗？")
}
function runAfterDiscard(action) { return confirmDiscardDetail() ? action() : false }
function closeDesktopDetail() {
  const sceneId = selectedItem.value?.scene?.id
  if (!sceneId || !confirmDiscardDetail()) return false
  clearSelectedScene()
  void nextTick(() => document.querySelector(`[data-action="select-workbench-scene"][data-id="${sceneId}"]`)?.focus())
  return true
}
function closeFilterPanel() {
  if (!filterPanel.value) return
  filterPanel.value.open = false
  void nextTick(() => filterPanel.value?.querySelector(":scope > summary")?.focus())
}
async function applyFilters() {
  if (await applyWorkbenchFilters()) closeFilterPanel()
}
async function resetFilters() {
  if (await resetWorkbenchFilters()) closeFilterPanel()
}
function syncAdvancedFilters(event) {
  if (Boolean(event.currentTarget.open) !== advancedFiltersOpen.value) toggleAdvanced()
}
function selectSceneSafely(sceneId) { return confirmDiscardDetail(sceneId) ? selectScene(sceneId) : false }
function runContextActionSafely(item, action = sceneContextAction(item)) {
  if (["missing_setup", "edit"].includes(action.key) && !confirmDiscardDetail(item?.scene?.id)) return false
  return runContextAction(item, action)
}
function openOverlapSafely(sceneId) { return confirmDiscardDetail(sceneId) ? openOverlap(sceneId) : false }
useLeaveGuard(() => (
  !detailDirty.value
  || getConfirm()("当前场景有未保存修改，确定放弃并离开吗？")
))
function warnBeforeUnload(event) {
  if (!detailDirty.value) return
  event.preventDefault()
  event.returnValue = ""
}
window.addEventListener("beforeunload", warnBeforeUnload)
onBeforeUnmount(() => window.removeEventListener("beforeunload", warnBeforeUnload))

let closingMobileDetail = false
async function requestCloseMobileDetail() {
  if (savingSceneId.value || closingMobileDetail) return
  if (detailDirty.value) {
    closingMobileDetail = true
    const confirmed = await confirmAsync("放弃尚未保存的场景修改？", "放弃修改")
    closingMobileDetail = false
    if (!confirmed) return
  }
  clearSelectedScene()
}
const {
  overlayRef: mobileDrawerOverlayRef,
  dialogRef: mobileDrawerDialogRef,
  onKeydown: onMobileDrawerKeydown,
  onFocusin: onMobileDrawerFocusin,
} = useModalDialog({
  isOpen: () => narrow.value && mobileDetailOpen.value && Boolean(selectedItem.value),
  requestClose: requestCloseMobileDetail,
  canClose: () => !savingSceneId.value,
})

const railKey = computed(() => `workspace-rail:${props.projectId}:scene-workbench:detail`)
function storedRailOpen() {
  try { return sessionStorage.getItem(railKey.value) !== "closed" } catch { return true }
}
const railOpen = ref(storedRailOpen())
watch(railKey, () => { railOpen.value = storedRailOpen() })
function onRailToggle(event) {
  railOpen.value = event.target.open
  try { sessionStorage.setItem(railKey.value, event.target.open ? "open" : "closed") } catch {}
}

function createPlannedScene() {
  return showOutlineLayerAiForm("planned_scene", { selectedIds: selectedItem.value?.scene?.id ? [selectedItem.value.scene.id] : [] })
}
function sceneIndex(scene) { return Number.isFinite(Number(scene?.scene_index)) ? Number(scene.scene_index) + 1 : "-" }
function segmentLabel(segment) { return { current: "当前剧情", upcoming: "后续", past: "已写过", unassigned: "未定位" }[segment] || "" }
function firstOverlap(item) { return Array.isArray(item?.overlap_details) ? item.overlap_details[0] : null }
function rowSpanSummary(item) {
  const labels = (item?.span_summaries || []).map(spanSummaryLabel).filter(Boolean)
  if (!labels.length) return ""
  return `${labels.slice(0, 2).join("；")}${labels.length > 2 ? `；另 ${labels.length - 2} 段` : ""}`
}
function rowOverlapSummary(item) {
  const details = item?.overlap_details || []
  if (!details.length) return ""
  const label = details[0].range_label || `与「${overlapCounterpartLabel(details[0])}」的正文范围重叠`
  return `${label}${details.length > 1 ? `；另 ${details.length - 1} 处` : ""}`
}
function menuItems(item) {
  const scene = item.scene
  return [
    { action: "open-writing-scene", label: "打开写作", data: { id: scene.id } },
    { action: "add-scene-task", label: "添加到我的任务", data: { id: scene.id } },
    { action: "start-merge-scene", label: "合并", data: { id: scene.id } },
    { action: "start-split-scene", label: "拆分", data: { id: scene.id } },
    ...(scene.structure_meta?.organize_ignored && !structureAssetDisplay(scene).isHistory ? [{ action: "restore-scene-organize", label: "恢复整理提醒", data: { id: scene.id } }] : []),
    ...(sceneReviewState(item).reviewed ? [{ action: "mark-scene-unreviewed", label: "标记需检查", data: { id: scene.id } }] : []),
    ...(!structureAssetDisplay(scene).isHistory ? [{ action: "move-scene-to-history", label: "移入历史", data: { id: scene.id } }] : []),
  ]
}
function handleMenu(item, menu) {
  if (menu.action === "open-writing-scene") return openWriting(item.scene)
  if (menu.action === "add-scene-task") {
    return router.navigate("writing", null, true, authorTaskPanelQuery({
      kind: "outline_scene",
      id: item.scene.id,
      title: `处理场景：${item.scene.title || "未命名场景"}`,
    }))
  }
  if (menu.action === "start-merge-scene") return modalController.startMerge(item.scene.id)
  if (menu.action === "start-split-scene") return modalController.startSplit(item.scene.id)
  if (menu.action === "restore-scene-organize") return vm.reviewScenes([item.scene.id], "restore_structure")
  if (menu.action === "mark-scene-unreviewed") return vm.reviewScenes([item.scene.id], "reopen")
  if (menu.action === "move-scene-to-history") return vm.moveToHistory(item.scene.id)
}

const SceneDetailPanel = defineComponent({
  props: { projectId: String, item: Object, draft: Object, dirty: Boolean, narrow: Boolean, saving: Boolean, saveError: String },
  emits: ["close", "context", "save", "merge", "split", "replacement"],
  setup(componentProps, { emit }) {
    return () => {
      const item = componentProps.item
      const scene = item.scene
      const review = sceneReviewState(item)
      const reviewLabel = review.reviewed ? `已检查 · ${new Date(review.reviewedAt).toLocaleString("zh-CN")}` : review.needsReview ? "需要人工检查" : "无注意项"
      const action = sceneContextAction(item)
      const secondaryHint = componentProps.saving ? "保存完成后可用" : componentProps.dirty ? "请先保存或放弃当前修改" : ""
      const field = (label, key, type = "input", options = []) => h("label", { class: ["scene-detail-field", type === "textarea" && "scene-detail-field--wide"] }, [
        h("span", label),
        type === "select"
          ? h("select", { id: `scene-detail-${key}`, class: "form-select", disabled: componentProps.saving, value: componentProps.draft[key], onChange: (event) => { componentProps.draft[key] = event.target.value } }, options.map(([value, text]) => h("option", { value }, text)))
          : type === "textarea"
            ? h("textarea", { id: `scene-detail-${key}`, class: "form-textarea", rows: 3, disabled: componentProps.saving, value: componentProps.draft[key], onInput: (event) => { componentProps.draft[key] = event.target.value } })
            : h("input", { id: `scene-detail-${key}`, class: "form-input", disabled: componentProps.saving, value: componentProps.draft[key], onInput: (event) => { componentProps.draft[key] = event.target.value } }),
      ])
      const povField = h("div", {
        class: "scene-detail-field scene-detail-field--wide",
        inert: componentProps.saving || undefined,
        "aria-disabled": componentProps.saving ? "true" : undefined,
      }, [
        h("span", "视角人物"),
        h(ReferencePickerAdapter, {
          id: "scene-detail-pov-character",
          projectId: componentProps.projectId,
          sources: [characterSource],
          modelValue: componentProps.draft.pov_character_id ? [componentProps.draft.pov_character_id] : [],
          placeholder: "按姓名或别名搜索人物",
          emptyText: "没有匹配的人物，可换个姓名或别名再试",
          "onUpdate:modelValue": (ids) => { componentProps.draft.pov_character_id = ids[0] || "" },
        }),
        h("small", { class: "scene-detail-field__hint" }, "用于限定角色所知与正文视角；留空表示未指定。"),
      ])
      return h("div", { class: "scene-detail-panel", "aria-busy": componentProps.saving }, [
        h("div", { class: "scene-detail-panel__head" }, [h("div", [componentProps.narrow ? h("div", { class: "scene-detail-panel__eyebrow" }, "场景详情") : null, h("h3", scene.title || "未命名场景")]), h("button", { type: "button", class: "btn btn-sm btn-text scene-detail-panel__close", disabled: componentProps.saving, "data-action": "close-scene-detail", onClick: () => emit("close") }, "返回列表")]),
        h("fieldset", { class: "scene-detail-section" }, [
          h("legend", "基本信息"),
          h("div", { class: "scene-detail-grid" }, [
            field("标题", "title"), field("叙事标签", "narrative_tag", "select", TAG_OPTIONS), field("状态", "status", "select", STATUS_OPTIONS), field("来源", "source", "select", SOURCE_OPTIONS),
          ]),
        ]),
        h("fieldset", { class: "scene-detail-section" }, [
          h("legend", "创作要点"),
          h("div", { class: "scene-detail-grid" }, [
            field("目标", "goal", "textarea"), field("核心冲突", "core_conflict", "textarea"), field("情感节奏", "emotional_beat", "textarea"), field("必须发生", "must_happen", "textarea"), field("禁止发生", "must_not_happen", "textarea"), povField,
          ]),
        ]),
        h("section", { class: "scene-detail-section scene-detail-summary", "aria-labelledby": "scene-detail-context-title" }, [
          h("h4", { id: "scene-detail-context-title" }, "章节与来源"),
          h("div", [h("strong", "章节映射"), h("span", item.chapter_range || "未关联章节")]),
          h("div", [h("strong", "来源与注意"), h("span", `${sceneSourceLabel(scene)} · ${sceneStatusLabel(scene)} · ${reviewLabel}`)]),
          healthReasons(item).length ? h("div", [h("strong", "待处理"), h("span", healthReasons(item).map((reason) => reason.label).join(" · "))]) : null,
          ...(item.span_summaries || []).map((summary) => h("div", { class: "scene-span-detail" }, [h("strong", "正文范围"), h("span", spanSummaryLabel(summary))])),
          ...(item.overlap_details || []).map((detail) => h("div", { class: "scene-overlap-detail" }, [h("strong", detail.range_label || `与「${overlapCounterpartLabel(detail)}」重叠`), h("button", { class: "btn btn-sm", onClick: () => emit("replacement", detail.counterpart_scene_id) }, `查看「${overlapCounterpartLabel(detail)}」`)])),
        ]),
        componentProps.saveError ? h("p", { class: "scene-detail-save-error", role: "alert" }, `保存失败：${componentProps.saveError}`) : null,
        h("div", { class: "scene-detail-actions" }, [
          h("button", { class: "btn btn-primary", disabled: componentProps.saving || !componentProps.dirty, "data-action": "save-scene-detail", onClick: () => emit("save") }, componentProps.saving ? "保存中..." : componentProps.dirty ? "保存修改" : "已保存"),
          action.key !== "edit" ? h("button", { class: "btn btn-sm", disabled: Boolean(secondaryHint), title: secondaryHint || undefined, onClick: () => emit("context") }, action.label) : null,
          h(ActionMenu, {
            class: "scene-detail-action-menu",
            menuId: `scene-detail-actions-${scene.id}`,
            label: `${scene.title || "未命名场景"}的更多结构操作${secondaryHint ? `，${secondaryHint}` : ""}`,
            triggerText: "更多",
            disabled: Boolean(secondaryHint),
            items: [
              { action: "start-merge-scene", label: "合并场景", data: { id: scene.id } },
              { action: "start-split-scene", label: "拆分场景", data: { id: scene.id } },
            ],
            onSelect: (menu) => menu.action === "start-merge-scene" ? emit("merge") : emit("split"),
          }),
        ]),
      ])
    }
  },
})
</script>
