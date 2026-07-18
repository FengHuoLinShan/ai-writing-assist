<!--
  WorldRelationsTab — 关系列表（canonical）。
  对应 vanilla _renderRelations({reviewOnly:false})（worldView.js:2045-2127）的 Vue 化。
  DOM class/id/data-action 逐节点保留（e2e 与视觉基线契约）。
-->
<template>
  <div>
    <p class="world-list-description">管理世界对象与人物之间的关系。</p>

    <!-- 错误态 -->
    <div v-if="relationsLoadError && !relations.length" class="empty-state">
      <p>{{ relationsLoadError }}</p>
    </div>

    <!-- 空态 -->
    <div v-else-if="!relations.length" class="empty-state">
      <p>还没有建立人物关系。</p>
      <p class="world-text-dim">关系网可以帮助你梳理角色之间的恩怨情仇。</p>
    </div>

    <!-- 关系列表 -->
    <template v-else>
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

      <table class="data-table">
        <thead>
          <tr>
            <th class="selection-cell">
              <WorldSelectionInput mode="all" scope="world-relations" :ids="relationIds" label="全选当前关系" />
            </th>
            <th>源对象</th>
            <th>关系类型</th>
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
              <WorldSelectionInput mode="one" scope="world-relations" :id="r.id || r.relationship_id" :label="`选择关系 ${r.relation_type || ''}`" />
            </td>
            <td class="world-table-cell--type">{{ sourceNameOf(r) }}</td>
            <td><span class="badge badge-canonical">{{ r.relation_type || "-" }}</span></td>
            <td class="world-table-cell--type">{{ targetNameOf(r) }}</td>
            <td><span class="badge" :class="statusBadgeClass(r)">{{ statusLabelOf(r) }}</span></td>
            <td class="world-table-cell--dim world-table-cell--ellipsis">{{ r.description || "" }}</td>
            <td class="world-table-cell--dim">
              <template v-if="relationEvidencePairs(r).length">
                <div v-for="([label, value]) in relationEvidencePairs(r)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
              </template>
              <template v-else>-</template>
            </td>
            <td>
              <div class="row-actions">
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
import { computed, watch } from "vue"
import { getRouter, getConfirmAction, getToast } from "../../../bridge/index.js"
import { worldSession as session } from "../worldSession.js"
import { deleteRelation, inlineRelationEvidencePairs as relationEvidencePairs, syncRelationsAliasesRegistry, runCanonicalBulkAction } from "../logic/worldRelationsAliasesOps.js"
import { selectedItemsFrom, getBulkSelection } from "../logic/worldBulkSelection.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
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

// 注册表同步（供 ops 操作查找）
watch(() => props.relations, (items) => {
  syncRelationsAliasesRegistry({ relations: items })
}, { immediate: true, deep: true })

const relationIds = computed(() => (
  props.relations.map((r) => r.id || r.relationship_id).filter(Boolean)
))

function sourceNameOf(r) {
  return r.source_name || r.source_entity_name || r.source?.name || (r.source_id ? `${String(r.source_id).slice(0, 8)}...` : "-")
}

function targetNameOf(r) {
  return r.target_name || r.target_entity_name || r.target?.name || (r.target_id ? `${String(r.target_id).slice(0, 8)}...` : "-")
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

function onPageChange(delta) {
  const filters = session.relationListFilters
  const newSkip = filters.skip + delta * filters.limit
  if (newSkip < 0) return
  if (newSkip >= props.relationsTotal) return
  filters.skip = newSkip
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
