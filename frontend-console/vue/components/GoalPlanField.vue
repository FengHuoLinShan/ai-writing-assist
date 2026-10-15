<template>
  <fieldset v-if="field.kind === 'object' && field.children?.length" class="goal-plan-field goal-plan-field--group">
    <legend>{{ field.label }}</legend>
    <GoalPlanField
      v-for="child in field.children"
      :key="child.name"
      :field="child"
      :value="value?.[child.name]"
      :field-id="`${fieldId}-${child.name}`"
      :disabled="disabled"
      @update="updateChild(child.name, $event)"
    />
    <small v-if="field.description">{{ field.description }}</small>
  </fieldset>

  <label
    v-else-if="field.kind !== 'identifier' && field.kind !== 'reference'"
    class="goal-plan-field"
    :for="fieldId"
  >
    <span>{{ field.label }}<span v-if="field.required" aria-hidden="true"> *</span></span>
    <span v-if="field.locked_reason" class="goal-plan-field-value">{{ field.locked_reason }}</span>
    <select
      v-else-if="field.enum_options?.length"
      :id="fieldId"
      :value="value ?? ''"
      :disabled="disabled || field.editable === false"
      @change="emitValue($event.target.value || null)"
    >
      <option v-if="!field.required" value="">未指定</option>
      <option v-for="option in field.enum_options" :key="option.value" :value="option.value">{{ option.label }}</option>
    </select>
    <input
      v-else-if="field.kind === 'boolean'"
      :id="fieldId"
      type="checkbox"
      :checked="value === true"
      :disabled="disabled || field.editable === false"
      @change="emitValue($event.target.checked)"
    />
    <textarea
      v-else-if="Array.isArray(value) && value.every(isPrimitive)"
      :id="fieldId"
      :value="value.join('\n')"
      rows="3"
      :disabled="disabled || field.editable === false"
      @input="emitValue($event.target.value.split('\n').map(item => item.trim()).filter(Boolean))"
    />
    <input
      v-else-if="field.kind === 'number'"
      :id="fieldId"
      type="number"
      :value="value ?? ''"
      :disabled="disabled || field.editable === false"
      @input="emitValue($event.target.value === '' ? null : Number($event.target.value))"
    />
    <textarea
      v-else-if="field.kind === 'text' && String(value ?? '').length > 100"
      :id="fieldId"
      :value="value ?? ''"
      rows="4"
      :disabled="disabled || field.editable === false"
      @input="emitValue($event.target.value)"
    />
    <input
      v-else-if="field.kind !== 'object' && !Array.isArray(value)"
      :id="fieldId"
      type="text"
      :value="value ?? ''"
      :disabled="disabled || field.editable === false"
      @input="emitValue($event.target.value === '' && !field.required ? null : $event.target.value)"
    />
    <span v-else class="goal-plan-field-value">{{ summary(value) }}</span>
    <small v-if="field.description">{{ field.description }}</small>
  </label>
</template>

<script setup>
const props = defineProps({
  field: { type: Object, required: true },
  value: { type: [String, Number, Boolean, Array, Object], default: null },
  fieldId: { type: String, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(["update"])

function isPrimitive(value) {
  return value === null || ["string", "number", "boolean"].includes(typeof value)
}

function emitValue(value) {
  emit("update", value)
}

function updateChild(name, value) {
  emitValue({ ...(props.value || {}), [name]: value })
}

function summary(value) {
  if (value == null) return "未指定"
  if (Array.isArray(value)) return `${value.length} 项`
  if (typeof value === "object") return "结构化资料"
  return String(value).slice(0, 160)
}
</script>

<style scoped>
.goal-plan-field{display:grid;gap:6px;min-width:0;color:var(--text-primary);font-size:13px}
.goal-plan-field input,.goal-plan-field select,.goal-plan-field textarea{box-sizing:border-box;width:100%;min-width:0;min-height:40px;padding:8px 10px;border:1px solid var(--border-color,var(--border));border-radius:8px;background:var(--bg-muted);color:inherit;font:inherit;line-height:1.5}
.goal-plan-field input[type=checkbox]{width:20px;min-height:20px;justify-self:start}
.goal-plan-field textarea{resize:vertical}
.goal-plan-field small{color:var(--text-secondary);line-height:1.5}
.goal-plan-field--group{padding:10px;border:1px solid var(--border-color,var(--border));border-radius:8px}
.goal-plan-field--group legend{padding:0 4px;font-weight:600}
.goal-plan-field-value{color:var(--text-secondary);padding:8px 0}
</style>
