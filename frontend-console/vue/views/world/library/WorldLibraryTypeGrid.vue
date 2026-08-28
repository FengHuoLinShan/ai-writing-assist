<script setup>
defineProps({ cards: { type: Array, default: () => [] }, workingCount: { type: Number, default: 0 } })
const emit = defineEmits(["select", "more"])
</script>

<template>
  <div class="world-type-grid" aria-label="资料类型">
    <button v-for="card in cards" :key="card.value" type="button" class="world-type-card" @click="emit('select', card.value)">
      <span class="world-type-card__symbol" aria-hidden="true">{{ card.symbol }}</span>
      <span><strong>{{ card.label }}</strong><small>{{ card.count }} 项</small></span>
      <span aria-hidden="true">›</span>
    </button>
    <button type="button" class="world-type-card" @click="emit('select', 'working')">
      <span class="world-type-card__symbol" aria-hidden="true">稿</span>
      <span><strong>工作稿</strong><small>{{ workingCount }} 项</small></span>
      <span aria-hidden="true">›</span>
    </button>
    <button type="button" class="world-type-card" @click="emit('more')">
      <span class="world-type-card__symbol" aria-hidden="true">···</span>
      <span><strong>更多类型</strong><small>查看全部</small></span>
      <span aria-hidden="true">›</span>
    </button>
  </div>
</template>

<style scoped>
.world-type-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.world-type-card { display: grid; min-width: 0; min-height: 142px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 18px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 20px; background: var(--bg-panel); color: var(--text-primary); text-align: left; cursor: pointer; }
.world-type-card:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-type-card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-type-card__symbol { display: grid; width: 64px; height: 64px; place-items: center; border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-secondary); font-size: var(--text-lg); }
.world-type-card strong, .world-type-card small { display: block; }
.world-type-card strong { font-size: var(--text-md); }
.world-type-card small { margin-top: 7px; color: var(--text-muted); }
@media (max-width: 1100px) { .world-type-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .world-type-grid { gap: 10px; }
  .world-type-card { min-height: 112px; gap: 10px; padding: 12px; }
  .world-type-card__symbol { width: 44px; height: 44px; }
}
@media (max-width: 390px) { .world-type-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
