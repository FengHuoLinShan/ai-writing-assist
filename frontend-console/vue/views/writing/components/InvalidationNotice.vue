<template>
  <section class="writing-invalidation-notice" aria-label="本次保存的影响范围" role="status">
    <p class="writing-invalidation-notice__headline">{{ notice.headline }}</p>
    <p v-if="notice.hasUnknownScope" class="writing-invalidation-notice__unknown">
      部分影响范围待核实：系统按保守方式标记了更多可能受影响的内容，重算前会再核对。
    </p>
    <p class="writing-invalidation-notice__hint">
      现在可以继续写作；需要时再从这里查看受影响的内容并选择重算。
    </p>
    <button type="button" class="btn btn-sm writing-invalidation-notice__open" @click="$emit('open')">
      查看受影响与重算选项
    </button>
  </section>
</template>

<script setup>
defineProps({
  notice: { type: Object, required: true },
})
defineEmits(["open"])
</script>

<style scoped>
.writing-invalidation-notice {
  margin: 0 0 10px;
  padding: 10px 12px;
  border: 1px solid rgba(176, 132, 32, 0.4);
  border-left: 3px solid rgba(176, 132, 32, 0.8);
  border-radius: 7px;
  background: rgba(176, 132, 32, 0.08);
  display: grid;
  gap: 4px;
  min-width: 0;
}
.writing-invalidation-notice__headline,
.writing-invalidation-notice__unknown,
.writing-invalidation-notice__hint {
  margin: 0;
  overflow-wrap: anywhere;
}
.writing-invalidation-notice__unknown { color: var(--text-secondary); }
.writing-invalidation-notice__hint { color: var(--text-secondary); font-size: 12px; }
.writing-invalidation-notice__open { justify-self: start; min-height: 34px; }
</style>
