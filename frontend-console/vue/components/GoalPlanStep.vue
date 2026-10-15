<template>
  <article class="goal-step-card">
    <header class="goal-step-heading">
      <div>
        <div class="goal-step-title">
          <span class="goal-step-index">{{ index + 1 }}</span>
          <h3>{{ stepView.label }}</h3>
        </div>
        <p>{{ stepView.description }}</p>
      </div>
      <span class="goal-step-risk" :data-risk="stepView.risk">{{ stepView.risk_label }}</span>
    </header>

    <label class="goal-step-intent">
      <span>这一步要做什么</span>
      <textarea :value="planStep.intent" rows="2" maxlength="1200" :disabled="disabled" @input="emitStep('intent', $event.target.value)" />
    </label>

    <div v-if="previousSteps.length" class="goal-step-dependencies">
      <strong>先完成</strong>
      <label v-for="item in previousSteps" :key="item.step_id">
        <input
          type="checkbox"
          :checked="planStep.depends_on.includes(item.step_id)"
          :disabled="disabled || referencedSteps.has(item.step_id)"
          @change="toggleDependency(item.step_id, $event.target.checked)"
        />
        {{ item.label }}
      </label>
      <small v-if="referencedSteps.size">参数或目标引用到的前置步骤必须保留。</small>
    </div>
    <p v-else class="goal-step-dependencies">这一步没有前置依赖。</p>

    <p v-if="stepView.preview_summary" class="goal-step-preview">{{ stepView.preview_summary }}</p>
    <dl v-if="stepView.diff?.length" class="goal-step-diff">
      <div v-for="change in stepView.diff" :key="change.field">
        <dt>{{ change.field }}</dt>
        <dd><span>{{ change.before }}</span><span aria-hidden="true">→</span><span>{{ change.after }}</span></dd>
      </div>
    </dl>

    <details class="goal-step-parameters">
      <summary>检查或调整参数</summary>
      <p v-if="stepView.fee_label" class="goal-step-fee">{{ stepView.fee_label }} · {{ stepView.status_label }}</p>
      <div v-if="planStep.operation_id === 'project.update_task'" class="goal-step-task-changes">
        <div v-for="field in taskChangeFields" :key="field.key" class="goal-step-change-row">
          <label :for="`goal-step-${index}-${field.key}`">{{ field.label }}</label>
          <select
            v-if="field.options"
            :id="`goal-step-${index}-${field.key}`"
            :value="planStep.parameters.changes?.[field.key] ?? ''"
            :disabled="disabled"
            @change="setTaskChange(field.key, $event.target.value)"
          >
            <option value="">未指定</option>
            <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <span v-else-if="field.readOnly" class="goal-step-readonly">{{ planStep.parameters.changes?.[field.key] ? '已指定来源' : '未指定' }}</span>
          <input
            v-else-if="!field.readOnly"
            :id="`goal-step-${index}-${field.key}`"
            :type="field.type"
            :value="planStep.parameters.changes?.[field.key] ?? ''"
            :disabled="disabled"
            @input="setTaskChange(field.key, $event.target.value)"
          />
          <button type="button" class="goal-step-remove-field" :disabled="disabled" :aria-label="`移除${field.label}`" @click="removeTaskChange(field.key)">移除</button>
        </div>
        <label class="goal-step-add-field">
          <span>添加可修改项</span>
          <select :value="''" :disabled="disabled || !availableTaskFields.length" @change="addTaskChange($event.target.value)">
            <option value="">选择字段…</option>
            <option v-for="field in availableTaskFields" :key="field.key" :value="field.key">{{ field.label }}</option>
          </select>
        </label>
        <p v-if="!Object.keys(planStep.parameters.changes || {}).length" class="goal-step-help">至少保留一个修改字段，或删除此步骤。</p>
      </div>
      <div class="goal-step-field-list">
        <GoalPlanField
          v-for="field in editableFields"
          :key="field.name"
          :field="field"
          :value="planStep.parameters?.[field.name]"
          :field-id="`goal-step-${index}-${field.name}`"
          :disabled="disabled"
          @update="emitParameter(field.name, $event)"
        />
        <p v-if="!editableFields.length && planStep.operation_id !== 'project.update_task'" class="goal-step-help">
          此步骤的结构化参数由工作区校验；你可以调整目标说明或删除这一步。
        </p>
      </div>
    </details>

    <footer class="goal-step-footer">
      <span>{{ stepView.target_count ? `${stepView.target_count} 个已选对象` : '按项目范围准备' }}</span>
      <button type="button" class="goal-step-remove" :disabled="disabled" @click="$emit('remove', stepView.step_id)">
        删除此步及依赖它的后续步骤
      </button>
    </footer>
  </article>
</template>

<script setup>
import { computed } from "vue"
import GoalPlanField from "./GoalPlanField.vue"

const props = defineProps({
  stepView: { type: Object, required: true },
  planStep: { type: Object, required: true },
  index: { type: Number, required: true },
  previousSteps: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(["update", "remove", "remove-parameter"])

const taskChangeFields = [
  { key: "title", label: "标题", type: "text" },
  { key: "note", label: "备注", type: "text" },
  { key: "due_date", label: "截止日期", type: "date" },
  { key: "source", label: "关联来源", readOnly: true },
  {
    key: "status",
    label: "状态",
    options: [
      { value: "open", label: "待处理" },
      { value: "completed", label: "已完成" },
      { value: "archived", label: "已归档" },
    ],
  },
]

const availableTaskFields = computed(() => taskChangeFields.filter(
  field => !field.readOnly && !Object.hasOwn(props.planStep.parameters.changes || {}, field.key),
))
const editableFields = computed(() => (props.stepView.fields || []).filter(
  field => field.name !== "changes" && field.kind !== "identifier" && field.kind !== "reference",
))
const referencedSteps = computed(() => {
  const result = new Set()
  const visit = value => {
    if (Array.isArray(value)) return value.forEach(visit)
    if (!value || typeof value !== "object") return
    if (value.$ref?.step_id) result.add(value.$ref.step_id)
    for (const [key, child] of Object.entries(value)) {
      if (key === "target_id" && child?.step_id) result.add(child.step_id)
      else visit(child)
    }
  }
  visit(props.planStep.parameters)
  visit(props.planStep.targets)
  return result
})

function emitStep(key, value) {
  emit("update", { stepId: props.stepView.step_id, path: [key], value })
}

function emitParameter(key, value) {
  emit("update", { stepId: props.stepView.step_id, path: ["parameters", key], value })
}

function toggleDependency(stepId, checked) {
  const next = new Set(props.planStep.depends_on || [])
  if (checked) next.add(stepId)
  else next.delete(stepId)
  emitStep("depends_on", [...next])
}

function setTaskChange(key, value) {
  emit("update", {
    stepId: props.stepView.step_id,
    path: ["parameters", "changes", key],
    value: value === "" ? null : value,
  })
}

function removeTaskChange(key) {
  emit("remove-parameter", { stepId: props.stepView.step_id, path: ["parameters", "changes", key] })
}

function addTaskChange(key) {
  const field = taskChangeFields.find(item => item.key === key)
  if (!field) return
  const initial = field.key === "status" ? "open" : ""
  setTaskChange(field.key, initial)
}
</script>

<style scoped>
.goal-step-card{display:grid;gap:14px;padding:16px;border:1px solid var(--border-color,var(--border));border-radius:12px;background:var(--bg-primary,var(--bg-base));min-width:0}
.goal-step-heading,.goal-step-title,.goal-step-footer,.goal-step-change-row{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0}
.goal-step-heading p,.goal-step-fee,.goal-step-help{margin:6px 0 0;color:var(--text-secondary);font-size:13px;line-height:1.55}
.goal-step-title{justify-content:flex-start}.goal-step-title h3{margin:0;font-size:16px;line-height:1.4}
.goal-step-index{display:grid;place-items:center;flex:0 0 28px;height:28px;border-radius:50%;background:var(--bg-muted);font-weight:700}
.goal-step-risk{flex:0 0 auto;padding:4px 8px;border-radius:999px;background:var(--bg-muted);font-size:12px}
.goal-step-risk[data-risk="R2"]{background:color-mix(in srgb,var(--warning,#b7791f) 16%,var(--bg-primary,#fff))}
.goal-step-risk[data-risk="R3"],.goal-step-risk[data-risk="R4"]{background:color-mix(in srgb,var(--danger,#b42318) 14%,var(--bg-primary,#fff))}
.goal-step-intent,.goal-step-change-row,.goal-step-add-field{display:grid;gap:6px;font-size:13px}
.goal-step-intent textarea,.goal-step-change-row input,.goal-step-change-row select,.goal-step-add-field select{box-sizing:border-box;width:100%;min-height:40px;padding:8px 10px;border:1px solid var(--border-color,var(--border));border-radius:8px;background:var(--bg-muted);color:inherit;font:inherit}
.goal-step-intent textarea{resize:vertical;line-height:1.5}
.goal-step-dependencies{display:flex;align-items:center;flex-wrap:wrap;gap:10px;color:var(--text-secondary);font-size:12px}
.goal-step-dependencies label{display:flex;align-items:center;gap:6px;min-height:32px}.goal-step-dependencies input{width:18px;height:18px}
.goal-step-dependencies small{flex-basis:100%}
.goal-step-preview{margin:0;color:var(--text-primary);line-height:1.6;overflow-wrap:anywhere}
.goal-step-diff{display:grid;gap:8px;margin:0}.goal-step-diff div{display:grid;gap:4px}.goal-step-diff dt{font-size:12px;font-weight:600;color:var(--text-secondary)}.goal-step-diff dd{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:8px;margin:0;overflow-wrap:anywhere}
.goal-step-diff dd span:last-child{font-weight:600}
.goal-step-parameters summary{cursor:pointer;min-height:36px;line-height:36px;font-weight:600}
.goal-step-task-changes,.goal-step-field-list{display:grid;gap:10px;margin-top:10px}
.goal-step-change-row{grid-template-columns:minmax(5rem,auto) minmax(0,1fr) auto;align-items:center}
.goal-step-remove-field,.goal-step-remove{border:0;background:transparent;color:var(--text-secondary);text-decoration:underline;cursor:pointer}
.goal-step-remove-field:disabled,.goal-step-remove:disabled{opacity:.55;cursor:not-allowed}
.goal-step-add-field{grid-template-columns:auto minmax(0,1fr);align-items:center}
.goal-step-footer{padding-top:4px;border-top:1px solid var(--border-color,var(--border));font-size:12px;color:var(--text-secondary)}
.goal-step-remove{font-size:12px;text-align:right;line-height:1.4}
@media(max-width:520px){.goal-step-card{padding:12px}.goal-step-heading{align-items:flex-start}.goal-step-change-row{grid-template-columns:minmax(0,1fr) auto}.goal-step-change-row label{grid-column:1/-1}.goal-step-footer{align-items:flex-start}.goal-step-diff dd{grid-template-columns:minmax(0,1fr);gap:3px}.goal-step-diff dd span:nth-child(2){display:none}}
</style>
