<template>
  <div class="map-change-review">
    <p v-if="!changes.length">没有内容变化。</p>
    <article v-for="change in changes" :key="change.key">
      <header>
        <label v-if="selectable"><input type="checkbox" :checked="modelValue.includes(change.key)" @change="toggle(change.key, $event.target.checked)" />{{ change.action }}：{{ change.label }}</label>
        <strong v-else>{{ change.action }}：{{ change.label }}</strong>
        <button v-if="change.featureIds.length" class="btn btn-sm" @click="$emit('locate', change.featureIds)">定位变化</button>
      </header>
      <details><summary>查看改了什么</summary><table>
        <thead><tr><th scope="col">内容</th><th scope="col">原来</th><th scope="col">现在</th></tr></thead>
        <tbody><tr v-for="field in change.fields" :key="field.title"><th scope="row">{{ field.title }}</th><td>{{ field.before }}</td><td>{{ field.after }}</td></tr></tbody>
      </table></details>
    </article>
  </div>
</template>
<script setup>
const props = defineProps({ changes: { type: Array, required: true }, modelValue: { type: Array, default: () => [] }, selectable: Boolean })
const emit = defineEmits(['update:modelValue', 'locate'])
function toggle(key, checked) { emit('update:modelValue', checked ? [...props.modelValue, key] : props.modelValue.filter(item => item !== key)) }
</script>
<style scoped>
.map-change-review{display:grid;gap:var(--space-2)}article{border-bottom:1px solid var(--border);padding-block:var(--space-2)}header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);flex-wrap:wrap}label{display:flex;align-items:center;gap:var(--space-2);min-height:44px}summary{cursor:pointer;min-height:44px;align-content:center}table{width:100%;table-layout:fixed;border-collapse:collapse}th,td{text-align:left;vertical-align:top;overflow-wrap:anywhere;padding:var(--space-2);border-bottom:1px solid var(--border);white-space:pre-wrap}th:first-child{width:24%}td{color:var(--text-secondary)}
</style>
