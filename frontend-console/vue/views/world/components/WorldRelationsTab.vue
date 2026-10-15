<!--
  WorldRelationsTab — 关系列表（canonical）。
  对应 vanilla _renderRelations({reviewOnly:false})（worldView.js:2045-2127）的 Vue 化。
  功能与数据契约保留；DOM 与定位器可随重设计调整。
-->
<template>
  <div>
    <p class="world-list-description">管理世界对象与人物之间的关系。</p>
    <div class="world-relation-validity-filter">
      <label for="world-relation-validity-scene">按 Scene 核对作者有效期</label>
      <select id="world-relation-validity-scene" v-model="validitySceneId" @change="onValiditySceneChanged">
        <option value="">不读取 Story 有效期结果</option>
        <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || `第 ${scene.scene_index ?? '?'} 场` }}</option>
      </select>
      <button v-if="validitySceneId" type="button" class="btn btn-sm" :disabled="validityLoading" @click="loadSceneRelations">{{ validityLoading ? '核对中…' : '重新核对' }}</button>
      <span v-if="sceneResult?.allow_story_override" role="status">剧情覆盖已开启</span>
      <p v-if="validityError" class="error-card" role="alert">{{ validityError }}</p>
    </div>

    <form class="review-search-bar world-canonical-search" role="search" aria-label="查找已采用关系" @submit.prevent="applySearch">
      <label class="world-review-quick-label" for="world-relation-search">查找关系</label>
      <input
        id="world-relation-search"
        v-model="searchQuery"
        class="form-input"
        type="search"
        placeholder="人物、地点、关系或描述"
        autocomplete="off"
      >
      <button class="btn btn-primary" type="submit">查找</button>
      <button v-if="session.relationListFilters.q" class="btn" type="button" @click="clearSearch">清除搜索</button>
    </form>

    <!-- 错误态 -->
    <div v-if="relationsLoadError && !shownRelations.length" class="error-card" role="alert">
      <strong>关系暂时没有加载出来</strong>
      <p>{{ relationsLoadError }}</p>
      <button class="btn btn-sm" type="button" @click="retryLoad">重新加载</button>
    </div>

    <!-- 空态 -->
    <div v-else-if="!shownRelations.length" class="empty-state">
      <p>{{ session.relationListFilters.q ? "没有找到匹配的关系。" : "还没有建立人物关系。" }}</p>
      <p class="world-text-dim">
        {{ session.relationListFilters.q ? "换个关键词，或清除搜索查看全部。" : "关系网可以帮助你梳理角色之间的恩怨情仇。" }}
      </p>
    </div>

    <!-- 关系列表 -->
    <template v-else>
      <p class="world-review-result-summary" role="status">
        当前结果：{{ shownTotal }} 条关系
      </p>

      <WorldBulkToolbar
        scope="world-relations"
        :actions="[
          { action: 'delete-relations', label: '批量删除', className: 'btn-danger' },
        ]"
        noun="关系"
        :select-all-ids="relationIds"
        select-all-label="全选当前关系"
        @run="onBulkAction"
      />

      <table class="data-table table-card-list world-canonical-list">
        <thead>
          <tr>
            <th class="selection-cell">
              <WorldSelectionInput mode="all" scope="world-relations" :ids="relationIds" label="全选当前关系" />
            </th>
            <th>源对象</th>
            <th>关系分类与类型</th>
            <th>目标对象</th>
            <th>状态</th>
            <th>描述</th>
            <th>证据</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
            <tr v-for="r in shownRelations" :key="r.id || r.relationship_id" :data-id="r.id || r.relationship_id">
            <td class="selection-cell">
                <WorldSelectionInput mode="one" scope="world-relations" :id="r.id || r.relationship_id" :label="`选择关系 ${detailTypeLabel(reviewTypeCatalog, 'relation', r.relation_type)}`" />
            </td>
            <td class="world-table-cell--type" data-label="源对象">{{ sourceNameOf(r) }}</td>
            <td data-label="关系分类与类型">
              <span class="badge" :class="r.relation_kind ? 'badge-canonical' : 'badge-candidate'">{{ kindLabel(reviewTypeCatalog, "relation", r.relation_kind) }}</span>
              <div class="world-text-dim">{{ detailTypeLabel(reviewTypeCatalog, "relation", r.relation_type) }}</div>
            </td>
            <td class="world-table-cell--type" data-label="目标对象">{{ targetNameOf(r) }}</td>
            <td data-label="状态"><span class="badge" :class="statusBadgeClass(r)">{{ statusLabelOf(r) }}</span></td>
            <td class="world-table-cell--dim world-table-cell--ellipsis" data-label="描述">
              {{ r.description || "未填写" }}
              <p v-if="r.validity" class="world-text-dim">已设置作者生效范围</p>
                <p v-if="validitySceneId && r.effective_at_cutoff === false && !r.story_override_applied" class="world-relation-validity-result" role="status">该关系在所选 Scene 不处于作者有效期。</p>
                <p v-if="r.validity_conflict || r.validity_gap" class="world-relation-validity-result" role="status">{{ relationValidityLabel(r) }}</p>
            </td>
            <td class="world-table-cell--dim" data-label="来源与证据">
              <template v-if="authorEvidencePairs(r).length">
                <details class="world-canonical-evidence"><summary>查看依据</summary>
                  <div v-for="([label, value]) in authorEvidencePairs(r)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
                </details>
              </template>
              <template v-else>暂无来源说明</template>
              <details v-if="diagnosticEvidencePairs(r).length" class="world-canonical-diagnostics">
                <summary>诊断信息</summary>
                <div class="world-canonical-diagnostics__items">
                  <div v-for="([label, value]) in diagnosticEvidencePairs(r)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
                </div>
              </details>
            </td>
            <td data-label="操作">
              <div class="row-actions">
                <button class="btn btn-sm" data-action="edit-relation" :data-id="r.id || r.relationship_id" @click="onEditRelation(r.id || r.relationship_id)">编辑</button>
                <button class="btn btn-sm btn-danger" data-action="delete-relation" :data-id="r.id || r.relationship_id" @click="onDeleteRelation(r.id || r.relationship_id)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <WorldPager
        :total="shownTotal"
        :skip="session.relationListFilters.skip"
        :limit="session.relationListFilters.limit"
        prev-action="prev-relations-page"
        next-action="next-relations-page"
        @change="onPageChange"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getRouter, getConfirmAction, getToast } from "../../../bridge/index.js"
import { validityGapLabel } from "../logic/validityLabels.js"
import { worldSession as session } from "../worldSession.js"
import { deleteRelation, inlineRelationEvidencePairs as relationEvidencePairs, syncRelationsAliasesRegistry, runCanonicalBulkAction, showRelationReviewEditForm } from "../logic/worldRelationsAliasesOps.js"
import { selectedItemsFrom, getBulkSelection, reconcileBulkSelection } from "../logic/worldBulkSelection.js"
import { reviewQueryFromState } from "../logic/worldQuery.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { detailTypeLabel, kindLabel } from "../logic/worldTypeCatalog.js"
import WorldBulkToolbar from "./WorldBulkToolbar.vue"
import WorldPager from "./WorldPager.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  relations: { type: Array, default: () => [] },
  relationsTotal: { type: Number, default: 0 },
  relationsLoadError: { type: String, default: null },
  entityTypes: { type: Array, default: () => [] },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
})

const searchQuery = ref(session.relationListFilters.q || "")
const scenes = ref([])
const validitySceneId = ref("")
const validityLoading = ref(false)
const validityError = ref("")
const sceneResult = ref(null)
let validityRequest = 0
let scenesRequest = 0
const shownRelations = computed(() => validitySceneId.value ? (sceneResult.value?.items || []) : props.relations)
const shownTotal = computed(() => validitySceneId.value ? (sceneResult.value?.total ?? 0) : props.relationsTotal)
watch(() => session.relationListFilters.q, (value) => {
  searchQuery.value = value || ""
})

// 注册表同步（供 ops 操作查找）
watch(() => [shownRelations.value, props.reviewTypeCatalog], ([items, reviewTypeCatalog]) => {
  syncRelationsAliasesRegistry({ relations: items, reviewTypeCatalog })
}, { immediate: true, deep: true })

const relationIds = computed(() => (
  shownRelations.value.map((r) => r.id || r.relationship_id).filter(Boolean)
))
watch(relationIds, (ids) => reconcileBulkSelection("world-relations", ids), { immediate: true })

function sourceNameOf(r) {
  return r.source_name || r.source_entity_name || r.source?.name || "未命名对象"
}

function targetNameOf(r) {
  return r.target_name || r.target_entity_name || r.target?.name || "未命名对象"
}

function relationReviewMeta(r) {
  return r.review_meta && typeof r.review_meta === "object" ? r.review_meta : {}
}

function authorEvidencePairs(r) {
  const meta = relationReviewMeta(r)
  const hasSceneIndex = meta.scene_index != null || r.scene_index != null
  const hasChapterIndex = meta.source_chapter_index != null || r.source_chapter_index != null
  return relationEvidencePairs(r).filter(([label]) => (
    label !== "处理批次"
    && (label !== "场景" || hasSceneIndex)
    && (label !== "章节" || hasChapterIndex)
  ))
}

function diagnosticEvidencePairs(r) {
  const meta = relationReviewMeta(r)
  const hasSceneIndex = meta.scene_index != null || r.scene_index != null
  const hasChapterIndex = meta.source_chapter_index != null || r.source_chapter_index != null
  return [
    ["处理批次", meta.workflow_id || r.workflow_id],
    ["场景标识", hasSceneIndex ? "" : (meta.scene_id || r.scene_id)],
    ["章节标识", hasChapterIndex ? "" : (meta.source_chapter_id || r.source_chapter_id)],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

function statusLabelOf(r) {
  const display = worldAssetDisplay({ ...r, status: r.status || "canonical" })
  return display.label
}

function statusBadgeClass(r) {
  const display = worldAssetDisplay({ ...r, status: r.status || "canonical" })
  return displayStateBadgeClass(display.displayState)
}

function relationValidityLabel(relation) {
  if (relation.story_override_applied) return "可信的同一关系状态观察已覆盖作者有效期。"
  if (relation.validity_conflict) return "Story 关系观察与作者有效期冲突；当前按作者有效期读取。"
  return validityGapLabel(relation.validity_gap)
}

function onDeleteRelation(id) {
  deleteRelation(id)
}

function onEditRelation(id) {
  showRelationReviewEditForm(id)
}

function onPageChange(delta) {
  const filters = session.relationListFilters
  const newSkip = filters.skip + delta * filters.limit
  if (newSkip < 0) return
  if (newSkip >= shownTotal.value) return
  filters.skip = newSkip
  if (validitySceneId.value) void loadSceneRelations()
  else navigateRelations(filters)
}

function applySearch() {
  const filters = session.relationListFilters
  filters.q = searchQuery.value.trim()
  filters.skip = 0
  if (validitySceneId.value) void loadSceneRelations()
  else navigateRelations(filters)
}

function clearSearch() {
  searchQuery.value = ""
  applySearch()
}

function navigateRelations(filters) {
  getRouter()?.navigate?.("world", "relations", true, reviewQueryFromState(filters, ["q"]))
}

function retryLoad() {
  getRouter()?.refresh?.()
}

async function loadScenes(projectId = props.projectId) {
  if (!projectId) return
  const requestId = ++scenesRequest
  try {
    const result = await getApi().outline.listScenesOrdered(projectId)
    if (projectId !== props.projectId || requestId !== scenesRequest) return
    scenes.value = Array.isArray(result) ? result : result?.items || []
  } catch (error) {
    if (projectId === props.projectId && requestId === scenesRequest) validityError.value = error?.message || "Scene 列表暂时无法读取。"
  }
}

async function loadSceneRelations() {
  if (!props.projectId || !validitySceneId.value) return
  const projectId = props.projectId
  const sceneId = validitySceneId.value
  const requestId = ++validityRequest
  validityLoading.value = true
  validityError.value = ""
  try {
    const filters = session.relationListFilters
    const result = await getApi().world.listRelationships({
      novel_id: projectId,
      as_of_scene_id: sceneId,
      status: filters.status || undefined,
      relation_type: filters.relation_type || undefined,
      relation_kind: filters.relation_kind || undefined,
      q: filters.q || undefined,
      source_chapter_id: filters.source_chapter_id || undefined,
      strength_min: filters.strength_min ?? undefined,
      strength_max: filters.strength_max ?? undefined,
      skip: filters.skip || 0,
      limit: filters.limit || 50,
    })
    if (projectId !== props.projectId || sceneId !== validitySceneId.value || requestId !== validityRequest) return
    sceneResult.value = result
  } catch (error) {
    if (projectId === props.projectId && sceneId === validitySceneId.value && requestId === validityRequest) {
      validityError.value = error?.message || "关系有效期暂时无法核对。"
    }
  } finally {
    if (projectId === props.projectId && sceneId === validitySceneId.value && requestId === validityRequest) validityLoading.value = false
  }
}

function onValiditySceneChanged() {
  validityRequest += 1
  validityError.value = ""
  if (!validitySceneId.value) {
    sceneResult.value = null
    validityLoading.value = false
    return
  }
  sceneResult.value = null
  void loadSceneRelations()
}

function onBulkAction(action) {
  const scope = "world-relations"
  const selection = getBulkSelection(scope)
  const items = selectedItemsFrom(shownRelations.value, selection, (r) => r.id || r.relationship_id)
  if (!items.length) {
    getToast()("请先选择要处理的项目", "warning")
    return
  }
  if (action === "review-relations" && items.some((item) => !item.relation_kind)) {
    getToast()("所选关系中有待分类项，请先选择关系分类", "warning")
    return
  }
  const labelByAction = { "review-relations": "批量采用", "delete-relations": "批量删除" }
  const danger = action.includes("delete")
  getConfirmAction()(
    `确定对选中的 ${items.length} 项执行「${labelByAction[action] || action}」吗？`,
    async () => {
      await runCanonicalBulkAction(scope, action, items)
    },
    danger ? "确认执行" : "确认",
  )
}

watch(() => props.projectId, (projectId) => {
  scenesRequest += 1
  validityRequest += 1
  validitySceneId.value = ""
  scenes.value = []
  sceneResult.value = null
  validityError.value = ""
  validityLoading.value = false
  if (projectId) void loadScenes(projectId)
}, { immediate: true })
watch(() => props.relations, () => {
  if (validitySceneId.value) void loadSceneRelations()
  else sceneResult.value = null
}, { deep: true })
onBeforeUnmount(() => { validityRequest += 1 })


</script>

<style scoped>
.world-relation-validity-filter {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 12px;
}

.world-relation-validity-filter label {
  color: var(--text-secondary);
  font-size: 12px;
}

.world-relation-validity-filter select {
  min-width: min(260px, 100%);
  max-width: 100%;
}

.world-relation-validity-filter p {
  flex-basis: 100%;
  margin: 0;
}

.world-relation-validity-result {
  margin: 4px 0 0;
  color: var(--warning, #8a5b00);
  white-space: normal;
}
</style>
