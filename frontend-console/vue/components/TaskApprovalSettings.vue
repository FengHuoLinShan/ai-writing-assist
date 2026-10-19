<template>
  <details class="task-approval-settings" :open="Boolean(modelValue)">
    <summary>修改方式：{{ modelValue ? '自动修改' : '逐项确认' }}</summary>
  <fieldset class="task-approval" :disabled="disabled">
    <legend>本次修改方式</legend>
    <label>批准方式
      <select :value="modelValue ? 'automatic' : 'manual'" @change="setMode($event.target.value)">
        <option value="manual">逐项确认</option>
        <option value="automatic" :disabled="!availability?.available || !scopeLabel">自动修改（Approve for me）</option>
      </select>
    </label>
    <p v-if="!availability?.available" role="status">{{ availability?.reason || '自动修改尚未完成模型实测，请逐项确认。' }}</p>
    <p v-else-if="!scopeLabel" role="status">请先选择具体对象或已保存章节，再开启本次自动修改。</p>
    <template v-if="modelValue">
      <p>仅本次任务：{{ scopeLabel }}。{{ budgetLabel }}。授权最多持续 30 分钟；次数或预算耗尽即停止。</p>
      <label>必须保留的内容（每行一项）
        <textarea :value="modelValue.preserve.join('\n')" rows="2" maxlength="20000" @input="update({ preserve: $event.target.value.split('\n').map(line => line.trim()).filter(Boolean) })" />
      </label>
      <label>最多判断次数
        <input type="number" min="1" max="30" :value="modelValue.max_judgments" @input="update({ max_judgments: Number($event.target.value) })" />
      </label>
      <p>允许代批符合要求的正文采用与设定修改；有创作取舍时仍会询问。合并、删除、废弃和发布需要本人确认。可随时撤回，已完成修改保留回执与原领域恢复入口。</p>
    </template>
  </fieldset>
  </details>
</template>

<script setup>
const props = defineProps({ modelValue: { type: Object, default: null }, availability: { type: Object, default: null }, scopeLabel: { type: String, default: '' }, budgetLabel: { type: String, default: '判断计入本任务已有预算' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
function setMode(mode) { emit('update:modelValue', mode === 'automatic' && props.availability?.available && props.scopeLabel ? { preserve: [], max_judgments: 5, timeout_seconds: 30 } : null) }
function update(values) { emit('update:modelValue', { ...props.modelValue, ...values }) }
</script>

<style scoped>
.task-approval-settings summary { min-height: 44px; padding: .4rem 0; cursor: pointer; font-size: .9rem; }
.task-approval { min-width: 0; display: grid; gap: .65rem; border: 1px solid var(--border-color, var(--border)); border-radius: .6rem; padding: .8rem; }
.task-approval label { display: grid; gap: .35rem; }
.task-approval select, .task-approval textarea, .task-approval input { box-sizing: border-box; min-height: 44px; max-width: 100%; width: 100%; color: var(--text-primary); background: var(--bg-input, var(--bg-primary)); border: 1px solid var(--border-color, var(--border)); border-radius: .4rem; padding: .5rem; }
.task-approval p { margin: 0; line-height: 1.5; font-size: .85rem; color: var(--text-secondary); overflow-wrap: anywhere; }
</style>
