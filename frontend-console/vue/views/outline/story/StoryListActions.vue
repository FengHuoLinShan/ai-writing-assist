<template>
  <div class="story-outline-list-item__actions" :aria-label="`${itemLabel}操作`">
    <button class="btn btn-sm btn-ghost" type="button" :disabled="index === 0" :aria-label="`${itemLabel}上移`" @click="$emit('move', -1)">上移</button>
    <button class="btn btn-sm btn-ghost" type="button" :disabled="index >= length - 1" :aria-label="`${itemLabel}下移`" @click="$emit('move', 1)">下移</button>
    <button class="btn btn-sm btn-ghost" type="button" :aria-label="`删除${itemLabel}`" @click="$emit('remove')">删除</button>
  </div>
</template>

<script setup>
defineProps({
  index: { type: Number, required: true },
  length: { type: Number, required: true },
  itemLabel: { type: String, default: "列表项" },
})
defineEmits(["move", "remove"])
</script>
