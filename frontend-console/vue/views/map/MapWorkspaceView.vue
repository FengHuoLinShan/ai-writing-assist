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
        <div class="map-view-controls" role="group" aria-label="地图视图"><button v-for="[value, label] in VIEW_MODES" :key="value" class="btn btn-sm map-view-mode" :class="{ 'is-active': viewMode === value }" :disabled="editingState.dirty" @click="setViewMode(value)">{{ label }}</button><label class="map-low-motion-toggle"><input type="checkbox" :checked="lowMotion" :disabled="editingState.dirty" @change="setLowMotion($event.target.checked)" />低动效</label></div>
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
        <template v-else><div class="map-dynamic-header"><h3>{{ dynamicSummary.dashboard.title || '世界动态总控台' }}</h3><span>{{ candidateCount }} 待处理 · {{ factCount }} 已采用</span><button class="btn btn-sm" :disabled="dynamicSummary.historyLoading" @click="toggleHistory">{{ dynamicSummary.historyLoading ? '加载历史…' : showHistory ? '隐藏历史' : '查看历史' }}</button></div>
          <section class="map-dashboard-priority"><div><span>主线危机</span><strong>{{ authorFacingStateText(dynamicSummary.dashboard.first_visual_layer?.main_crisis) || '暂无主线危机' }}</strong></div><div><span>主要对象</span><strong>{{ dynamicSummary.dashboard.first_visual_layer?.main_characters?.join('、') || '暂无焦点对象' }}</strong></div><div><span>最重要风险</span><strong>{{ riskText }}</strong></div></section>
          <MapTimelinePanel :timeline="timeline" :playback="playback" :low-motion="lowMotion" :editing="editingState.editing" @start="startTimeline" @stop="stopTimeline" @step="stepTimeline" @position="setTimelinePosition" @speed="setTimelineSpeed" @candidates="setTimelineCandidates" @track="setTimelineTrack" @retry="loadDynamic({ force: true })" @playback-start="startPlayback" @playback-stop="stopPlayback" @continuity-focus="continuityFocus" @continuity-evidence="continuityEvidence" @continuity-explain="continuityExplain" />
          <section class="map-dynamic-section"><h4>动态队列</h4><p v-if="!activeQueue.length" class="map-muted-text">暂无动态队列</p><article v-for="item in activeQueue.slice(0, 8)" :key="item.item_id || item.id" class="map-dynamic-item" :class="{ 'is-danger': item.risk_level === 'danger', 'is-warning': item.risk_level === 'warning' }" @click="modalController.showDynamicItem(item)"><div class="map-dynamic-title">{{ item.title || '地图事实' }}</div><div class="map-dynamic-meta">{{ item.time_label || '时间未确定' }} · {{ mapAssetDisplay(item).label }}<template v-if="item.confidence != null"> · 置信度 {{ Math.round(item.confidence * 100) }}%</template></div><div class="map-dynamic-source">{{ item.source_summary || '来源未确定' }}</div><div v-if="item.item_kind === 'observation' && mapAssetDisplay(item).displayState === 'review'" class="map-dynamic-actions"><button class="btn btn-sm btn-primary" @click.stop="confirmObservation(item)">采用</button><button class="btn btn-sm" @click.stop="ignoreObservation(item)">忽略</button></div></article></section>
          <section v-if="dynamicSummary.dashboard.inspector" class="map-dynamic-section map-inspector"><h4>检查器</h4><article class="map-dynamic-item"><div class="map-dynamic-title">{{ dynamicSummary.dashboard.inspector.title || '暂无世界动态' }}</div><div class="map-dynamic-meta">{{ [dynamicSummary.dashboard.inspector.type_label, dynamicSummary.dashboard.inspector.location_label, dynamicSummary.dashboard.inspector.spatial_anchor_label].filter(Boolean).join(' · ') }}</div><div class="map-dynamic-source">{{ dynamicSummary.dashboard.inspector.summary }}</div><ul v-if="dynamicSummary.dashboard.inspector.source_evidence?.length" class="map-evidence-list"><li v-for="text in dynamicSummary.dashboard.inspector.source_evidence.slice(0, 3)" :key="text">{{ text }}</li></ul></article></section>
          <section v-if="dynamicSummary.dashboard.batch_groups?.length" class="map-dynamic-section"><h4>批量修改</h4><div v-for="group in dynamicSummary.dashboard.batch_groups.slice(0, 6)" :key="group.group_key" class="map-batch-row"><span>{{ group.group_label }}</span><strong>{{ group.count }}</strong><small>{{ pendingGroupCount(group) }} 待处理 · {{ group.confirmed_count }} 已采用</small><div class="map-batch-actions"><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'confirm')">采用待处理项</button><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'ignore')">忽略待处理项</button><button class="btn btn-sm" :disabled="!pendingGroupCount(group)" @click="batchReview(group, 'conflict')">标记冲突</button></div></div></section>
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
import { MAP_LAYER_LABELS, inboxConfidenceLabel, inboxEvidenceText, inboxMissingLabels, inboxSourceLabel, inboxTimeLabel, proposalTypeLabel } from "./mapModel.js"
import MapViewportAdapter from "./MapViewportAdapter.vue"
import MapTimelinePanel from "./components/MapTimelinePanel.vue"
import MapTreeNode from "./components/MapTreeNode.vue"
import MapQuickCreateDialog from "./components/MapQuickCreateDialog.vue"
import MapDynamicEditDialog from "./components/MapDynamicEditDialog.vue"
import { useMapWorkspace } from "./useMapWorkspace.js"

const VIEW_MODES = [["dashboard", "世界动态总控台"], ["live", "活地图"], ["lens", "叙事透镜"]]
const props = defineProps({ projectId: { type: String, required: true }, route: { type: Object, default: () => ({}) }, maps: { type: Array, default: () => [] }, archivedMaps: { type: Array, default: () => [] }, locations: { type: Array, default: () => [] }, inbox: { type: Object, default: () => ({}) } })
const vm = useMapWorkspace(props)
const { activeMap, activeQueue, archiveMap, archivedMaps, archivedPage, archivedPageCount, batchReview, confirmObservation, consumePendingObservationEditor, dynamicEditor, dynamicSummary, editingState, ignoreInbox, ignoreObservation, inbox, inboxItems, layers, loadDynamic, loadInbox, locations, lowMotion, mapByParent, maps, message, modalController, mode, openLocation, openMap, openRecent, playback, quickCreate, recentMap, returnOverview, searchQuery, searchResults, setLayer, setLowMotion, setTimelineCandidates, setTimelinePosition, setTimelineTrack, setViewMode, showArchived, showHistory, startPlayback, startTimeline, stepTimeline, stopPlayback, stopTimeline, timeline, timelineProjection, toggleHistory, viewMode, viewport, viewportContext, visibleArchivedMaps } = vm
const railOpen = ref(typeof window === "undefined" || window.innerWidth > 1099)
const inboxSources = computed(() => [...new Set(inbox.items.map((item) => item.source || item.source_ref?.source || item.source_ref?.workflow).filter(Boolean))].sort())
const candidateCount = computed(() => activeQueue.value.filter((item) => mapAssetDisplay(item).displayState === "review").length)
const factCount = computed(() => activeQueue.value.filter((item) => item.item_kind === "fact" && !mapAssetDisplay(item).isHistory).length)
const riskText = computed(() => (dynamicSummary.dashboard?.first_visual_layer?.top_risks || []).map(authorFacingStateText).filter(Boolean).join("；") || "暂无高风险")
const semanticBubbles = computed(() => buildMapLayout({ dashboard: dynamicSummary.dashboard || {}, viewport: { width: 720, height: 360 }, viewMode: viewMode.value, focusEntityId: vm.focusEntityId.value, sceneId: timeline.sceneIndex, lowMotion: lowMotion.value }).semanticBubbles || [])
function resetInbox() { inbox.page = 0; void loadInbox() }
function changeInboxPage(delta) { inbox.page = Math.max(0, inbox.page + delta); void loadInbox() }
function pendingGroupCount(group) { return Number(group.pending_count ?? group.review_count ?? group.candidate_count ?? 0) || 0 }
function setTimelineSpeed(value) { timeline.speedMs = Math.max(600, Number(value || 1600)); timeline.playing = false }
function toggleRail(event) { railOpen.value = event.target.open }
function openDynamicItem(id) { const item = activeQueue.value.find((entry) => (entry.item_id || entry.id) === id); if (item) modalController.showDynamicItem(item) }
function onMountError(error) { console.error("map viewport mount failed", error) }
function continuityFocus(issue, side) { return vm.continuityFocus?.(issue, side) }
function continuityEvidence(issue) { return vm.continuityEvidence?.(issue) }
function continuityExplain(issue) { return vm.continuityExplain?.(issue) }
</script>
