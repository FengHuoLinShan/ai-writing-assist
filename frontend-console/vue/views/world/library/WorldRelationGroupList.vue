<!--
  WorldRelationGroupList — 关系分组视角的组列表页。
  组名搜索作用于 relation-groups 的 q；分页是组数维度；
  零成员组保留并给出入口；未关联入口显示 unlinked_total。
  custom 视角配置不完整时展示配置表单，不发注定 422 的请求。
-->
<script setup>
import { computed, ref } from "vue"
import WorldPager from "../components/WorldPager.vue"
import { LIBRARY_PAGE_SIZE, isCustomViewConfigured } from "../bible/worldCards.js"

const props = defineProps({
  projectId: { type: String, default: "" },
  filters: { type: Object, default: () => ({}) },
  viewMeta: { type: Object, default: null },
  groups: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  unlinkedTotal: { type: Number, default: null },
  entityTypeOptions: { type: Array, default: () => [] },
  loadError: { type: String, default: null },
  pageSize: { type: Number, default: LIBRARY_PAGE_SIZE },
})
const emit = defineEmits(["apply-filters", "open-group-entity", "retry"])

const groupSearch = ref(props.filters.q || "")

const viewTitle = computed(() => props.viewMeta?.title || "关系分组")
const isCustom = computed(() => props.filters.groupView === "custom")
const customIncomplete = computed(() => isCustom.value && !isCustomViewConfigured(props.filters))

const customForm = ref({
  groupType: props.filters.groupType || "",
  memberType: props.filters.memberType || "",
  relationType: props.filters.relationType || "",
  groupSide: props.filters.groupSide || "",
})

function typeLabel(value) {
  return props.entityTypeOptions.find((item) => item.value === value)?.label || value || "未分类"
}

function submitSearch() {
  emit("apply-filters", { q: groupSearch.value, skip: 0 })
}

function openGroup(group) {
  // q（组名搜索）保留在 URL，返回组列表时原样恢复；成员搜索 member_q
  // 属于上一个组的浏览态，切换组时清空，避免串入新组的成员过滤。
  emit("apply-filters", { groupId: group.id, groupUnlinked: false, memberQ: "", skip: 0 })
}

function openUnlinked() {
  emit("apply-filters", { groupId: "", groupUnlinked: true, memberQ: "", skip: 0 })
}

function submitCustomForm() {
  emit("apply-filters", {
    groupType: customForm.value.groupType,
    memberType: customForm.value.memberType,
    relationType: customForm.value.relationType.trim(),
    groupSide: customForm.value.groupSide,
    skip: 0,
  })
}

const customFormValid = computed(() => Boolean(
  customForm.value.groupType
  && customForm.value.relationType.trim()
  && customForm.value.groupSide,
))

function changePage(delta) {
  const nextSkip = Math.max(0, (props.filters.skip || 0) + delta * props.pageSize)
  emit("apply-filters", { skip: nextSkip })
}
</script>

<template>
  <div class="world-relation-groups" data-relation-view="groups">
    <header class="world-type-results__header">
      <button type="button" class="btn btn-sm btn-ghost" data-action="relation-groups-back-home" @click="emit('apply-filters', { groupView: '' })">← 返回资料库首页</button>
      <div>
        <h2>{{ viewTitle }}</h2>
        <p>{{ viewMeta?.description || '按关系把相关对象组织成组，就地维护成员归属。' }}</p>
      </div>
    </header>

    <div v-if="loadError" class="empty-state" role="alert" data-author-action="retry">
      <p>分组列表暂时没有加载出来：{{ loadError }}</p>
      <button class="btn btn-sm" type="button" data-action="relation-groups-retry" @click="emit('retry')">重新加载</button>
    </div>

    <form v-else-if="customIncomplete" class="world-card-filters world-relation-custom-form" @submit.prevent="submitCustomForm">
      <p class="world-bible-empty-hint">自定义视角需要先选择分组对象类型、详细关系和方向；这些选择会保存进网址，刷新后可直接恢复。</p>
      <label>
        <span>分组对象类型 *</span>
        <select v-model="customForm.groupType" data-field="custom-group-type" required>
          <option value="">请选择</option>
          <option v-for="option in entityTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <label>
        <span>成员对象类型（可选）</span>
        <select v-model="customForm.memberType" data-field="custom-member-type">
          <option value="">全部类型</option>
          <option v-for="option in entityTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <label>
        <span>详细关系 *</span>
        <input v-model="customForm.relationType" type="text" maxlength="64" data-field="custom-relation-type" placeholder="例如 guarded_by" required>
      </label>
      <label>
        <span>分组在关系中的方向 *</span>
        <select v-model="customForm.groupSide" data-field="custom-group-side" required>
          <option value="">请选择</option>
          <option value="target">分组是关系的目标（成员 → 分组）</option>
          <option value="source">分组是关系的源（分组 → 成员）</option>
        </select>
      </label>
      <div class="world-card-filters__actions">
        <button class="btn btn-sm btn-primary" type="submit" :disabled="!customFormValid" data-action="relation-custom-apply">应用自定义视角</button>
      </div>
    </form>

    <template v-else>
      <form class="world-card-filters" role="search" @submit.prevent="submitSearch">
        <label class="world-card-filters__search">
          <span>搜索分组名称</span>
          <input v-model="groupSearch" type="search" maxlength="120" placeholder="按组名称或别名查找" data-field="relation-group-search">
        </label>
        <div class="world-card-filters__actions">
          <button class="btn btn-sm btn-primary" type="submit" data-action="relation-group-search">查找</button>
          <button v-if="filters.q" class="btn btn-sm" type="button" data-action="relation-group-clear-search" @click="groupSearch = ''; emit('apply-filters', { q: '', skip: 0 })">清除</button>
        </div>
      </form>

      <p class="world-review-result-summary" role="status" data-relation-groups-count>
        当前视角：{{ total }} 个分组<template v-if="unlinkedTotal != null">，{{ unlinkedTotal }} 个对象尚无此类关联</template>
      </p>

      <ul class="world-relation-groups__list" aria-label="分组列表">
        <li v-for="group in groups" :key="group.id" class="world-relation-groups__row" :data-group-id="group.id">
          <button type="button" class="world-relation-groups__main" data-action="relation-group-open" @click="openGroup(group)">
            <span class="world-relation-groups__name">{{ group.name }}</span>
            <span class="world-relation-groups__meta">
              <span class="badge">{{ typeLabel(group.entity_type) }}</span>
              <span :data-member-count="group.id">{{ group.member_count }} 名成员</span>
            </span>
          </button>
          <div class="world-relation-groups__actions">
            <button class="btn btn-sm btn-primary" type="button" data-action="relation-group-open-members" @click="openGroup(group)">查看成员</button>
            <button class="btn btn-sm btn-ghost" type="button" data-action="relation-group-open-entity" @click="emit('open-group-entity', group)">对象详情</button>
          </div>
        </li>
        <li v-if="unlinkedTotal != null" class="world-relation-groups__row world-relation-groups__row--unlinked">
          <button type="button" class="world-relation-groups__main" data-action="relation-group-open-unlinked" @click="openUnlinked">
            <span class="world-relation-groups__name">尚无此类关联</span>
            <span class="world-relation-groups__meta"><span :data-unlinked-total="true">{{ unlinkedTotal }} 个对象</span></span>
          </button>
          <div class="world-relation-groups__actions">
            <button class="btn btn-sm" type="button" data-action="relation-group-open-unlinked" @click="openUnlinked">查看并补充</button>
          </div>
        </li>
      </ul>

      <div v-if="!groups.length" class="empty-state" data-relation-groups-empty>
        <p>{{ filters.q ? '没有找到匹配的分组，换个关键词试试。' : '这个视角下还没有分组对象；先在资料库里采用相关对象，再回来维护成员。' }}</p>
        <button v-if="filters.q" class="btn btn-sm" type="button" @click="groupSearch = ''; emit('apply-filters', { q: '', skip: 0 })">清除搜索</button>
      </div>
      <div v-else-if="unlinkedTotal === 0" class="empty-state">
        <p>本视角下的对象都已建立此类关联。</p>
      </div>

      <WorldPager
        :total="total"
        :skip="filters.skip || 0"
        :limit="pageSize"
        prev-action="relation-groups-prev-page"
        next-action="relation-groups-next-page"
        @change="changePage"
      />
    </template>
  </div>
</template>

<style scoped>
.world-relation-groups { display: grid; gap: 12px; min-width: 0; }
.world-relation-groups__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-relation-groups__row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 8px; }
.world-relation-groups__main { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; border: 0; padding: 6px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.world-relation-groups__main:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-relation-groups__name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-relation-groups__meta { display: inline-flex; align-items: center; gap: 8px; color: var(--text-muted); }
.world-relation-groups__row--unlinked .world-relation-groups__name { color: var(--text-muted); }
.world-relation-groups__actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 6px 2px; }
.world-relation-custom-form { display: grid; gap: 10px; }
.world-relation-custom-form label { display: grid; gap: 4px; }
@media (min-width: 1080px) {
  .world-relation-groups__row { grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }
  .world-relation-groups__actions { flex-direction: column; align-items: stretch; padding: 0; }
}
@media (max-width: 760px) {
  .world-relation-groups__actions .btn { min-height: 44px; }
  .world-relation-groups__main { min-height: 52px; grid-template-columns: minmax(0, 1fr); }
  .world-relation-groups__main .world-relation-groups__meta { width: fit-content; }
}
</style>
