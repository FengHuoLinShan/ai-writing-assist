<!--
  WorldAliasesTab — 别名列表（canonical）。
  对应 vanilla _renderAliases({reviewOnly:false})（worldView.js:2668-2763）的 Vue 化。
  别名按所属对象分组，同一对象的别名共享同一行（rowspan）。
  DOM class/id/data-action 逐节点保留（e2e 与视觉基线契约）。
-->
<template>
  <div>
    <p class="world-list-description">管理世界对象的别名、称号和化名。别名不独立创建对象。</p>

    <form class="review-search-bar world-canonical-search" role="search" aria-label="查找已采用别名" @submit.prevent="applySearch">
      <label class="world-review-quick-label" for="world-alias-search">查找别名</label>
      <input
        id="world-alias-search"
        v-model="searchQuery"
        class="form-input"
        type="search"
        placeholder="别名、所属对象或引用"
        autocomplete="off"
      >
      <button class="btn btn-primary" type="submit">查找</button>
      <button v-if="session.aliasListFilters.q" class="btn" type="button" @click="clearSearch">清除搜索</button>
    </form>

    <!-- 错误态 -->
    <div v-if="aliasesLoadError && !aliases.length" class="error-card" role="alert">
      <strong>别名暂时没有加载出来</strong>
      <p>{{ aliasesLoadError }}</p>
      <button class="btn btn-sm" type="button" @click="retryLoad">重新加载</button>
    </div>

    <!-- 空态 -->
    <div v-else-if="!aliases.length" class="empty-state">
      <p>{{ session.aliasListFilters.q ? "没有找到匹配的别名。" : "还没有设置别名。" }}</p>
      <p class="world-text-dim">
        {{ session.aliasListFilters.q ? "换个关键词，或清除搜索查看全部。" : "别名可以帮助你管理角色的化名、称号和绰号。" }}
      </p>
    </div>

    <!-- 别名列表 -->
    <template v-else>
      <p class="world-review-result-summary" role="status">
        当前结果：{{ aliasesTotal }} 个别名
      </p>

      <WorldBulkToolbar
        scope="world-aliases"
        :actions="[
          { action: 'review-aliases', label: '批量采用', className: 'btn-primary' },
          { action: 'delete-aliases', label: '批量删除', className: 'btn-danger' },
        ]"
        noun="别名"
        :select-all-ids="aliasIds"
        select-all-label="全选当前别名"
        @run="onBulkAction"
      />

      <table class="data-table table-card-list world-canonical-list world-alias-list">
        <thead>
          <tr>
            <th class="selection-cell">
              <WorldSelectionInput mode="all" scope="world-aliases" :ids="aliasIds" label="全选当前别名" />
            </th>
            <th>对象</th>
            <th>别名</th>
            <th>分类与类型</th>
            <th>状态</th>
            <th>来源</th>
            <th>置信度</th>
            <th>证据</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in aliasGroups" :key="group.entityKey">
            <tr v-for="(a, index) in group.aliases" :key="aliasKeyOf(a)" :data-id="aliasKeyOf(a)">
              <td class="selection-cell">
                <WorldSelectionInput mode="one" scope="world-aliases" :id="aliasKeyOf(a)" :label="`选择别名 ${a.alias || ''}`" />
              </td>
              <td
                v-if="index === 0"
                :rowspan="group.aliases.length"
                class="world-table-cell--type world-alias-group-cell"
                data-label="对象"
              >
                <div>{{ group.entityName }}</div>
                <div v-if="group.aliases.length > 1" class="world-text-dim world-alias-group-count">{{ group.aliases.length }} 个别名</div>
              </td>
              <td class="world-alias-mobile-entity" data-label="对象">{{ group.entityName }}</td>
              <td data-label="别名">{{ a.alias || "未填写" }}</td>
              <td data-label="分类与类型">
                <span class="badge" :class="a.alias_kind ? 'badge-canonical' : 'badge-candidate'">{{ kindLabel(reviewTypeCatalog, "alias", a.alias_kind) }}</span>
                <div class="world-text-dim">{{ detailTypeLabel(reviewTypeCatalog, "alias", a.alias_type) }}</div>
              </td>
              <td data-label="状态"><span class="badge" :class="statusBadgeClassOf(a)">{{ statusLabelOf(a) }}</span></td>
              <td class="world-table-cell--muted" data-label="来源">{{ sourceLabelOf(a) }}</td>
              <td data-label="置信度">{{ confidenceLabelOf(a) }}</td>
              <td class="world-table-cell--dim" data-label="来源与证据">
                <template v-if="authorEvidencePairs(a).length">
                  <div class="world-canonical-evidence">
                    <div v-for="([label, value]) in authorEvidencePairs(a)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
                  </div>
                </template>
                <template v-else>暂无引用说明</template>
                <details v-if="diagnosticEvidencePairs(a).length" class="world-canonical-diagnostics">
                  <summary>诊断信息</summary>
                  <div class="world-canonical-diagnostics__items">
                    <div v-for="([label, value]) in diagnosticEvidencePairs(a)" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
                  </div>
                </details>
              </td>
              <td data-label="操作">
                <div class="row-actions">
                  <span v-if="a.managed_by_suggestion" class="world-text-dim">随对象建议处理</span>
                  <template v-else>
                    <button class="btn btn-sm" data-action="edit-alias" :data-entity-id="a.entity_id" :data-alias="a.alias" @click="onEditAlias(a.entity_id, a.alias)">编辑</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-alias" :data-entity-id="a.entity_id" :data-alias="a.alias" @click="onDeleteAlias(a.entity_id, a.alias)">删除</button>
                  </template>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <WorldPager
        :total="aliasesTotal"
        :skip="session.aliasListFilters.skip"
        :limit="session.aliasListFilters.limit"
        prev-action="prev-aliases-page"
        next-action="next-aliases-page"
        @change="onPageChange"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { getRouter, getConfirmAction, getToast } from "../../../bridge/index.js"
import { worldSession as session } from "../worldSession.js"
import { deleteAlias, syncRelationsAliasesRegistry, runCanonicalBulkAction, aliasKey, showAliasEditForm } from "../logic/worldRelationsAliasesOps.js"
import { selectedItemsFrom, getBulkSelection, reconcileBulkSelection } from "../logic/worldBulkSelection.js"
import { reviewQueryFromState } from "../logic/worldQuery.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { detailTypeLabel, kindLabel } from "../logic/worldTypeCatalog.js"
import WorldBulkToolbar from "./WorldBulkToolbar.vue"
import WorldPager from "./WorldPager.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  aliases: { type: Array, default: () => [] },
  aliasesTotal: { type: Number, default: 0 },
  aliasesLoadError: { type: String, default: null },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
})

const searchQuery = ref(session.aliasListFilters.q || "")
watch(() => session.aliasListFilters.q, (value) => {
  searchQuery.value = value || ""
})

// 注册表同步
watch(() => [props.aliases, props.reviewTypeCatalog], ([items, reviewTypeCatalog]) => {
  syncRelationsAliasesRegistry({ aliases: items, reviewTypeCatalog })
}, { immediate: true, deep: true })

// ---- 别名分组（对应 vanilla _groupAliasesByEntity） ----
const aliasGroups = computed(() => {
  const groups = []
  const byEntity = new Map()
  for (const alias of props.aliases || []) {
    const entityKey = alias.entity_id || alias.entity_name || "__unknown__"
    let group = byEntity.get(entityKey)
    if (!group) {
      group = {
        entityKey,
        entityId: alias.entity_id || "",
        entityName: alias.entity_name || "未知对象",
        aliases: [],
      }
      byEntity.set(entityKey, group)
      groups.push(group)
    }
    group.aliases.push(alias)
  }
  return groups
})

const aliasIds = computed(() => (
  props.aliases.map((a) => aliasKey(a)).filter(Boolean)
))
watch(aliasIds, (ids) => reconcileBulkSelection("world-aliases", ids), { immediate: true })

function aliasKeyOf(a) {
  return aliasKey(a)
}

function sourceLabelOf(a) {
  return { deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }[a.source] || a.source || "未记录"
}

function confidenceLabelOf(a) {
  return a.confidence != null ? `${(Number(a.confidence) * 100).toFixed(0)}%` : "未记录"
}

function authorEvidencePairs(a) {
  return [
    ["章节", Number(a.source_chapter_index) > 0 ? a.source_chapter_index : ""],
    ["场景", Number(a.scene_index) > 0 ? a.scene_index : ""],
    ["引用", a.quote],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

function diagnosticEvidencePairs(a) {
  return [
    ["处理批次", a.workflow_id],
    ["场景标识", Number(a.scene_index) > 0 ? "" : a.scene_id],
    ["章节标识", Number(a.source_chapter_index) > 0 ? "" : a.source_chapter_id],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

function statusLabelOf(a) {
  const status = a.status === "candidate" || a.needs_review
    ? "candidate"
    : (a.status || (a.display_state ? undefined : "canonical"))
  return worldAssetDisplay({ ...a, status }).label
}

function statusBadgeClassOf(a) {
  const status = a.status === "candidate" || a.needs_review
    ? "candidate"
    : (a.status || (a.display_state ? undefined : "canonical"))
  return displayStateBadgeClass(worldAssetDisplay({ ...a, status }).displayState)
}

function onDeleteAlias(entityId, alias) {
  deleteAlias(entityId, alias)
}

function onEditAlias(entityId, alias) {
  showAliasEditForm(entityId, alias)
}

function onPageChange(delta) {
  const filters = session.aliasListFilters
  const newSkip = filters.skip + delta * filters.limit
  if (newSkip < 0) return
  if (newSkip >= props.aliasesTotal) return
  filters.skip = newSkip
  navigateAliases(filters)
}

function applySearch() {
  const filters = session.aliasListFilters
  filters.q = searchQuery.value.trim()
  filters.skip = 0
  navigateAliases(filters)
}

function clearSearch() {
  searchQuery.value = ""
  applySearch()
}

function navigateAliases(filters) {
  getRouter()?.navigate?.("world", "aliases", true, reviewQueryFromState(filters, ["q"]))
}

function retryLoad() {
  getRouter()?.refresh?.()
}

function onBulkAction(action) {
  const scope = "world-aliases"
  const selection = getBulkSelection(scope)
  const items = selectedItemsFrom(props.aliases, selection, (a) => aliasKey(a))
  if (!items.length) {
    getToast()("请先选择要处理的项目", "warning")
    return
  }
  if (action === "review-aliases" && items.some((item) => !item.alias_kind)) {
    getToast()("所选别名中有待分类项，请先选择别名分类", "warning")
    return
  }
  const labelByAction = { "review-aliases": "批量采用", "delete-aliases": "批量删除" }
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
