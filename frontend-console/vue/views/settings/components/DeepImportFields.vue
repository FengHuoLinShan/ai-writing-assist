<script setup>
import { nextTick, ref, watch } from "vue"
import { DEEP_IMPORT_GROUPS, deepImportFieldId } from "../logic/deepImport.js"

/**
 * 深度导入字段网格 — DOM 契约与 vanilla renderDeepImportFields 一致
 * （group/field 结构、输入 id、bool 选项顺序）。
 */
const form = defineModel({ type: Object, required: true })
const props = defineProps({ validationError: { type: Object, default: null } })
const openGroups = ref(new Set())
const expertOpen = ref(false)

function toggleGroup(groupId) {
  const next = new Set(openGroups.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  openGroups.value = next
}

function changedCount(group) {
  return group.fields.filter((field) => String(form.value?.[group.id]?.[field.key] ?? "") !== String(field.value ?? "")).length
}

function fieldHelp(field) {
  if (field.type === "bool" || field.type === "nullableBool") return "开启会增加这一步的补充处理；关闭可节省时间和模型用量。"
  if (field.key.includes("concurrency") || field.key.includes("batch")) return "调高可同时处理更多内容，但更容易遇到限流；调低更稳，但会更慢。"
  if (field.key.includes("timeout") || field.key.includes("grace")) return "调高会等待更久，较慢的模型更容易完成；调低会更快失败并进入重试或人工检查。"
  if (field.key.includes("confidence")) return "调高会更保守，更多结果需要作者检查；调低会更积极地合并相近结果。"
  if (field.key.includes("token") || field.key.includes("chars") || field.key.includes("limit")) return "调高会保留更多上下文或细节，但耗时和模型用量更高；调低更快、更省。"
  if (field.key.includes("attempt")) return "调高会多尝试修复不完整结果，但会增加等待和模型用量；调低会更快交给人工检查。"
  return "调高通常会扩大这一步的处理范围；调低可缩短导入时间。"
}

function helpId(group, field) { return `${deepImportFieldId(group.id, field.key)}-help` }
function isOpen(groupId) { return openGroups.value.has(groupId) }
function isInvalid(group, field) { return props.validationError?.groupId === group.id && props.validationError?.fieldKey === field.key }

watch(() => props.validationError, (error) => {
  if (!error?.groupId || !error?.fieldKey) return
  expertOpen.value = true
  const next = new Set(openGroups.value)
  next.add(error.groupId)
  openGroups.value = next
  void nextTick(() => document.getElementById(deepImportFieldId(error.groupId, error.fieldKey))?.focus())
}, { deep: true })

function fieldStep(field) {
  return field.step || (field.type === "float" ? "0.01" : "1")
}
</script>

<template>
  <div class="deep-import-expert-toggle">
    <p>建议保持当前值。只有导入持续失败、遗漏明显或模型经常超时时再调整。</p>
    <button
      type="button"
      class="btn btn-sm"
      data-action="toggle-deep-import-expert"
      :aria-expanded="expertOpen"
      aria-controls="deep-import-expert-fields"
      @click="expertOpen = !expertOpen"
    >{{ expertOpen ? "收起专家参数" : "查看专家参数" }}</button>
  </div>
  <div id="deep-import-expert-fields" v-show="expertOpen" class="llm-deep-import-grid">
    <section v-for="group in DEEP_IMPORT_GROUPS" :key="group.id" class="deep-import-group">
      <button
        type="button"
        class="deep-import-group__toggle"
        :aria-expanded="isOpen(group.id)"
        :aria-controls="`deep-import-group-${group.id}`"
        @click="toggleGroup(group.id)"
      >
        <span>{{ group.label }}</span>
        <span v-if="changedCount(group)" class="deep-import-group__changed">与默认不同 {{ changedCount(group) }} 项</span>
        <span aria-hidden="true">{{ isOpen(group.id) ? '收起' : '展开' }}</span>
      </button>
      <div class="deep-import-group__summary">
        <p>{{ group.summary }}</p><p>适合：{{ group.when }}</p><p>代价：{{ group.cost }}</p>
      </div>
      <div v-show="isOpen(group.id)" :id="`deep-import-group-${group.id}`" class="form-row">
        <div v-for="field in group.fields" :key="field.key" class="form-group">
          <label :for="deepImportFieldId(group.id, field.key)">{{ field.label }}</label>
          <select
            v-if="field.type === 'bool'"
            class="form-input"
            :id="deepImportFieldId(group.id, field.key)"
            v-model="form[group.id][field.key]"
            :aria-describedby="helpId(group, field)"
            :aria-invalid="isInvalid(group, field)"
          >
            <option value="false">关闭</option>
            <option value="true">开启</option>
          </select>
          <select
            v-else-if="field.type === 'nullableBool'"
            class="form-input"
            :id="deepImportFieldId(group.id, field.key)"
            v-model="form[group.id][field.key]"
            :aria-describedby="helpId(group, field)"
            :aria-invalid="isInvalid(group, field)"
          >
            <option value="">自动</option>
            <option value="true">开启</option>
            <option value="false">关闭</option>
          </select>
          <input
            v-else
            class="form-input"
            :id="deepImportFieldId(group.id, field.key)"
            type="number"
            :min="field.min"
            :max="field.max"
            :step="fieldStep(field)"
            v-model="form[group.id][field.key]"
            :aria-describedby="helpId(group, field)"
            :aria-invalid="isInvalid(group, field)"
          />
          <p :id="helpId(group, field)" class="deep-import-field-help">{{ fieldHelp(field) }}</p>
          <p v-if="isInvalid(group, field)" class="form-error" role="alert">{{ validationError.error }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
