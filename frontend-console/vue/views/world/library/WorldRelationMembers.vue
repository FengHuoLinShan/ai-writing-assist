<!--
  WorldRelationMembers — 关系分组视角的组内/未关联成员页。
  复用 WorldLibraryCards/WorldLibraryList + WorldPager（成员维度分页/搜索/排序）；
  每个成员显示 relation_refs（关系标签可进入现有关系编辑流）；
  选择复用 worldBulkSelection（作用域 = 项目 + 视角 + 分组 + 已应用查询，
  全选仅当前页，一次最多 50）；添加/移出走同一 membership-batch 入口。
-->
<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getRouter, getToast } from "../../../bridge/index.js"
import WorldLibraryCards from "./WorldLibraryCards.vue"
import WorldLibraryList from "./WorldLibraryList.vue"
import WorldPager from "../components/WorldPager.vue"
import WorldRelationAddDialog from "./WorldRelationAddDialog.vue"
import WorldRelationRemoveDialog from "./WorldRelationRemoveDialog.vue"
import {
  LIBRARY_PAGE_SIZE,
  RELATION_MEMBERSHIP_MAX,
  buildMembershipAddPayload,
  buildMembershipRemovePayload,
  cardsFromLibraryItems,
  membershipResultMessage,
  relationMembershipErrorInfo,
  relationRefLabel,
  relationSelectionScope,
} from "../bible/worldCards.js"
import {
  getBulkSelection,
  clearBulkSelection,
  reconcileBulkSelection,
  selectAllState,
  toggleAllBulkSelection,
} from "../logic/worldBulkSelection.js"

const props = defineProps({
  projectId: { type: String, default: "" },
  filters: { type: Object, default: () => ({}) },
  viewMeta: { type: Object, default: null },
  bible: { type: Object, default: null },
  metaFor: { type: Function, required: true },
  relationKindOptions: { type: Array, default: () => [] },
  groupLabel: { type: String, default: "" },
})
const emit = defineEmits(["apply-filters", "open-card", "create-task", "toggle-favorite", "edit-relation", "retry"])

const toast = getToast()

const unlinkedMode = computed(() => Boolean(props.filters.groupUnlinked))
const memberCards = computed(() => cardsFromLibraryItems(props.bible?.libraryItems || []))
const libraryTotal = computed(() => Number(props.bible?.libraryTotal || 0))
const loadError = computed(() => props.bible?.relationGroupsError || null)
// 组内成员搜索是独立作用域（member_q），与组列表的组名搜索（q）互不串扰。
const memberSearch = ref(props.filters.memberQ || "")
watch(() => props.filters.memberQ, (value) => { memberSearch.value = value || "" })

const scope = computed(() => relationSelectionScope(props.projectId, props.filters))
const visibleMemberIds = computed(() => memberCards.value.map((card) => card.id).filter(Boolean))
// 结果集变化时只保留仍可见的成员（配合 URL 作用域，跨项目/跨分组选择自然失效）。
watch([scope, () => memberCards.value], () => {
  reconcileBulkSelection(scope.value, visibleMemberIds.value)
}, { immediate: true })

const selectedCount = computed(() => getBulkSelection(scope.value).size)
const overLimit = computed(() => selectedCount.value > RELATION_MEMBERSHIP_MAX)
const allState = computed(() => selectAllState(scope.value, visibleMemberIds.value))

function toggleAll(event) {
  if (!event.target.checked) {
    toggleAllBulkSelection(scope.value, visibleMemberIds.value, false)
    return
  }
  const current = getBulkSelection(scope.value).size
  const incoming = visibleMemberIds.value.filter((id) => !getBulkSelection(scope.value).has(String(id))).length
  if (current + incoming > RELATION_MEMBERSHIP_MAX) {
    toast(`一次最多选择 ${RELATION_MEMBERSHIP_MAX} 个成员，请分批处理。`, "warning")
    event.target.checked = false
    return
  }
  toggleAllBulkSelection(scope.value, visibleMemberIds.value, true)
}

function clearSelection() {
  clearBulkSelection(scope.value)
}

function selectedMembers() {
  const selection = getBulkSelection(scope.value)
  return memberCards.value.filter((card) => selection.has(String(card.id)))
}

// ---- 添加 / 移出（单个与批量共用 membership-batch 入口） ----
// 请求期间组件可能被卸载或切到别的项目/分组：旧响应不得在新页面提示成功或刷新路由。
let disposed = false
onBeforeUnmount(() => { disposed = true })
const pageIdentity = computed(() => (
  `${props.projectId}|${props.filters.groupView || ""}|${props.filters.groupId || ""}|${props.filters.groupUnlinked ? "1" : "0"}`
))

const addOpen = ref(false)
const addPending = ref(false)
const addErrorInfo = ref(null)
const addTargets = ref([])

const removeOpen = ref(false)
const removePending = ref(false)
const removeErrorInfo = ref(null)
const removeTargets = ref([])

const addGroupOptions = ref([])
const addGroupsLoading = ref(false)
let addGroupsLoaded = false

function openAdd(cards) {
  if (!cards.length) {
    toast("请先选择要添加的成员。", "warning")
    return
  }
  addErrorInfo.value = null
  addTargets.value = cards
  addOpen.value = true
  // 目标组选择需要完整组列表（未关联页必选；组内页可改选其他组）。
  if (!addGroupsLoaded) loadAddGroupOptions()
}

async function loadAddGroupOptions() {
  addGroupsLoaded = true
  addGroupsLoading.value = true
  const params = {
    novel_id: props.projectId,
    group_view: props.filters.groupView,
    skip: 0,
    // 服务端 MAX_PAGE_SIZE=50；超出会被 422 拒绝导致组选项永远不就绪。
    limit: 50,
  }
  if (props.filters.groupView === "custom") {
    if (props.filters.groupType) params.group_type = props.filters.groupType
    if (props.filters.memberType) params.member_type = props.filters.memberType
    if (props.filters.relationType) params.relation_type = props.filters.relationType
    if (props.filters.groupSide) params.group_side = props.filters.groupSide
  }
  try {
    // 按 total 完整分页拉取：只取首页会让第 51 个之后的组无法被选为添加目标。
    let skip = 0
    let total = Number.POSITIVE_INFINITY
    while (skip < total) {
      const data = await getApi().world.listRelationGroups({ ...params, skip })
      if (disposed) return
      const items = Array.isArray(data?.items) ? data.items : []
      addGroupOptions.value = [...addGroupOptions.value, ...items]
      total = Number(data?.total ?? items.length)
      if (!items.length) break
      skip += items.length
    }
    addGroupsLoading.value = false
  } catch {
    addGroupsLoaded = false
    addGroupOptions.value = []
    addGroupsLoading.value = false
    if (!disposed) toast("分组列表加载失败，可关闭后重试", "warning")
  }
}

function openRemove(cards) {
  const withRefs = cards.filter((card) => (card.relationRefs || []).length)
  if (!withRefs.length) {
    toast("所选成员在本分组没有可结束的关系。", "warning")
    return
  }
  removeErrorInfo.value = null
  removeTargets.value = withRefs
  removeOpen.value = true
}

function runErrorAction(action) {
  const router = getRouter()
  if (action === "review") {
    router?.navigate("world", "review", true, new URLSearchParams({ kind: "relations" }))
    return
  }
  if (action === "validation") {
    router?.navigate("world", "bible", true, new URLSearchParams({ open: "health" }))
    return
  }
  router?.refresh?.()
}

async function submitAdd(relation, targetGroupId = null) {
  const memberIds = addTargets.value.map((card) => card.id)
  const { payload, error } = buildMembershipAddPayload({
    projectId: props.projectId,
    filters: props.filters,
    memberIds,
    relation,
    groupId: targetGroupId,
  })
  if (error) {
    toast(error, "warning")
    return
  }
  addPending.value = true
  addErrorInfo.value = null
  const identity = pageIdentity.value
  try {
    const result = await getApi().world.applyRelationMembershipBatch(payload, props.projectId)
    // 卸载或切到别的项目/分组后完成的旧请求：不再提示成功或刷新新页面。
    if (disposed || pageIdentity.value !== identity) return
    addPending.value = false
    addOpen.value = false
    clearSelection()
    toast(membershipResultMessage(result), "success")
    getRouter()?.refresh?.()
  } catch (err) {
    if (disposed || pageIdentity.value !== identity) return
    addPending.value = false
    // 失败保留输入与选择，显示作者可懂文案与后续入口。
    addErrorInfo.value = relationMembershipErrorInfo(err)
  }
}

async function submitRemove(relationRefs) {
  const memberIds = removeTargets.value.map((card) => card.id)
  const { payload, error } = buildMembershipRemovePayload({
    projectId: props.projectId,
    filters: props.filters,
    memberIds,
    relationRefs,
  })
  if (error) {
    toast(error, "warning")
    return
  }
  removePending.value = true
  removeErrorInfo.value = null
  const identity = pageIdentity.value
  try {
    const result = await getApi().world.applyRelationMembershipBatch(payload, props.projectId)
    if (disposed || pageIdentity.value !== identity) return
    removePending.value = false
    removeOpen.value = false
    clearSelection()
    toast(membershipResultMessage(result), "success")
    getRouter()?.refresh?.()
  } catch (err) {
    if (disposed || pageIdentity.value !== identity) return
    removePending.value = false
    removeErrorInfo.value = relationMembershipErrorInfo(err)
  }
}

function labelFor(ref) {
  return relationRefLabel(props.viewMeta, ref)
}

function submitSearch() {
  emit("apply-filters", { memberQ: memberSearch.value, skip: 0 })
}

function changeSort(event) {
  emit("apply-filters", { sort: event.target.value, skip: 0 })
}

function changePage(delta) {
  const nextSkip = Math.max(0, (props.filters.skip || 0) + delta * LIBRARY_PAGE_SIZE)
  emit("apply-filters", { skip: nextSkip })
}

function backToGroups() {
  // 返回组列表：丢弃成员搜索 member_q；组名搜索 q 留在 URL，原样恢复组查询。
  emit("apply-filters", { groupId: "", groupUnlinked: false, memberQ: "", skip: 0 })
}

const headerLabel = computed(() => {
  if (unlinkedMode.value) return "尚无此类关联"
  return props.groupLabel || "分组成员"
})

const countLabel = computed(() => (
  `${libraryTotal.value} 名成员${libraryTotal.value > LIBRARY_PAGE_SIZE
    ? `，第 ${Math.floor((props.filters.skip || 0) / LIBRARY_PAGE_SIZE) + 1} / ${Math.ceil(libraryTotal.value / LIBRARY_PAGE_SIZE)} 页`
    : ""}`
))

const emptyHint = computed(() => {
  if (props.filters.memberQ) return "没有找到匹配的成员，换个关键词试试。"
  if (unlinkedMode.value) return "本视角下所有对象都已建立此类关联。"
  return "这个分组还没有成员，可以从“尚无此类关联”入口补充。"
})
</script>

<template>
  <div class="world-relation-members" data-relation-view="members">
    <header class="world-type-results__header">
      <button type="button" class="btn btn-sm btn-ghost" data-action="relation-members-back" @click="backToGroups">← 返回分组列表</button>
      <div>
        <h2>{{ viewMeta?.title || '关系分组' }} · {{ headerLabel }}</h2>
        <p data-relation-members-count>{{ countLabel }}</p>
      </div>
    </header>

    <div v-if="loadError" class="empty-state" role="alert" data-author-action="retry">
      <p>分组成员暂时没有加载出来：{{ loadError }}</p>
      <button class="btn btn-sm" type="button" data-action="relation-members-retry" @click="emit('retry')">重新加载</button>
    </div>

    <template v-else>
      <form class="world-card-filters" role="search" @submit.prevent="submitSearch">
        <label class="world-card-filters__search">
          <span>搜索成员</span>
          <input v-model="memberSearch" type="search" maxlength="120" placeholder="名称、别名或内容" data-field="relation-member-search">
        </label>
        <label>
          <span>排序</span>
          <select :value="filters.sort" data-field="relation-member-sort" @change="changeSort">
            <option value="updated">最近更新</option>
            <option value="recent">最近使用</option>
            <option value="title">名称</option>
            <option value="created">创建时间</option>
          </select>
        </label>
        <div class="world-card-filters__actions">
          <button class="btn btn-sm btn-primary" type="submit" data-action="relation-member-search">查找</button>
          <button v-if="filters.memberQ" class="btn btn-sm" type="button" data-action="relation-member-clear-search" @click="memberSearch = ''; emit('apply-filters', { memberQ: '', skip: 0 })">清除</button>
        </div>
      </form>

      <div class="bulk-toolbar world-relation-members__toolbar" :data-scope="scope">
        <div class="bulk-toolbar__status">
          <span class="bulk-toolbar__select-all">
            <label class="selection-checkbox">
              <input
                type="checkbox"
                data-action="relation-members-toggle-all"
                :checked="allState.checked"
                :indeterminate.prop="allState.indeterminate"
                :disabled="allState.disabled"
                @change="toggleAll"
              >
              <span>全选当前页</span>
            </label>
          </span>
          <strong data-relation-selected-count>{{ selectedCount }}</strong>
          <span>名成员已选</span>
          <span v-if="overLimit" class="bulk-toolbar__hint" role="note">一次最多处理 {{ RELATION_MEMBERSHIP_MAX }} 个成员，请先减少选择。</span>
        </div>
        <div class="bulk-toolbar__actions">
          <button class="btn btn-sm btn-primary" type="button" data-action="relation-members-add" :disabled="!selectedCount || overLimit" @click="openAdd(selectedMembers())">添加到分组</button>
          <button v-if="!unlinkedMode" class="btn btn-sm btn-danger" type="button" data-action="relation-members-remove" :disabled="!selectedCount || overLimit" @click="openRemove(selectedMembers())">移出分组</button>
          <button class="btn btn-sm" type="button" data-action="relation-members-clear" :disabled="!selectedCount" @click="clearSelection">清空选择</button>
        </div>
      </div>

      <WorldLibraryCards
        v-if="memberCards.length && filters.layout === 'cards'"
        :cards="memberCards"
        :meta-for="metaFor"
        selectable
        :selection-scope="scope"
        :selection-limit="RELATION_MEMBERSHIP_MAX"
        :relation-label-for="labelFor"
        :member-mode="unlinkedMode ? 'unlinked' : 'group'"
        @open="emit('open-card', $event)"
        @create-task="emit('create-task', $event)"
        @toggle-favorite="emit('toggle-favorite', $event)"
        @add-one="openAdd([$event])"
        @remove-one="openRemove([$event])"
        @edit-relation="emit('edit-relation', $event)"
      />
      <WorldLibraryList
        v-else-if="memberCards.length"
        :cards="memberCards"
        :meta-for="metaFor"
        selectable
        :selection-scope="scope"
        :selection-limit="RELATION_MEMBERSHIP_MAX"
        :relation-label-for="labelFor"
        :member-mode="unlinkedMode ? 'unlinked' : 'group'"
        @open="emit('open-card', $event)"
        @create-task="emit('create-task', $event)"
        @toggle-favorite="emit('toggle-favorite', $event)"
        @add-one="openAdd([$event])"
        @remove-one="openRemove([$event])"
        @edit-relation="emit('edit-relation', $event)"
      />
      <div v-else class="empty-state" data-relation-members-empty>
        <p>{{ emptyHint }}</p>
        <button v-if="filters.memberQ" class="btn btn-sm" type="button" @click="memberSearch = ''; emit('apply-filters', { memberQ: '', skip: 0 })">清除搜索</button>
      </div>

      <WorldPager
        :total="libraryTotal"
        :skip="filters.skip || 0"
        :limit="LIBRARY_PAGE_SIZE"
        prev-action="relation-members-prev-page"
        next-action="relation-members-next-page"
        @change="changePage"
      />
    </template>

    <WorldRelationAddDialog
      :open="addOpen"
      :view-meta="viewMeta"
      :filters="filters"
      :members="addTargets"
      :groups="addGroupOptions"
      :groups-loading="addGroupsLoading"
      :relation-kind-options="relationKindOptions"
      :pending="addPending"
      :error-info="addErrorInfo"
      @close="addOpen = false"
      @submit="submitAdd"
      @error-action="runErrorAction"
    />
    <WorldRelationRemoveDialog
      :open="removeOpen"
      :view-meta="viewMeta"
      :members="removeTargets"
      :pending="removePending"
      :error-info="removeErrorInfo"
      @close="removeOpen = false"
      @submit="submitRemove"
      @error-action="runErrorAction"
    />
  </div>
</template>

<style scoped>
.world-relation-members { display: grid; gap: 12px; min-width: 0; }
.world-relation-members__toolbar .bulk-toolbar__select-all { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 760px) {
  .world-relation-members__toolbar .bulk-toolbar__actions .btn { min-height: 44px; }
}
</style>
