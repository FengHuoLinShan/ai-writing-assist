<!--
  WorldEntityCollection — 对象表格/卡片集合 + 批量工具条
  （vanilla _renderEntityTable 1447-1523 / _renderEntityCards 1525-1599）。
-->
<template>
  <div>
    <WorldBulkToolbar
      scope="world-objects"
      :actions="bulkActions"
      noun="对象"
      hint="仅作用于当前页选中对象"
      :select-all-ids="visibleIds"
      select-all-label="全选当前页对象"
      @run="$emit('bulk-run', $event)"
    />
    <table v-if="objectViewMode !== 'card'" class="data-table table-card-list world-table--no-top-border">
      <thead>
        <tr>
          <th class="selection-cell"><WorldSelectionInput mode="all" scope="world-objects" :ids="visibleIds" label="全选当前页对象" /></th>
          <th>状态</th>
          <th>类型</th>
          <th>名称</th>
          <th>来源</th>
          <th>注意</th>
          <th>重要度</th>
          <th>摘要</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="entity in entities" :key="idOf(entity)" :data-id="idOf(entity)" class="clickable">
          <td class="selection-cell"><WorldSelectionInput mode="one" scope="world-objects" :id="idOf(entity)" :label="`选择 ${entity.name || '对象'}`" /></td>
          <td data-label="状态"><span class="badge" :class="displayOf(entity).statusClass">{{ displayOf(entity).label }}</span></td>
          <td data-label="类型" class="world-table-cell--type">{{ cardTypeLabel(entity) }}</td>
          <td data-label="名称">{{ entity.name }}<span v-if="showNewBadge" class="badge badge-new">新</span><span v-if="entity.ranking" class="world-ranking-badges" :title="rankingTitle(entity)"><span v-for="label in entity.ranking.labels || []" :key="label" class="badge" :class="label === 'hot' ? 'badge-warning' : 'badge-info'">{{ label === 'hot' ? '近期热点' : '重要' }}</span></span></td>
          <td data-label="来源" class="world-table-cell--muted">{{ sourceText(entity) }}</td>
          <td data-label="注意" :class="needsReview(entity) ? 'world-table-cell--warning' : 'world-table-cell--muted'">{{ displayOf(entity).attentionText }}</td>
          <td data-label="重要度">{{ entity.importance ?? entity.importance_score ?? "-" }}</td>
          <td data-label="摘要" class="world-table-cell--muted world-table-cell--ellipsis">{{ entity.summary || entity.public_info || "-" }}</td>
          <td data-label="操作">
            <div class="row-actions">
              <button v-if="showReviewAction(entity)" class="btn btn-sm btn-primary" data-action="mark-entity-reviewed" :data-id="idOf(entity)" @click="markEntityReviewed(idOf(entity))">标记已检查</button>
              <button class="btn btn-sm btn-primary" data-action="edit-entity" :data-id="idOf(entity)" @click="editEntity(idOf(entity))">{{ canPromote(entity) ? "编辑后采用" : "编辑" }}</button>
              <button v-if="canMerge(entity)" class="btn btn-sm" data-action="merge-entity" :data-id="idOf(entity)" @click="showMergeForm(idOf(entity))">合并</button>
              <ActionMenu :menu-id="`entity-actions-${idOf(entity)}`" :label="`${entity.name || '对象'}的更多操作`" :items="tableMenuItems(entity)" @select="onMenuSelect" />
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="world-object-card-grid">
      <article v-for="entity in entities" :key="idOf(entity)" class="world-object-card" :data-id="idOf(entity)">
        <div class="world-object-card__top">
          <div class="world-object-card__avatar" :style="{ background: entityAvatarColor(entity) }">
            {{ (entity.name || "?").slice(0, 1) }}
          </div>
          <div class="world-object-card__identity">
            <h3>{{ entity.name || "未命名对象" }} <span v-if="showNewBadge" class="badge badge-new">新</span></h3>
            <div class="world-object-card__meta">
              <span>{{ cardTypeLabel(entity) }}</span>
              <span class="badge" :class="displayOf(entity).statusClass">{{ displayOf(entity).label }}</span>
              <span v-if="entity.ranking" class="world-ranking-badges" :title="rankingTitle(entity)"><span v-for="label in entity.ranking.labels || []" :key="label" class="badge" :class="label === 'hot' ? 'badge-warning' : 'badge-info'">{{ label === 'hot' ? '近期热点' : '重要' }}</span></span>
            </div>
          </div>
          <div class="world-object-card__selection">
            <WorldSelectionInput mode="one" scope="world-objects" :id="idOf(entity)" :label="`选择 ${entity.name || '对象'}`" />
          </div>
        </div>
        <p class="world-object-card__summary">{{ entity.summary || entity.public_info || "暂无摘要" }}</p>
        <div class="world-object-card__facts">
          <span>来源：{{ sourceText(entity) }}</span>
          <span v-if="displayOf(entity).attentionReasons.length">注意：{{ displayOf(entity).attentionReasons.join("、") }}</span>
          <span>重要度：{{ entity.importance ?? entity.importance_score ?? "-" }}</span>
          <span v-if="entity.ranking">综合分：{{ entity.ranking.combined_score ?? 0 }} · 近十二章 {{ entity.ranking.recent_12_chapter_occurrences ?? 0 }} 次</span>
        </div>
        <div class="world-object-card__actions">
          <button v-if="showReviewAction(entity)" class="btn btn-sm btn-primary" data-action="mark-entity-reviewed" :data-id="idOf(entity)" @click="markEntityReviewed(idOf(entity))">标记已检查</button>
          <button class="btn btn-sm btn-primary" data-action="edit-entity" :data-id="idOf(entity)" @click="editEntity(idOf(entity))">{{ canPromote(entity) ? "编辑后采用" : "编辑" }}</button>
          <button v-if="canMerge(entity)" class="btn btn-sm" data-action="merge-entity" :data-id="idOf(entity)" @click="showMergeForm(idOf(entity))">合并</button>
          <ActionMenu :menu-id="`entity-card-actions-${idOf(entity)}`" :label="`${entity.name || '对象'}的更多操作`" :items="cardMenuItems(entity)" @select="onMenuSelect" />
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { entityAvatarColor, entityId, entityNeedsReview, isSuggestionShadow } from "../logic/worldEntityHelpers.js"
import {
  deleteEntity,
  editEntity,
  markEntityReviewed,
  promoteEntity,
  showKnowledgeForm,
  showMergeForm,
  showRollbackForm,
} from "../logic/worldEntityOps.js"
import ActionMenu from "../../../components/ActionMenu.vue"
import WorldBulkToolbar from "./WorldBulkToolbar.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  entities: { type: Array, default: () => [] },
  showNewBadge: { type: Boolean, default: false },
  objectViewMode: { type: String, default: "table" },
  displayState: { type: String, default: "active" },
  entityTypes: { type: Array, default: () => [] },
})

defineEmits(["bulk-run"])

const idOf = entityId
const needsReview = entityNeedsReview

const visibleIds = computed(() => props.entities.map((item) => entityId(item)).filter(Boolean))

/** vanilla：display_state=active 时才提供 融合/标记为别名（worldView.js:1513-1516）。 */
const bulkActions = computed(() => [
  ...(props.displayState === "active" ? [
    { action: "fuse-entities", label: "融合", className: "btn-primary" },
    { action: "alias-entities", label: "标记为别名", className: "btn-primary" },
  ] : []),
  { action: "delete-entities", label: "批量删除", className: "btn-danger" },
])

function displayOf(entity) {
  const display = worldAssetDisplay({ ...entity, status: entity.status || "canonical" })
  return {
    label: display.label,
    statusClass: displayStateBadgeClass(display.displayState),
    attentionReasons: display.attentionReasons,
    attentionText: display.attentionReasons.join("、") || "—",
  }
}

function sourceText(entity) {
  return { deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }[entity.source] || entity.source || "-"
}

function cardTypeLabel(entity) {
  return props.entityTypes.find((item) => item.value === entity.entity_type)?.label || entity.entity_type || "-"
}

/** 对应 vanilla _renderRankingBadges 的 title。 */
function rankingTitle(entity) {
  const ranking = entity.ranking || {}
  const last = ranking.last_appearance_chapter == null ? "无近期出场" : `最近第 ${ranking.last_appearance_chapter} 章`
  return `综合分 ${ranking.combined_score ?? 0}；${last}`
}

const canPromote = (entity) => entity.status === "draft" || entity.status === "candidate"
const canMerge = (entity) => !isSuggestionShadow(entity) && canPromote(entity)
const isCharacter = (entity) => entity.entity_type === "character" || entity.entity_type === "character_ref"

/** 对应 vanilla _renderEntityReviewAction。 */
const showReviewAction = (entity) => Boolean(entityId(entity)) && !isSuggestionShadow(entity) && entityNeedsReview(entity)

/** 表格行菜单。 */
function tableMenuItems(entity) {
  const id = entityId(entity)
  return [
    ...(canPromote(entity) ? [{ action: "promote-entity", label: "采用", data: { id } }] : []),
    ...(!isSuggestionShadow(entity) ? [{ action: "rollback-entity", label: "回滚", data: { id } }] : []),
    ...(isCharacter(entity) ? [{ action: "knowledge-entity", label: "知识", data: { id } }] : []),
    { action: "delete-entity", label: isSuggestionShadow(entity) ? "忽略" : "删除", class: "danger", data: { id } },
  ]
}

/** 卡片菜单。 */
function cardMenuItems(entity) {
  const id = entityId(entity)
  return [
    ...(canPromote(entity) ? [{ action: "promote-entity", label: "采用", data: { id } }] : []),
    ...(!isSuggestionShadow(entity) ? [{ action: "rollback-entity", label: "回滚", data: { id } }] : []),
    ...(isCharacter(entity) ? [{ action: "knowledge-entity", label: "知识", data: { id } }] : []),
    { action: "delete-entity", label: isSuggestionShadow(entity) ? "忽略" : "删除", class: "danger", data: { id } },
  ]
}

const MENU_HANDLERS = {
  "promote-entity": (id) => promoteEntity(id),
  "rollback-entity": (id) => showRollbackForm(id),
  "knowledge-entity": (id) => showKnowledgeForm(id),
  "delete-entity": (id) => deleteEntity(id),
}

function onMenuSelect(item) {
  const id = item.data?.id
  if (id) MENU_HANDLERS[item.action]?.(id)
}
</script>
