<script setup>
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"

defineProps({
  cards: { type: Array, default: () => [] },
  metaFor: { type: Function, required: true },
})
const emit = defineEmits(["open", "create-task"])
</script>

<template>
  <div class="world-bible-page-card-grid world-card-grid">
    <article v-for="card in cards" :key="card.key" class="world-bible-page-card world-card" :class="`world-card--${card.kind}`" :data-world-card-kind="card.kind" :style="{ '--world-bible-type-color': metaFor(card).color }">
      <div class="world-bible-page-card__band"></div>
      <div class="world-bible-page-card__head">
        <div class="world-bible-page-card__icon">{{ metaFor(card).symbol }}</div>
        <div class="world-bible-page-card__title">
          <h3>{{ card.title }}</h3>
          <div class="world-bible-page-card__meta">
            <span>{{ metaFor(card).label }}</span>
            <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
          </div>
        </div>
      </div>
      <p class="world-bible-page-card__summary">{{ card.summary || '还没有摘要，可以打开后补充。' }}</p>
      <div class="world-bible-page-card__footer">
        <span>{{ card.kind === 'page' ? '资料页' : '人物或具体设定' }}</span>
        <span v-if="card.draftId">已保留未发布修改</span>
      </div>
      <div class="world-bible-page-card__actions">
        <button class="btn btn-sm btn-ghost" type="button" data-action="world-card-create-task" @click="emit('create-task', card)">添加到我的任务</button>
        <button class="btn btn-sm btn-primary" type="button" data-action="open-world-card" @click="emit('open', card)">{{ card.state === 'working' ? '继续编辑' : '打开' }}</button>
      </div>
    </article>
  </div>
</template>

<style scoped>
@media (max-width: 760px) {
  .world-bible-page-card__actions .btn { min-height: 44px; }
}
</style>
