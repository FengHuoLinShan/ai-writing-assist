<!--
  WorldRelationsTab — 关系列表（canonical）。
  对应 vanilla _renderRelations({reviewOnly:false})（worldView.js:2045-2127）的 Vue 化。
  DOM class/id/data-action 逐节点保留（e2e 与视觉基线契约）。
-->
<template>
  <div>
    <p class="world-list-description">管理世界对象与人物之间的关系。</p>

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
    <div v-if="relationsLoadError && !relations.length" class="error-card" role="alert">
      <strong>关系暂时没有加载出来</strong>
      <p>{{ relationsLoadError }}</p>
      <button class="btn btn-sm" type="button" @click="retryLoad">重新加载</button>
    </div>

    <!-- 空态 -->
    <div v-else-if="!relations.length" class="empty-state">
      <p>{{ session.relationListFilters.q ? "没有找到匹配的关系。" : "还没有建立人物关系。" }}</p>
      <p class="world-text-dim">
        {{ session.relationListFilters.q ? "换个关键词，或清除搜索查看全部。" : "关系网可以帮助你梳理角色之间的恩怨情仇。" }}
      </p>
    </div>

    <!-- 关系列表 -->
    <template v-else>
      <p class="world-review-result-summary" role="status">
        当前结果：{{ relationsTotal }} 条关系
      </p>

      <WorldBulkToolbar
        scope="world-relations"
        :actions="[
          { action: 'review-relations', label: '批量采用', className: 'btn-primary' },
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
          <tr v-for="r in relations" :key="r.id || r.relationship_id" :data-id="r.id || r.relationship_id">
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
            <td class="world-table-cell--dim world-table-cell--ellipsis" data-label="描述">{{ r.description || "未填写" }}</td>
            <td class="world-table-cell--dim" data-label="来源与证据">
              <template v-if="authorEvidencePairs(r).length">
                <div class="world-canonical-evidence">
                  <div v-for="([label, value]) in authorEvidencePairs(r)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
                </div>
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
        :total="relationsTotal"
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
import { computed, ref, watch } from "vue"
import { getRouter, getConfirmAction, getToast } from "../../../bridge/index.js"
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
watch(() => session.relationListFilters.q, (value) => {
  searchQuery.value = value || ""
})

// 注册表同步（供 ops 操作查找）
watch(() => [props.relations, props.reviewTypeCatalog], ([items, reviewTypeCatalog]) => {
  syncRelationsAliasesRegistry({ relations: items, reviewTypeCatalog })
}, { immediate: true, deep: true })

const relationIds = computed(() => (
  props.relations.map((r) => r.id || r.relationship_id).filter(Boolean)
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
  if (newSkip >= props.relationsTotal) return
  filters.skip = newSkip
  navigateRelations(filters)
}

function applySearch() {
  const filters = session.relationListFilters
  filters.q = searchQuery.value.trim()
  filters.skip = 0
  navigateRelations(filters)
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

function onBulkAction(action) {
  const scope = "world-relations"
  const selection = getBulkSelection(scope)
  const items = selectedItemsFrom(props.relations, selection, (r) => r.id || r.relationship_id)
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


</script>
