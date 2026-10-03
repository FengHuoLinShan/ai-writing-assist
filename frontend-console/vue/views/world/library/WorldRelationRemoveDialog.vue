<!--
  WorldRelationRemoveDialog — 移出分组的领域确认。
  显示受影响对象、关系和数量；同一成员的多条关系由作者勾选要结束的具体关系
  （relation_refs 清单即勾选项，提交时透传 expected_execution_fingerprint）。
  清单为空时不可提交；提交进行中禁用重复提交；失败保留勾选并显示后续入口。
-->
<script setup>
import { computed, ref, watch } from "vue"
import WorldToolDialog from "../components/WorldToolDialog.vue"
import { relationRefLabel } from "../bible/worldCards.js"

const props = defineProps({
  open: { type: Boolean, default: false },
  viewMeta: { type: Object, default: null },
  members: { type: Array, default: () => [] }, // 所选成员卡（含 relationRefs）
  pending: { type: Boolean, default: false },
  errorInfo: { type: Object, default: null },
})
const emit = defineEmits(["close", "submit", "error-action"])

// relationId -> 是否勾选结束；默认全选（作者取消要保留的关系）。
const checked = ref(new Set())

watch(() => props.open, (open) => {
  if (!open) return
  const next = new Set()
  for (const member of props.members) {
    for (const ref of member.relationRefs || []) next.add(ref.relation.id)
  }
  checked.value = next
}, { immediate: true })

watch(() => props.members, () => {
  if (!props.open) return
  const valid = new Set()
  for (const member of props.members) {
    for (const ref of member.relationRefs || []) valid.add(ref.relation.id)
  }
  const next = new Set([...checked.value].filter((id) => valid.has(id)))
  if (next.size !== checked.value.size) checked.value = next
}, { immediate: true })

function toggle(relationId, event) {
  const next = new Set(checked.value)
  if (event.target.checked) next.add(relationId)
  else next.delete(relationId)
  checked.value = next
}

const totalRelations = computed(() => props.members.reduce(
  (sum, member) => sum + (member.relationRefs || []).length, 0,
))
const checkedCount = computed(() => {
  const valid = new Set(props.members.flatMap((member) => (member.relationRefs || []).map((ref) => ref.relation.id)))
  return [...checked.value].filter((id) => valid.has(id)).length
})
// 后端 membership-batch 的 relation_refs 单批上限。
const REFS_LIMIT = 50
const overRefsLimit = computed(() => checkedCount.value > REFS_LIMIT)

function submit() {
  if (!checkedCount.value || props.pending || overRefsLimit.value) return
  const refs = []
  for (const member of props.members) {
    for (const ref of member.relationRefs || []) {
      if (checked.value.has(ref.relation.id)) refs.push(ref)
    }
  }
  emit("submit", refs)
}
</script>

<template>
  <WorldToolDialog :open="open" title="移出分组" @close="!pending && emit('close')">
    <div class="world-relation-dialog" data-relation-remove-dialog>
      <p class="world-bible-empty-hint">
        将结束 {{ members.length }} 个对象<template v-if="members.length <= 3">（{{ members.map((member) => member.title).join('、') }}）</template>在本分组中的
        {{ totalRelations }} 条关系。关系行会保留为历史记录，未勾选的关系和其他分组不受影响。
      </p>

      <ul class="world-relation-remove__list" aria-label="要结束的关系清单">
        <li v-for="member in members" :key="member.id" class="world-relation-remove__member">
          <strong>{{ member.title }}</strong>
          <label v-for="ref in member.relationRefs" :key="ref.relation.id" class="world-relation-remove__ref">
            <input
              type="checkbox"
              data-action="relation-remove-toggle"
              :data-relation-id="ref.relation.id"
              :checked="checked.has(ref.relation.id)"
              :disabled="pending"
              @change="toggle(ref.relation.id, $event)"
            >
            <span>{{ relationRefLabel(viewMeta, ref) }}<small v-if="ref.relation.description"> · {{ ref.relation.description }}</small></span>
          </label>
          <p v-if="!(member.relationRefs || []).length" class="world-bible-empty-hint">这个对象在当前分组没有可结束的关系。</p>
        </li>
      </ul>

      <p class="world-review-result-summary" role="status" data-relation-remove-count>已勾选 {{ checkedCount }} / {{ totalRelations }} 条关系</p>
      <p v-if="!checkedCount" class="form-help" role="note">移出前至少要勾选一条要结束的关系。</p>
      <p v-else-if="overRefsLimit" class="form-help" role="alert" data-relation-remove-over-limit>一次最多结束 {{ REFS_LIMIT }} 条关系（当前 {{ checkedCount }} 条），请取消部分勾选或分批移出。</p>

      <div v-if="errorInfo" class="form-error" role="alert" data-relation-remove-error>
        <strong>{{ errorInfo.title }}</strong>
        <p>{{ errorInfo.message }}</p>
        <button v-if="errorInfo.action !== 'none'" class="btn btn-sm" type="button" :data-error-action="errorInfo.action" @click="emit('error-action', errorInfo.action)">{{ errorInfo.actionLabel }}</button>
      </div>

      <div class="world-relation-dialog__actions">
        <button class="btn btn-sm" type="button" :disabled="pending" data-action="relation-remove-cancel" @click="emit('close')">取消</button>
        <button class="btn btn-sm btn-primary" type="button" :disabled="!checkedCount || overRefsLimit || pending" data-action="relation-remove-confirm" @click="submit">{{ pending ? "正在移出…" : "确认移出" }}</button>
      </div>
    </div>
  </WorldToolDialog>
</template>

<style scoped>
.world-relation-dialog { display: grid; gap: 12px; }
.world-relation-remove__list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; max-height: 46vh; overflow-y: auto; }
.world-relation-remove__member { display: grid; gap: 6px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; }
.world-relation-remove__ref { display: flex; align-items: baseline; gap: 8px; min-height: 32px; }
.world-relation-remove__ref small { color: var(--text-muted); }
.world-relation-dialog__actions { display: flex; justify-content: flex-end; gap: 8px; }
.world-relation-dialog__actions .btn { min-height: 40px; }
.form-error { display: grid; gap: 6px; }
</style>
