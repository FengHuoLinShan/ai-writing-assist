<template>
  <div class="map-workspace" :class="{ 'map-workspace-active': mode === 'map', 'is-map-editing': editingState.editing }">
    <div class="view-header map-toolbar">
      <div class="view-header__title">
        <button v-if="mode === 'map'" class="btn btn-sm" data-action="map-overview" @click="returnOverview">← 返回总览</button>
        <span>{{ mode === 'map' ? activeMap?.name || '地图' : '地图' }}</span>
        <span v-if="mode === 'overview'" class="view-header__count">{{ maps.length }} 张 · {{ locations.length }} 个地点</span>
      </div>
      <div v-if="mode === 'overview'" class="view-header__actions">
        <button class="btn btn-sm btn-primary" data-action="map-open-recent" @click="openRecent">打开最近地图</button>
        <button class="btn btn-sm btn-primary" data-action="map-quick-create" @click="quickCreate.open()">快速创建</button>
        <button class="btn btn-sm" data-action="map-create-world" @click="modalController.showCreateWorld()">创建世界地图</button>
        <button class="btn btn-sm" data-action="map-toggle-archived" @click="showArchived = !showArchived">{{ showArchived ? '返回当前地图' : `归档地图 ${archivedMaps.length}` }}</button>
        <input v-model="searchQuery" class="form-input map-overview-search" placeholder="搜索地图或地点" />
      </div>
      <div v-else class="view-header__actions">
        <button class="btn btn-sm btn-primary" data-action="map-quick-create" :disabled="editingState.dirty" @click="quickCreate.open()">快速创建</button>
        <button class="btn btn-sm" data-action="map-visual-history" :disabled="editingState.dirty" @click="showVisualHistory">编辑历史</button>
        <div class="map-view-controls" role="group" aria-label="地图视图"><button v-for="[value, label] in VIEW_MODES" :key="value" class="btn btn-sm map-view-mode" :class="{ 'is-active': viewMode === value }" @click="setViewMode(value)">{{ label }}</button><label class="map-low-motion-toggle"><input type="checkbox" :checked="lowMotion" @change="setLowMotion($event.target.checked)" />低动效</label></div>
        <label v-for="(label, key) in MAP_LAYER_LABELS" :key="key" class="map-layer-toggle"><input type="checkbox" :checked="layers[key]" :disabled="editingState.dirty" @change="setLayer(key, $event.target.checked)" />{{ label }}</label>
      </div>
    </div>

    <div v-if="message" class="alert alert-warning">{{ message }}</div>
    <div v-if="mode === 'overview' && searchResults.length" id="map-search-results"><button v-for="item in searchResults" :key="`${item.type}:${item.id}`" class="btn btn-sm" @click="item.type === 'map' ? openMap(item.id, { viewMode: 'live' }) : openLocation(item.id)">{{ item.name }}</button></div>

    <template v-if="mode === 'overview'">
      <section v-if="showArchived" class="card map-archived-list">
        <h3>归档地图</h3><p class="map-muted-text">归档地图不参与地图树、定位和编辑；恢复会连同其完整子树执行。</p>
        <p v-if="!visibleArchivedMaps.length" class="map-muted-text">暂无归档地图</p>
        <div v-for="map in visibleArchivedMaps" :key="map.id" class="map-archived-row"><span><strong>{{ map.name }}</strong><small>{{ map.map_type }} · {{ map.archived_at ? new Date(map.archived_at).toLocaleString() : '归档时间未知' }}</small></span><button class="btn btn-sm" @click="modalController.showRestore(map.id)">恢复子树</button></div>
        <div class="map-pagination"><button class="btn btn-sm" :disabled="archivedPage === 0" @click="archivedPage--">上一页</button><span>第 {{ archivedPage + 1 }} / {{ archivedPageCount }} 页，共 {{ archivedMaps.length }} 个归档子树</span><button class="btn btn-sm" :disabled="archivedPage + 1 >= archivedPageCount" @click="archivedPage++">下一页</button></div>
      </section>
      <div v-else class="map-overview-grid">
        <section class="card map-enrichment-panel">
          <div class="map-inbox-heading"><div><h3>从既有 Scene 补充地图事实</h3><p>只读取已发布正文和既有 Scene，不重跑深度导入；结果只进入待复核候选。</p></div><span class="badge">人物位置 · 事件地点 · 线路 · 势力</span></div>
          <div class="map-enrichment-controls">
            <label>起始章<input id="map-enrichment-start" v-model="enrichment.state.startChapter" class="form-input" type="number" min="1" :disabled="enrichment.running.value" /></label>
            <label>结束章<input id="map-enrichment-end" v-model="enrichment.state.endChapter" class="form-input" type="number" min="1" placeholder="留空表示最后一章" :disabled="enrichment.running.value" /></label>
            <label class="map-enrichment-quality"><input id="map-enrichment-high-quality" v-model="enrichment.state.highQuality" type="checkbox" :disabled="enrichment.running.value" />双阶段高质量审计</label>
            <button class="btn btn-sm btn-primary" data-action="map-enrichment-start" :disabled="enrichment.running.value" @click="enrichment.submit">{{ enrichment.running.value ? '补充中...' : '确认并开始补充' }}</button>
          </div>
          <p class="map-enrichment-note">高质量模式会先抽取，再独立检查遗漏；未知或歧义地点不会猜测坐标。点击上方按钮即明确授权该项目的本次候选流水线。</p>
          <div v-if="enrichment.state.progress" id="map-enrichment-progress" class="workflow-progress-card" role="status">
            <strong>{{ enrichment.state.progress.label }}</strong><span>{{ enrichment.state.progress.statusLabel }}</span>
            <p>{{ enrichment.state.progress.message }}</p><p v-if="enrichment.state.progress.resultSummary">{{ enrichment.state.progress.resultSummary }}</p>
            <p v-if="enrichment.state.progress.errorMessage" class="alert alert-warning">{{ enrichment.state.progress.errorMessage }}</p>
          </div>
        </section>
        <section class="card map-project-inbox">
          <div class="map-inbox-heading"><div><h3>地图收件箱</h3><p>未分配地图的建议先在这里分流，不会进入任意地图面板。</p></div><span class="badge">{{ inbox.total }} 条</span></div>
          <div class="map-inbox-filters" aria-label="地图收件箱筛选"><select v-model="inbox.filters.dynamicType" class="form-select" aria-label="按动态类型筛选" @change="resetInbox"><option value="">全部类型</option><option value="location">人物/事件位置</option><option value="route_state">线路状态</option><option value="boundary">势力范围</option></select><details class="map-inbox-diagnostic-filter"><summary>诊断筛选</summary><input v-model="inbox.filters.sceneId" class="form-input" aria-label="按 Scene 原始 ID 筛选" placeholder="Scene 原始 ID" @change="resetInbox" /></details><select v-model="inbox.filters.source" class="form-select" aria-label="按来源筛选" @change="resetInbox"><option value="">全部来源</option><option v-for="source in inboxSources" :key="source" :value="source">{{ inboxSourceLabel({ source }) }}</option></select><select v-model="inbox.filters.confidence" class="form-select" aria-label="按置信度筛选" @change="resetInbox"><option value="">全部置信度</option><option value="low">低于 60%</option><option value="high">60% 及以上</option></select><select v-model="inbox.filters.eligibility" class="form-select" aria-label="按字段完整度筛选" @change="resetInbox"><option value="">全部完整度</option><option value="ready">可确认</option><option value="missing">待补全</option></select></div>
          <p v-if="inbox.loading" class="map-muted-text">正在加载地图待处理项...</p><div v-if="inbox.error" class="alert alert-warning map-inbox-error"><span>{{ inbox.error }}</span><button class="btn btn-sm" @click="loadInbox">重试</button></div><p v-if="!inbox.loading && !inboxItems.length" class="map-muted-text">当前筛选下没有未分配建议。</p>
          <div class="map-inbox-list"><article v-for="item in inboxItems" :key="item.id" class="map-inbox-item"><div><strong>{{ item.target_name || proposalTypeLabel(item) }}</strong><div class="map-dynamic-meta">{{ proposalTypeLabel(item) }} · {{ inboxSourceLabel(item) }} · {{ inboxConfidenceLabel(item) }}</div><div class="map-dynamic-meta">{{ inboxTimeLabel(item) }}</div><div class="map-dynamic-source">{{ inboxEvidenceText(item) }}</div><div class="map-dynamic-meta">{{ inboxMissingLabels(item).length ? `待补：${inboxMissingLabels(item).join('、')}` : '字段完整，分配地图后可确认' }}</div></div><div class="map-dynamic-actions"><button class="btn btn-sm btn-primary" @click="modalController.showAssign(item)">分配并继续</button><button class="btn btn-sm" @click="ignoreInbox(item)">忽略</button><button class="btn btn-sm" @click="modalController.copyDiagnostic(item)">复制诊断信息</button></div></article></div>
          <div v-if="inbox.total > 20" class="map-pagination"><button class="btn btn-sm" :disabled="inbox.page === 0" @click="changeInboxPage(-1)">上一页</button><span>{{ inbox.page * 20 + 1 }}–{{ Math.min(inbox.total, inbox.page * 20 + inbox.items.length) }} / {{ inbox.total }}</span><button class="btn btn-sm" :disabled="!inbox.hasMore" @click="changeInboxPage(1)">下一页</button></div>
        </section>
        <section class="card"><h3>最近地图</h3><p>{{ recentMap?.name || '暂无最近地图' }}</p></section>
        <section class="card"><h3>空间总览</h3><p>地图 {{ maps.length }} 张，地点 {{ locations.length }} 个</p></section>
        <section class="card"><h3>地图树</h3><MapTreeNode v-if="mapByParent.get(null)?.length" :items="mapByParent.get(null)" :children="mapByParent" @open="openMap($event.id, { viewMode: 'live' })" @archive="archiveMap" /><p v-else class="map-muted-text">暂无地图</p></section>
        <section class="card"><h3>图层</h3><label v-for="(label, key) in MAP_LAYER_LABELS" :key="key" class="map-layer-toggle"><input type="checkbox" :checked="layers[key]" @change="setLayer(key, $event.target.checked)" />{{ label }}</label></section>
      </div>
    </template>

    <div v-else class="map-workspace-body">
      <main class="map-workspace-main">
        <div v-if="!editingState.editing && semanticBubbles.length" class="map-semantic-band"><div class="map-semantic-bubbles" :class="{ 'is-low-motion': lowMotion }"><button v-for="bubble in semanticBubbles" :key="bubble.itemId" class="map-semantic-bubble" :style="{ left: `${bubble.box.x}px`, top: `${bubble.box.y}px`, width: `${bubble.box.width}px` }" @click="openDynamicItem(bubble.itemId)"><span>{{ bubble.label }}</span></button></div></div>
        <MapViewportAdapter ref="viewport" :context="viewportContext" :timeline-projection="timelineProjection" @mounted="consumePendingObservationEditor" @mount-error="onMountError" />
      </main>
      <details class="workspace-rail map-dynamic-rail workspace-rail--right" :class="{ 'is-map-editing': editingState.editing }" :open="railOpen" @toggle="toggleRail"><summary class="workspace-rail__summary" :aria-label="`${railOpen ? '收起' : '展开'}动态摘要`"><span class="workspace-rail__title">动态摘要</span></summary><div class="workspace-rail__body"><aside class="map-dynamic-panel">
        <p v-if="dynamicSummary.loading" class="map-muted-text">正在加载世界动态...</p><div v-else-if="dynamicSummary.error" class="alert alert-warning">{{ dynamicSummary.error }}</div><p v-else-if="!dynamicSummary.dashboard" class="map-muted-text">暂无世界动态</p>
        <template v-else>
          <template v-if="viewMode === 'dashboard'">
            <div class="map-dynamic-header map-mode-header is-dashboard"><h3>{{ dynamicSummary.dashboard.title || '世界动态总控台' }}</h3><span>{{ candidateCount }} 待处理 · {{ factCount }} 已采用</span><button class="btn btn-sm" :disabled="dynamicSummary.historyLoading" @click="toggleHistory">{{ dynamicSummary.historyLoading ? '加载历史…' : showHistory ? `隐藏历史 ${historyQueue.length}` : historyQueue.length ? `查看历史 ${historyQueue.length}` : '查看历史' }}</button></div>
            <section class="map-dashboard-priority"><div><span>主线危机</span><strong>{{ authorFacingStateText(dynamicSummary.dashboard.first_visual_layer?.main_crisis) || '暂无主线危机' }}</strong></div><div><span>主要对象</span><strong>{{ dynamicSummary.dashboard.first_visual_layer?.main_characters?.join('、') || '暂无焦点对象' }}</strong></div><div><span>最重要风险</span><strong>{{ riskText }}</strong></div></section>
            <MapTimelinePanel :timeline="timeline" :playback="playback" :low-motion="lowMotion" :editing="editingState.editing" @start="startTimeline" @stop="stopTimeline" @step="stepTimeline" @position="setTimelinePosition" @speed="setTimelineSpeed" @candidates="setTimelineCandidates" @track="setTimelineTrack" @retry="loadDynamic({ force: true })" @playback-start="startPlayback" @playback-stop="stopPlayback" @continuity-focus="continuityFocus" @continuity-evidence="continuityEvidence" @continuity-explain="continuityExplain" />
            <SceneMemoryRepairPanel :project-id="projectId" :scene-id="activeSceneId" />
            <section class="map-dynamic-section"><h4>动态队列</h4><p v-if="!activeQueue.length" class="map-muted-text">暂无动态队列</p><article v-for="item in activeQueue.slice(0, 8)" :key="item.item_id || item.id" class="map-dynamic-item" :class="{ 'is-danger': item.risk_level === 'danger', 'is-warning': item.risk_level === 'warning' }" @click="modalController.showDynamicItem(item)"><div class="map-dynamic-title">{{ dynamicTitle(item) }}</div><div class="map-dynamic-meta">{{ item.time_label || '时间未确定' }} · {{ mapAssetDisplay(item).label }}<template v-if="item.confidence != null"> · 置信度 {{ Math.round(item.confidence * 100) }}%</template></div><div class="map-dynamic-source">{{ dynamicSource(item) }}</div><div v-if="item.item_kind === 'observation' && mapAssetDisplay(item).displayState === 'review'" class="map-dynamic-actions"><button class="btn btn-sm btn-primary" @click.stop="confirmObservation(item)">采用</button><button class="btn btn-sm" @click.stop="ignoreObservation(item)">忽略</button></div></article></section>
            <section v-if="showHistory" class="map-dynamic-section map-dynamic-history"><h4>历史记录</h4><p v-if="!historyQueue.length" class="map-muted-text">暂无已忽略、已回滚或已废弃记录</p><article v-for="item in historyQueue.slice(0, 8)" :key="`history:${item.item_id || item.id}`" class="map-dynamic-item" @click="modalController.showDynamicItem(item)"><div class="map-dynamic-title">{{ dynamicTitle(item) }}</div><div class="map-dynamic-meta">{{ item.time_label || '时间未确定' }} · {{ mapAssetDisplay(item).label }}</div><div class="map-dynamic-source">{{ dynamicSource(item) }}</div></article></section>
            <InspectorPanel v-if="dynamicSummary.dashboard.inspector" :inspector="dynamicSummary.dashboard.inspector" />
            <section v-if="dynamicSummary.dashboard.batch_groups?.length" class="map-dynamic-section"><h4>批量修改</h4><div v-for="group in dynamicSummary.dashboard.batch_groups.slice(0, 6)" :key="group.group_key" class="map-batch-row"><span>{{ group.group_label }}</span><strong>{{ group.count }}</strong><small>{{ pendingGroupCount(group) }} 待处理 · {{ group.confirmed_count }} 已采用</small><div class="map-batch-actions"><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'confirm')">采用待处理项</button><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'ignore')">忽略待处理项</button><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'conflict')">标记冲突</button></div></div></section>
          </template>
          <template v-else-if="viewMode === 'live'">
            <div class="map-dynamic-header map-mode-header is-live"><div><h3>活地图</h3><p>{{ activeSceneLabel }} · 只播放已采用事实</p></div><span>{{ factCount }} 已采用</span></div>
            <div class="map-mode-note">待处理候选默认不进入正式状态；需要对照时，可在时间轴中开启“待处理预览”。</div>
            <section class="map-dashboard-priority"><div><span>主线危机</span><strong>{{ authorFacingStateText(dynamicSummary.dashboard.first_visual_layer?.main_crisis) || '暂无主线危机' }}</strong></div><div><span>主要对象</span><strong>{{ dynamicSummary.dashboard.first_visual_layer?.main_characters?.join('、') || '暂无焦点对象' }}</strong></div><div><span>最重要风险</span><strong>{{ riskText }}</strong></div></section>
            <MapTimelinePanel :timeline="timeline" :playback="playback" :low-motion="lowMotion" :editing="editingState.editing" @start="startTimeline" @stop="stopTimeline" @step="stepTimeline" @position="setTimelinePosition" @speed="setTimelineSpeed" @candidates="setTimelineCandidates" @track="setTimelineTrack" @retry="loadDynamic({ force: true })" @playback-start="startPlayback" @playback-stop="stopPlayback" @continuity-focus="continuityFocus" @continuity-evidence="continuityEvidence" @continuity-explain="continuityExplain" />
            <section class="map-dynamic-section map-live-current-facts"><h4>{{ activeSceneLabel }}的地图事实</h4><p v-if="!currentLiveFacts.length" class="map-muted-text">当前时点暂无单独列出的地图事实；时间轴仍可播放前序累计状态。</p><article v-for="item in currentLiveFacts.slice(0, 6)" :key="item.item_id || item.id" class="map-dynamic-item" @click="modalController.showDynamicItem(item)"><div class="map-dynamic-title">{{ dynamicTitle(item) }}</div><div class="map-dynamic-meta">{{ item.time_label || activeSceneLabel }} · 已采用</div><div class="map-dynamic-source">{{ dynamicSource(item) }}</div></article></section>
            <InspectorPanel v-if="lensHasFocus && dynamicSummary.dashboard.inspector" :inspector="dynamicSummary.dashboard.inspector" />
            <p v-if="candidateCount" class="map-mode-footnote">另有 {{ candidateCount }} 条待处理建议，请到“世界动态总控台”集中复核。</p>
          </template>
          <template v-else>
            <div class="map-dynamic-header map-mode-header is-lens"><div><h3>叙事透镜</h3><p>{{ lensHasFocus ? lensTitle : '选择人物、地点、势力或动态，查看其空间上下文与证据' }}</p></div><button v-if="lensHasFocus" class="btn btn-sm" data-action="map-clear-lens-focus" @click="clearLensFocus">清除聚焦</button></div>
            <template v-if="lensHasFocus"><InspectorPanel v-if="dynamicSummary.dashboard.inspector" :inspector="dynamicSummary.dashboard.inspector" /><section class="map-dynamic-section map-lens-context"><h4>上下文时间线</h4><p v-if="!lensContextItems.length" class="map-muted-text">当前对象还没有可展示的时序事实或待处理建议。</p><article v-for="item in lensContextItems.slice(0, 10)" :key="item.item_id || item.id" class="map-dynamic-item" @click="modalController.showDynamicItem(item)"><div class="map-dynamic-title">{{ dynamicTitle(item) }}</div><div class="map-dynamic-meta">{{ item.time_label || '时间未确定' }} · {{ mapAssetDisplay(item).label }}</div><div class="map-dynamic-source">{{ dynamicSource(item) }}</div></article></section><section class="map-dynamic-section map-lens-evidence-summary"><h4>证据与风险</h4><div class="map-inspector-counts"><span>来源证据 {{ dynamicSummary.dashboard.inspector?.source_evidence?.length || 0 }}</span><span>待消歧 {{ dynamicSummary.dashboard.inspector?.conflicts?.length || 0 }}</span><span>关联风险 {{ dynamicSummary.dashboard.first_visual_layer?.top_risks?.length || 0 }}</span></div></section></template>
            <div v-else class="map-lens-empty"><strong>从地图开始聚焦</strong><p>点击地点、人物标记或势力范围，在详情中选择“叙事透镜”；也可以从下列活跃对象开始。</p><div v-if="lensFocusableItems.length" class="map-lens-focus-options"><button v-for="item in lensFocusableItems" :key="item.target_entity_id" class="btn btn-sm" data-action="map-focus-entity" @click="focusEntityInLens(item.target_entity_id)">{{ dynamicTitle(item) }}</button></div><p v-else class="map-muted-text">当前地图尚无带对象标识的动态。</p></div>
          </template>
        </template>
      </aside></div></details>
    </div>
  </div>
  <MapQuickCreateDialog :quick="quickCreate" />
  <MapDynamicEditDialog :editor="dynamicEditor" />
</template>

<script setup>
import { computed, ref } from "vue"
import { authorFacingStateText, mapAssetDisplay } from "../../../shared/assetDisplayState.js"
import { buildMapLayout } from "../../../views/mapLayoutEngine.js"
import { MAP_LAYER_LABELS, inboxConfidenceLabel, inboxEvidenceText, inboxMissingLabels, inboxSourceLabel, inboxTimeLabel, mapSourceText, normalizeEmbeddedSceneLabel, proposalTypeLabel } from "./mapModel.js"
import MapViewportAdapter from "./MapViewportAdapter.vue"
import MapTimelinePanel from "./components/MapTimelinePanel.vue"
import MapTreeNode from "./components/MapTreeNode.vue"
import MapQuickCreateDialog from "./components/MapQuickCreateDialog.vue"
import MapDynamicEditDialog from "./components/MapDynamicEditDialog.vue"
import InspectorPanel from "./components/MapInspectorPanel.vue"
import SceneMemoryRepairPanel from "./components/SceneMemoryRepairPanel.vue"
import { useMapWorkspace } from "./useMapWorkspace.js"

const VIEW_MODES = [["dashboard", "世界动态总控台"], ["live", "活地图"], ["lens", "叙事透镜"]]
const props = defineProps({ projectId: { type: String, required: true }, route: { type: Object, default: () => ({}) }, maps: { type: Array, default: () => [] }, archivedMaps: { type: Array, default: () => [] }, locations: { type: Array, default: () => [] }, inbox: { type: Object, default: () => ({}) } })
const vm = useMapWorkspace(props)
const { activeMap, activeQueue, activeSceneId, activeSceneLabel, archiveMap, archivedMaps, archivedPage, archivedPageCount, batchReview, clearLensFocus, confirmObservation, consumePendingObservationEditor, currentLiveFacts, dynamicEditor, dynamicSummary, editingState, enrichment, focusEntityInLens, historyQueue, ignoreInbox, ignoreObservation, inbox, inboxItems, layers, lensContextItems, lensFocusableItems, lensHasFocus, loadDynamic, loadInbox, locations, lowMotion, mapByParent, maps, message, modalController, mode, openLocation, openMap, openRecent, playback, quickCreate, recentMap, returnOverview, searchQuery, searchResults, setLayer, setLowMotion, setTimelineCandidates, setTimelinePosition, setTimelineTrack, setViewMode, showArchived, showHistory, showVisualHistory, startPlayback, startTimeline, stepTimeline, stopPlayback, stopTimeline, timeline, timelineProjection, toggleHistory, viewMode, viewport, viewportContext, visibleArchivedMaps } = vm
const railOpen = ref(typeof window === "undefined" || window.innerWidth > 1099)
const inboxSources = computed(() => [...new Set(inbox.items.map((item) => item.source || item.source_ref?.source || item.source_ref?.workflow).filter(Boolean))].sort())
const candidateCount = computed(() => activeQueue.value.filter((item) => mapAssetDisplay(item).displayState === "review").length)
const factCount = computed(() => activeQueue.value.filter((item) => item.item_kind === "fact" && !mapAssetDisplay(item).isHistory).length)
const riskText = computed(() => (dynamicSummary.dashboard?.first_visual_layer?.top_risks || []).map(authorFacingStateText).filter(Boolean).join("；") || "暂无高风险")
const lensTitle = computed(() => dynamicSummary.dashboard?.inspector?.title || activeSceneLabel.value || "尚未选择叙事对象")
const semanticBubbles = computed(() => buildMapLayout({ dashboard: dynamicSummary.dashboard || {}, viewport: { width: 720, height: 360 }, viewMode: viewMode.value, focusEntityId: vm.focusEntityId.value, sceneId: timeline.sceneIndex, lowMotion: lowMotion.value }).semanticBubbles || [])
function resetInbox() { inbox.page = 0; void loadInbox() }
function changeInboxPage(delta) { inbox.page = Math.max(0, inbox.page + delta); void loadInbox() }
function pendingGroupCount(group) { return Number(group.pending_count ?? group.review_count ?? group.candidate_count ?? 0) || 0 }
function setTimelineSpeed(value) { timeline.speedMs = Math.max(600, Number(value || 1600)); timeline.playing = false }
function toggleRail(event) { railOpen.value = event.target.open }
function openDynamicItem(id) { const item = activeQueue.value.find((entry) => (entry.item_id || entry.id) === id); if (item) modalController.showDynamicItem(item) }
function dynamicTitle(item) { return normalizeEmbeddedSceneLabel(item?.title || item?.target_name || item?.dynamic_type || "地图事实", item) }
function dynamicSource(item) { return mapSourceText(item?.source_summary || item?.evidence_text || "来源未确定") }
function onMountError(error) { console.error("map viewport mount failed", error) }
function continuityFocus(issue, side) { return vm.continuityFocus?.(issue, side) }
function continuityEvidence(issue) { return vm.continuityEvidence?.(issue) }
function continuityExplain(issue) { return vm.continuityExplain?.(issue) }
</script>
