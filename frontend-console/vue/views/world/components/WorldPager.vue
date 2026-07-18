<!--
  WorldPager — 分页条，DOM 契约对齐 vanilla _renderPager（worldView.js:1372-1385）。
  total <= limit 时不渲染。
-->
<template>
  <div v-if="total > limit" class="world-pagination">
    <button class="btn btn-sm" :data-action="prevAction" :disabled="skip <= 0" @click="$emit('change', -1)">上一页</button>
    <span class="world-pagination__info">第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条</span>
    <button class="btn btn-sm" :data-action="nextAction" :disabled="skip + limit >= total" @click="$emit('change', 1)">下一页</button>
  </div>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
  total: { type: Number, default: 0 },
  skip: { type: Number, default: 0 },
  limit: { type: Number, default: 20 },
  prevAction: { type: String, required: true },
  nextAction: { type: String, required: true },
})

defineEmits(["change"])

const currentPage = computed(() => Math.floor(props.skip / props.limit) + 1)
const totalPages = computed(() => Math.ceil(props.total / props.limit))
</script>
