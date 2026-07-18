<script setup>
import { DEEP_IMPORT_GROUPS, deepImportFieldId } from "../logic/deepImport.js"

/**
 * 深度导入字段网格 — DOM 契约与 vanilla renderDeepImportFields 一致
 * （group/field 结构、输入 id、bool 选项顺序）。
 */
const form = defineModel({ type: Object, required: true })

function fieldStep(field) {
  return field.step || (field.type === "float" ? "0.01" : "1")
}
</script>

<template>
  <div class="llm-deep-import-grid">
    <div v-for="group in DEEP_IMPORT_GROUPS" :key="group.id" class="deep-import-group">
      <h4>{{ group.label }}</h4>
      <div class="form-row">
        <div v-for="field in group.fields" :key="field.key" class="form-group">
          <label :for="deepImportFieldId(group.id, field.key)">{{ field.label }}</label>
          <select
            v-if="field.type === 'bool'"
            class="form-input"
            :id="deepImportFieldId(group.id, field.key)"
            v-model="form[group.id][field.key]"
          >
            <option value="false">关闭</option>
            <option value="true">开启</option>
          </select>
          <select
            v-else-if="field.type === 'nullableBool'"
            class="form-input"
            :id="deepImportFieldId(group.id, field.key)"
            v-model="form[group.id][field.key]"
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
          />
        </div>
      </div>
    </div>
  </div>
</template>
