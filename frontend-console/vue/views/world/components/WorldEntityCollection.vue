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
    <table v-if="objectViewMode !== 'card'" class="data-table table-card-list world-table--no-top-border world-object-table">
      <thead>
        <tr>
          <th class="selection-cell"><WorldSelectionInput mode="all" scope="world-objects" :ids="visibleIds" label="全选当前页对象" /></th>
          <th class="world-object-table__identity">对象</th>
          <th class="world-object-table__overview">资料概览</th>
          <th class="world-object-table__actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="entity in entities" :key="idOf(entity)" :data-id="idOf(entity)" class="clickable">
          <td class="selection-cell"><WorldSelectionInput mode="one" scope="world-objects" :id="idOf(entity)" :label="`选择 ${entity.name || '对象'}`" /></td>
          <td data-label="对象" class="world-object-table__identity">
            <div class="world-object-table__title">
              <strong>{{ entity.name || "未命名对象" }}</strong>
              <span v-if="showNewBadge" class="badge badge-new">新</span>
            </div>
            <div class="world-object-table__meta">
              <span class="world-table-cell--type">{{ cardTypeLabel(entity) }}</span>
              <span class="badge" :class="displayOf(entity).statusClass">{{ displayOf(entity).label }}</span>
              <span v-if="entity.ranking" class="world-ranking-badges" :title="rankingTitle(entity)"><span v-for="label in entity.ranking.labels || []" :key="label" class="badge" :class="label === 'hot' ? 'badge-warning' : 'badge-info'">{{ label === 'hot' ? '近期热点' : '重要' }}</span></span>
            </div>
            <p v-if="displayOf(entity).attentionReasons.length" class="world-object-table__attention">
              需要留意：{{ displayOf(entity).attentionReasons.join("、") }}
            </p>
          </td>
          <td data-label="资料概览" class="world-object-table__overview">
            <p class="world-object-table__summary" :title="entity.summary || entity.public_info || '暂无摘要'">{{ entity.summary || entity.public_info || "暂无摘要" }}</p>
            <div class="world-object-table__facts">
              <span>来源：{{ sourceText(entity) }}</span>
              <span>重要度：{{ importanceText(entity) }}</span>
            </div>
          </td>
          <td data-label="操作" class="world-object-table__actions">
            <div class="row-actions">
              <button v-if="showReviewAction(entity)" class="btn btn-sm btn-primary" data-action="mark-entity-reviewed" :data-id="idOf(entity)" @click="markEntityReviewed(idOf(entity))">标记已检查</button>
              <button class="btn btn-sm btn-primary" data-action="edit-entity" :data-id="idOf(entity)" @click="editEntity(idOf(entity))">{{ canPromote(entity) ? "编辑后采用" : "编辑" }}</button>
              <input :id="imageInputId(entity)" class="sr-only" type="file" accept="image/png,image/jpeg" tabindex="-1" :aria-label="`选择${entity.name || '对象'}图片`" :disabled="isImageUploading(entity)" @click.stop @change.stop="uploadEntityImage(entity, $event)" />
              <span v-if="isImageUploading(entity)" class="world-object-table__upload-status" role="status">图片上传中…</span>
              <ActionMenu :menu-id="`entity-actions-${idOf(entity)}`" :label="`${entity.name || '对象'}的更多操作`" :items="tableMenuItems(entity)" @select="onMenuSelect" />
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="world-object-card-grid">
      <article v-for="entity in entities" :key="idOf(entity)" class="world-object-card" :data-id="idOf(entity)">
        <button class="world-object-card__open" type="button" data-action="open-entity-detail" :data-id="idOf(entity)" :aria-label="`打开${entity.name || '对象'}详情`" @click="openEntityCard(entity)"></button>
        <div class="world-object-card__top">
          <div class="world-object-card__avatar" :class="{ 'world-object-card__avatar--image': thumbnailUrl(entity) }" :style="thumbnailUrl(entity) ? undefined : { background: entityAvatarColor(entity) }">
            <img v-if="thumbnailUrl(entity)" :src="thumbnailUrl(entity)" alt="" @error="onThumbnailError(entity, $event)" />
            <span v-else>{{ (entity.name || "?").slice(0, 1) }}</span>
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
          <span>重要度：{{ importanceText(entity) }}</span>
          <span v-if="entity.ranking">综合分：{{ entity.ranking.combined_score ?? 0 }} · 近十二章 {{ entity.ranking.recent_12_chapter_occurrences ?? 0 }} 次</span>
        </div>
        <div class="world-object-card__actions">
          <button v-if="showReviewAction(entity)" class="btn btn-sm btn-primary" data-action="mark-entity-reviewed" :data-id="idOf(entity)" @click="markEntityReviewed(idOf(entity))">标记已检查</button>
          <input :id="imageInputId(entity)" class="sr-only" type="file" accept="image/png,image/jpeg" tabindex="-1" :aria-label="`选择${entity.name || '对象'}图片`" :disabled="isImageUploading(entity)" @click.stop @change.stop="uploadEntityImage(entity, $event)" />
          <button class="btn btn-sm" data-action="upload-entity-image" :data-id="idOf(entity)" :disabled="isImageUploading(entity)" @click.stop="openImagePicker(entity)">{{ isImageUploading(entity) ? "上传中..." : "上传图片" }}</button>
          <button v-if="canMerge(entity)" class="btn btn-sm" data-action="merge-entity" :data-id="idOf(entity)" @click="showMergeForm(idOf(entity))">合并</button>
          <ActionMenu :menu-id="`entity-card-actions-${idOf(entity)}`" :label="`${entity.name || '对象'}的更多操作`" :items="cardMenuItems(entity)" @select="onMenuSelect" />
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, watch } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { entityAvatarColor, entityId, entityNeedsReview, isSuggestionShadow } from "../logic/worldEntityHelpers.js"
import { getApi, getAppState, getRouter, getToast } from "../../../bridge/index.js"
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
  projectId: { type: String, default: null },
  entities: { type: Array, default: () => [] },
  showNewBadge: { type: Boolean, default: false },
  objectViewMode: { type: String, default: "table" },
  displayState: { type: String, default: "active" },
  entityTypes: { type: Array, default: () => [] },
})

defineEmits(["bulk-run"])

const idOf = entityId

const visibleIds = computed(() => props.entities.map((item) => entityId(item)).filter(Boolean))

const thumbnailUrls = reactive({})
const thumbnailStates = reactive({})
const imagePresence = reactive({})
const uploadingImageIds = reactive({})
const thumbnailRequests = new Map()
const uploadControllers = new Map()
let disposed = false

function entityKey(entityOrId) {
  return String(typeof entityOrId === "object" ? idOf(entityOrId) : entityOrId || "")
}

function currentProjectId() {
  return props.projectId || getAppState()?.currentProjectId || null
}

function hasImage(entity) {
  const id = entityKey(entity)
  return Boolean(imagePresence[id] ?? entity?.has_image)
}

function thumbnailUrl(entity) {
  return thumbnailUrls[entityKey(entity)] || ""
}

function onThumbnailError(entity, event) {
  const id = entityKey(entity)
  if (event?.currentTarget?.src !== thumbnailUrls[id]) return
  releaseThumbnail(id)
  thumbnailStates[id] = "error"
}

function releaseThumbnail(id) {
  const key = entityKey(id)
  thumbnailRequests.get(key)?.controller?.abort()
  thumbnailRequests.delete(key)
  if (thumbnailUrls[key]) URL.revokeObjectURL(thumbnailUrls[key])
  delete thumbnailUrls[key]
  delete thumbnailStates[key]
}

function currentEntityFor(id) {
  const key = entityKey(id)
  return props.entities.find((entity) => entityKey(entity) === key) || null
}

function ownsThumbnailRequest(id, token, projectId) {
  const current = currentEntityFor(id)
  const stateProjectId = getAppState()?.currentProjectId
  return !disposed
    && props.objectViewMode === "card"
    && currentProjectId() === projectId
    && (!stateProjectId || stateProjectId === projectId)
    && thumbnailRequests.get(entityKey(id))?.token === token
    && Boolean(current && hasImage(current))
}

async function loadThumbnail(entity, { force = false } = {}) {
  const id = entityKey(entity)
  const projectId = currentProjectId()
  if (props.objectViewMode !== "card" || !id || !projectId || !hasImage(entity)) return
  if (!force && (thumbnailUrls[id] || thumbnailRequests.has(id) || thumbnailStates[id] === "error")) return

  releaseThumbnail(id)
  const controller = new AbortController()
  const token = {}
  thumbnailRequests.set(id, { controller, token })
  thumbnailStates[id] = "loading"
  try {
    const blob = await getApi().world.fetchEntityImage(
      id,
      projectId,
      "thumbnail",
      { signal: controller.signal },
    )
    if (!ownsThumbnailRequest(id, token, projectId) || !blob) return
    const url = URL.createObjectURL(blob)
    if (!ownsThumbnailRequest(id, token, projectId)) {
      URL.revokeObjectURL(url)
      return
    }
    thumbnailUrls[id] = url
    thumbnailStates[id] = "ready"
  } catch (error) {
    if (ownsThumbnailRequest(id, token, projectId) && !controller.signal.aborted) {
      thumbnailStates[id] = "error"
    }
  } finally {
    if (thumbnailRequests.get(id)?.token === token) thumbnailRequests.delete(id)
  }
}

function syncThumbnails() {
  const desired = new Map()
  if (props.objectViewMode === "card") {
    for (const entity of props.entities) {
      if (hasImage(entity)) desired.set(entityKey(entity), entity)
    }
  }
  const known = new Set([
    ...Object.keys(thumbnailUrls),
    ...Object.keys(thumbnailStates),
    ...thumbnailRequests.keys(),
  ])
  for (const id of known) {
    if (!desired.has(id)) releaseThumbnail(id)
  }
  for (const entity of desired.values()) void loadThumbnail(entity)
}

watch(
  () => [props.entities, props.projectId, props.objectViewMode],
  syncThumbnails,
  { immediate: true, deep: true },
)

function imageInputId(entity) {
  return `world-entity-image-${encodeURIComponent(entityKey(entity))}`
}

function isImageUploading(entity) {
  return Boolean(uploadingImageIds[entityKey(entity)])
}

function openImagePicker(entity) {
  if (isImageUploading(entity)) return
  document.getElementById(imageInputId(entity))?.click()
}

function ownsImageUpload(id, projectId, controller) {
  const stateProjectId = getAppState()?.currentProjectId
  return !disposed
    && uploadControllers.get(entityKey(id)) === controller
    && currentProjectId() === projectId
    && (!stateProjectId || stateProjectId === projectId)
}

async function uploadEntityImage(entity, event) {
  const input = event.target
  const file = input?.files?.[0]
  const id = entityKey(entity)
  const projectId = currentProjectId()
  if (!file || !id || !projectId || isImageUploading(entity)) return

  const controller = new AbortController()
  uploadControllers.set(id, controller)
  uploadingImageIds[id] = true
  try {
    await getApi().world.uploadEntityImage(id, file, projectId, null, { signal: controller.signal })
    if (!ownsImageUpload(id, projectId, controller)) return
    imagePresence[id] = true
    entity.has_image = true
    void loadThumbnail(entity, { force: true })
    getToast()("图片已上传", "success")
    try {
      const refreshed = await getRouter()?.refresh?.()
      if (refreshed === false) throw new Error("列表刷新失败")
    } catch {
      if (ownsImageUpload(id, projectId, controller)) {
        getToast()("图片已上传，但列表刷新失败", "warning")
      }
    }
  } catch (error) {
    if (ownsImageUpload(id, projectId, controller) && !controller.signal.aborted) {
      getToast()(`图片上传失败：${error?.message || "请重试"}`, "error")
    }
  } finally {
    if (uploadControllers.get(id) === controller) uploadControllers.delete(id)
    delete uploadingImageIds[id]
    if (input) input.value = ""
  }
}

function openEntityCard(entity) {
  editEntity(idOf(entity))
}

onBeforeUnmount(() => {
  disposed = true
  for (const id of [...thumbnailRequests.keys(), ...Object.keys(thumbnailUrls)]) releaseThumbnail(id)
  for (const controller of uploadControllers.values()) controller.abort()
  uploadControllers.clear()
})

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
  }
}

function sourceText(entity) {
  return { deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }[entity.source] || "未记录"
}

function importanceText(entity) {
  return entity.importance ?? entity.importance_score ?? "未记录"
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
    ...(!isImageUploading(entity) ? [{ action: "upload-entity-image", label: "上传图片", data: { id } }] : []),
    ...(canMerge(entity) ? [{ action: "merge-entity", label: "合并", data: { id } }] : []),
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
  "upload-entity-image": (id) => openImagePicker(id),
  "merge-entity": (id) => showMergeForm(id),
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
