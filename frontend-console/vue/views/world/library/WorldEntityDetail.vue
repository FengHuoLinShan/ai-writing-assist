<script setup>
import { computed } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"

const props = defineProps({
  entity: { type: Object, required: true },
  typeLabel: { type: String, default: "人物或设定" },
  aliasesOpen: { type: Boolean, default: false },
})
const emit = defineEmits(["back", "edit", "create-alias", "edit-alias", "create-task"])
const aliases = computed(() => (props.entity?.content_json?.aliases || []).map((item) => (
  typeof item === "string" ? { alias: item } : item
)).filter((item) => String(item?.alias || "").trim()))
const display = computed(() => worldAssetDisplay(props.entity))
</script>

<template>
  <article class="world-entity-detail" aria-labelledby="world-entity-detail-title">
    <header class="world-entity-detail__header">
      <div>
        <button type="button" class="btn btn-sm btn-ghost" @click="emit('back')">← 返回资料库</button>
        <h2 id="world-entity-detail-title">{{ entity.name || '未命名人物或设定' }}</h2>
        <p><span>{{ typeLabel }}</span> · <span class="badge" :class="displayStateBadgeClass(display.displayState)">{{ display.label }}</span></p>
      </div>
      <div class="world-entity-detail__actions">
        <button type="button" class="btn btn-sm" @click="emit('create-task')">添加到我的任务</button>
        <button type="button" class="btn btn-sm btn-primary" @click="emit('edit')">编辑资料</button>
      </div>
    </header>
    <section>
      <h3>概要</h3>
      <p>{{ entity.summary || entity.public_info || '还没有概要，可以编辑后补充。' }}</p>
    </section>
    <details :open="aliasesOpen || undefined" class="world-entity-detail__aliases">
      <summary>别名 <span>{{ aliases.length }}</span></summary>
      <ul v-if="aliases.length">
        <li v-for="item in aliases" :key="item.alias">
          <span>{{ item.alias }}</span>
          <button type="button" class="btn btn-sm btn-ghost" @click="emit('edit-alias', item.alias)">编辑</button>
        </li>
      </ul>
      <p v-else>还没有别名。别名会附着在这一对象上，不创建重复资料。</p>
      <button type="button" class="btn btn-sm" @click="emit('create-alias')">添加别名</button>
    </details>
  </article>
</template>

<style scoped>
.world-entity-detail { display: grid; gap: 20px; }
.world-entity-detail__header { display: flex; align-items: start; justify-content: space-between; gap: 20px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
.world-entity-detail__header h2 { margin: 12px 0 6px; }
.world-entity-detail__header p { margin: 0; color: var(--text-muted); }
.world-entity-detail__actions { display: flex; flex-wrap: wrap; justify-content: end; gap: 8px; }
.world-entity-detail__aliases { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; }
.world-entity-detail__aliases summary { cursor: pointer; font-weight: 600; }
.world-entity-detail__aliases ul { display: grid; gap: 6px; padding: 0; list-style: none; }
.world-entity-detail__aliases li { display: flex; min-height: 40px; align-items: center; justify-content: space-between; gap: 12px; }
@media (max-width: 760px) {
  .world-entity-detail__header { flex-direction: column; }
  .world-entity-detail__actions { width: 100%; justify-content: stretch; }
  .world-entity-detail__actions .btn, .world-entity-detail__aliases .btn { min-height: 44px; }
}
</style>
