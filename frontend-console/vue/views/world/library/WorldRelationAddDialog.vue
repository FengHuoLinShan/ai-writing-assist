<!--
  WorldRelationAddDialog — 把所选成员加入当前分组的确认面板。
  预设视角默认使用视角 default_relation，也可显式选择 match_relations 之一；
  custom 视角要求作者显式选择关系三元组（详细关系 / 最小语义分类 / 方向）。
  提交进行中禁用重复提交；失败保留输入并显示作者可懂的后续入口。
-->
<script setup>
import { computed, ref, watch } from "vue"
import WorldToolDialog from "../components/WorldToolDialog.vue"
import { relationAddOptions } from "../bible/worldCards.js"

const props = defineProps({
  open: { type: Boolean, default: false },
  viewMeta: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  members: { type: Array, default: () => [] }, // 所选成员卡（含 title）
  relationKindOptions: { type: Array, default: () => [] },
  // 可选的目标组（[{id, name}]），按 total 完整分页加载。
  groups: { type: Array, default: () => [] },
  groupsLoading: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
  errorInfo: { type: Object, default: null }, // relationMembershipErrorInfo 结果
})
const emit = defineEmits(["close", "submit", "error-action"])

const isCustom = computed(() => props.filters.groupView === "custom")
// 未关联页没有组上下文，添加前必须显式选择目标组。
const needsGroupPick = computed(() => !props.filters.groupId)
// 组内页也提供目标组选择：默认当前组，改选其他组可让对象同时属于两组
// （添加默认保留对象的其他归属），这是把已有成员归入另一组的就地路径。
const showGroupSelect = computed(() => (
  needsGroupPick.value || Boolean(props.groups.length) || props.groupsLoading
))
const addOptions = computed(() => relationAddOptions(props.viewMeta))

const selectedType = ref("")
const customRelationType = ref("")
const customRelationKind = ref("")
const customGroupSide = ref("")
const targetGroupId = ref("")

watch(() => props.open, (open) => {
  if (!open) return
  const presetDefault = props.viewMeta?.default_relation?.relation_type
    || addOptions.value[0]?.relation_type
    || ""
  selectedType.value = presetDefault
  customRelationType.value = props.filters.relationType || ""
  customRelationKind.value = ""
  customGroupSide.value = props.filters.groupSide || "target"
  targetGroupId.value = props.filters.groupId || props.groups[0]?.id || ""
}, { immediate: true })

watch(() => props.groups, (groups) => {
  if (!targetGroupId.value && groups.length) targetGroupId.value = groups[0]?.id || ""
})

const selectedOption = computed(() => addOptions.value.find((option) => option.relation_type === selectedType.value) || null)

const customValid = computed(() => Boolean(
  customRelationType.value.trim() && customRelationKind.value && customGroupSide.value,
))

const canSubmit = computed(() => (
  props.pending
    ? false
    : (showGroupSelect.value ? Boolean(targetGroupId.value) : true)
      && (isCustom.value ? customValid.value : Boolean(selectedOption.value))
))

function submit() {
  if (!canSubmit.value) return
  const relation = isCustom.value
    ? {
      relation_type: customRelationType.value.trim(),
      relation_kind: customRelationKind.value,
      group_side: customGroupSide.value,
    }
    : {
      relation_type: selectedOption.value.relation_type,
      relation_kind: selectedOption.value.relation_kind,
      group_side: selectedOption.value.group_side,
    }
  emit("submit", relation, showGroupSelect.value ? targetGroupId.value : null)
}
</script>

<template>
  <WorldToolDialog :open="open" title="添加到分组" @close="!pending && emit('close')">
    <div class="world-relation-dialog">
      <p class="world-bible-empty-hint">
        将为 {{ members.length }} 个对象<template v-if="members.length <= 3">（{{ members.map((member) => member.title).join('、') }}）</template>建立分组关系；
        已存在的同类正式关系会直接复用，不会修改其描述、证据或强度。
      </p>

      <label v-if="showGroupSelect" class="world-relation-dialog__field">
        <span>加入的分组 {{ needsGroupPick ? '*' : '' }}</span>
        <select v-model="targetGroupId" data-field="add-target-group" :disabled="pending || (!groups.length && groupsLoading)">
          <option v-if="!groups.length && groupsLoading" value="">分组加载中…</option>
          <option v-else-if="!targetGroupId" value="">请选择分组</option>
          <option v-if="targetGroupId && !groups.some((group) => group.id === targetGroupId)" :value="targetGroupId">当前分组</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option>
        </select>
        <small v-if="needsGroupPick">从“尚无此类关联”进入时，需要先选择要加入的分组。</small>
        <small v-else>默认加入当前分组；改选其他分组会让所选对象同时属于两个组，原有分组保留。</small>
        <small v-if="groupsLoading && groups.length">分组较多，正在加载剩余分组…</small>
      </label>

      <template v-if="!isCustom">
        <label class="world-relation-dialog__field">
          <span>使用的关系 *</span>
          <select v-model="selectedType" data-field="add-relation-type" :disabled="pending">
            <option v-for="option in addOptions" :key="`${option.relation_type}|${option.group_side}`" :value="option.relation_type">
              {{ option.label }}（{{ option.group_side === "source" ? "分组 → 成员" : "成员 → 分组" }}）
            </option>
          </select>
          <small>默认使用本视角的常用关系，也可以改用列表中的其他明确关系。</small>
        </label>
      </template>

      <template v-else>
        <label class="world-relation-dialog__field">
          <span>详细关系 *</span>
          <input v-model="customRelationType" type="text" maxlength="64" data-field="add-custom-relation-type" :disabled="pending" placeholder="例如 guarded_by">
        </label>
        <label class="world-relation-dialog__field">
          <span>最小语义分类 *</span>
          <select v-model="customRelationKind" data-field="add-custom-relation-kind" :disabled="pending">
            <option value="">请选择分类</option>
            <option v-for="option in relationKindOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <small>自定义关系需要选择一个既有最小语义分类，用于 AI 检索。</small>
        </label>
        <label class="world-relation-dialog__field">
          <span>分组在关系中的方向 *</span>
          <select v-model="customGroupSide" data-field="add-custom-group-side" :disabled="pending">
            <option value="target">分组是关系的目标（成员 → 分组）</option>
            <option value="source">分组是关系的源（分组 → 成员）</option>
          </select>
        </label>
      </template>

      <p v-if="isCustom && !customValid" class="form-help" role="note">自定义视角需要填写详细关系、语义分类和方向后才能提交。</p>

      <div v-if="errorInfo" class="form-error" role="alert" data-relation-add-error>
        <strong>{{ errorInfo.title }}</strong>
        <p>{{ errorInfo.message }}</p>
        <button v-if="errorInfo.action !== 'none'" class="btn btn-sm" type="button" :data-error-action="errorInfo.action" @click="emit('error-action', errorInfo.action)">{{ errorInfo.actionLabel }}</button>
      </div>

      <div class="world-relation-dialog__actions">
        <button class="btn btn-sm" type="button" :disabled="pending" data-action="relation-add-cancel" @click="emit('close')">取消</button>
        <button class="btn btn-sm btn-primary" type="button" :disabled="!canSubmit" data-action="relation-add-confirm" @click="submit">{{ pending ? "正在添加…" : "确认添加" }}</button>
      </div>
    </div>
  </WorldToolDialog>
</template>

<style scoped>
.world-relation-dialog { display: grid; gap: 12px; }
.world-relation-dialog__field { display: grid; gap: 4px; }
.world-relation-dialog__field small { color: var(--text-muted); }
.world-relation-dialog__actions { display: flex; justify-content: flex-end; gap: 8px; }
.world-relation-dialog__actions .btn { min-height: 40px; }
.form-error { display: grid; gap: 6px; }
</style>
