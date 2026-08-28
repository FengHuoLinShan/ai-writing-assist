<script setup>
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"

defineProps({
  cards: { type: Array, default: () => [] },
  metaFor: { type: Function, required: true },
})
const emit = defineEmits(["open", "create-task"])
</script>

<template>
  <ul class="world-library-list" aria-label="资料列表">
    <li v-for="card in cards" :key="card.key" class="world-library-list__row" :data-world-card-kind="card.kind">
      <button type="button" class="world-library-list__main" data-action="open-world-card" @click="emit('open', card)">
        <span class="world-library-list__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
        <span class="world-library-list__copy"><strong>{{ card.title }}</strong><small>{{ metaFor(card).label }} · {{ card.summary || '还没有摘要' }}</small></span>
        <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
      </button>
      <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-create-task" @click="emit('create-task', card)">添加任务</button>
    </li>
  </ul>
</template>

<style scoped>
.world-library-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-library-list__row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 8px; }
.world-library-list__main { display: grid; min-width: 0; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; border: 0; padding: 6px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.world-library-list__main:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-list__symbol { display: grid; width: 36px; height: 36px; place-items: center; border-radius: var(--radius-sm); background: var(--bg-hover); }
.world-library-list__copy { min-width: 0; display: grid; gap: 4px; }
.world-library-list__copy strong, .world-library-list__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-library-list__copy small { color: var(--text-muted); }
@media (max-width: 760px) {
  .world-library-list__row { grid-template-columns: 1fr; }
  .world-library-list__row > .btn { min-height: 44px; }
  .world-library-list__main { min-height: 52px; grid-template-columns: auto minmax(0, 1fr); }
  .world-library-list__main .badge { grid-column: 2; width: fit-content; }
}
</style>
