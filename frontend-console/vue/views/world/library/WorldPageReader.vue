<script setup>
import { computed, ref } from "vue"
import RpMarkdownContent from "../../interaction/RpMarkdownContent.vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"

const props = defineProps({
  source: { type: Object, default: null },
  sections: { type: Array, default: () => [] },
  assetRefs: { type: Array, default: () => [] },
  typeLabel: { type: String, default: "" },
  statusLabel: { type: String, default: "" },
  working: { type: Boolean, default: false },
  refItems: { type: Array, default: () => [] },
})
const emit = defineEmits(["edit", "back"])

const collapsed = ref(new Set())

const display = computed(() => worldAssetDisplay(props.source || {}))

const tocEntries = computed(() => {
  const entries = []
  if (String(props.source?.free_text || "").trim()) {
    entries.push({ id: "reader-overview", label: "页面概览" })
  }
  for (const section of props.sections) {
    const label = String(section?.title || "").trim()
    if (label) entries.push({ id: `reader-section-${section.section_id}`, label })
  }
  return entries
})

const visibleSections = computed(() => props.sections.filter(
  (section) => String(section?.title || "").trim() || String(section?.body_markdown || "").trim(),
))

const visibleRefs = computed(() => (props.refItems || []).slice(0, 50))

function toggleSection(sectionId) {
  const next = new Set(collapsed.value)
  if (next.has(sectionId)) next.delete(sectionId)
  else next.add(sectionId)
  collapsed.value = next
}

function isCollapsed(sectionId) {
  return collapsed.value.has(sectionId)
}

function scrollTo(id) {
  const target = document.getElementById(id)
  if (target) target.scrollIntoView({ block: "start" })
}

function sectionKindLabel(section) {
  if (section?.section_type === "checklist") return "检查清单"
  if (section?.section_type === "asset_collection") return "资产清单"
  return "正文"
}
</script>

<template>
  <div class="world-page-reader" data-reader-mode="read">
    <header class="world-page-reader__header">
      <div>
        <h2 id="world-page-reader-title">{{ source?.title || '未命名资料页' }}</h2>
        <p class="world-page-reader__meta">
          <span>{{ typeLabel }}</span> ·
          <span v-if="working" class="badge badge-draft">工作稿</span>
          <template v-else>
            <span>{{ statusLabel }}</span>
            <span class="badge" :class="displayStateBadgeClass(display.displayState)">{{ display.label }}</span>
          </template>
        </p>
      </div>
      <div class="world-page-reader__actions">
        <button type="button" class="btn btn-sm btn-ghost world-page-reader__back" data-action="world-reader-back" @click="emit('back')">返回资料库</button>
        <button type="button" class="btn btn-sm btn-primary" data-action="world-reader-edit" @click="emit('edit')">编辑</button>
      </div>
    </header>

    <div class="world-page-reader__layout">
      <nav v-if="tocEntries.length > 1" class="world-page-reader__toc" aria-label="标题目录">
        <strong>本页目录</strong>
        <button
          v-for="entry in tocEntries"
          :key="entry.id"
          type="button"
          data-action="world-reader-toc"
          @click="scrollTo(entry.id)"
        >{{ entry.label }}</button>
      </nav>

      <div class="world-page-reader__content">
        <section v-if="String(source?.free_text || '').trim()" id="reader-overview" class="world-page-reader__block">
          <h3>页面概览</h3>
          <RpMarkdownContent :source="source.free_text" class="world-page-reader__markdown" />
        </section>

        <p v-if="!String(source?.free_text || '').trim() && !visibleSections.length" class="world-page-reader__empty">
          这一页还没有正文；点击“编辑”开始撰写。
        </p>

        <section
          v-for="section in visibleSections"
          :id="`reader-section-${section.section_id}`"
          :key="section.section_id"
          class="world-page-reader__block world-page-reader__section"
        >
          <button
            type="button"
            class="world-page-reader__section-head"
            :aria-expanded="isCollapsed(section.section_id) ? 'false' : 'true'"
            data-action="world-reader-toggle"
            @click="toggleSection(section.section_id)"
          >
            <span aria-hidden="true">{{ isCollapsed(section.section_id) ? '▸' : '▾' }}</span>
            <strong>{{ section.title }}</strong>
            <small>{{ sectionKindLabel(section) }}</small>
          </button>
          <div v-if="!isCollapsed(section.section_id)" class="world-page-reader__section-body">
            <RpMarkdownContent :source="section.body_markdown || ''" class="world-page-reader__markdown" />
          </div>
        </section>

        <section v-if="visibleRefs.length" class="world-page-reader__refs" aria-label="引用的资料">
          <h3>引用的资料</h3>
          <ul>
            <li v-for="item in visibleRefs" :key="`${item.kind}:${item.id}`" :data-ref-kind="item.kind">
              <span :class="{ 'world-page-reader__ref--unavailable': item.unavailable }">{{ item.label }}</span>
              <small v-if="item.unavailable">（不可用引用）</small>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.world-page-reader { display: grid; gap: 14px; }
.world-page-reader__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.world-page-reader__header h2 { margin: 0; font-size: var(--text-lg); }
.world-page-reader__meta { margin: 6px 0 0; color: var(--text-secondary); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.world-page-reader__actions { display: flex; gap: 8px; flex-shrink: 0; }
.world-page-reader__layout { display: grid; grid-template-columns: 208px minmax(0, 1fr); gap: 20px; align-items: start; }
.world-page-reader__toc { position: sticky; top: 12px; display: grid; gap: 2px; max-height: calc(100vh - 160px); overflow-y: auto; }
.world-page-reader__toc strong { padding: 6px 8px; font-size: 12px; color: var(--text-muted); }
.world-page-reader__toc button { display: block; min-height: 36px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text-secondary); padding: 6px 8px; text-align: left; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-page-reader__toc button:hover { color: var(--text-primary); background: var(--bg-hover); }
.world-page-reader__toc button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-page-reader__content { display: grid; gap: 14px; min-width: 0; max-width: 76ch; }
.world-page-reader__block { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 14px 18px; }
.world-page-reader__block > h3 { margin: 0 0 8px; font-size: var(--text-md); }
.world-page-reader__section { padding: 0; }
.world-page-reader__section-head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; min-height: 48px; border: 0; background: transparent; padding: 12px 16px; color: var(--text-primary); text-align: left; cursor: pointer; }
.world-page-reader__section-head:hover { background: var(--bg-hover); }
.world-page-reader__section-head:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.world-page-reader__section-head small { color: var(--text-muted); }
.world-page-reader__section-body { padding: 0 16px 14px; border-top: 1px solid var(--border); }
.world-page-reader__section-body .world-page-reader__markdown { padding-top: 12px; }
.world-page-reader__markdown { color: var(--text-primary); line-height: 1.7; }
.world-page-reader__empty { color: var(--text-muted); margin: 0; }
.world-page-reader__refs { border-top: 1px dashed var(--border); padding-top: 10px; }
.world-page-reader__refs h3 { margin: 0 0 8px; font-size: var(--text-sm); color: var(--text-secondary); }
.world-page-reader__refs ul { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-page-reader__refs li { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; background: var(--bg-panel); }
.world-page-reader__refs small { color: var(--text-muted); }
.world-page-reader__ref--unavailable { color: var(--text-muted); text-decoration: line-through; }
@media (max-width: 960px) {
  .world-page-reader__layout { grid-template-columns: minmax(0, 1fr); }
  .world-page-reader__toc { position: static; max-height: none; display: flex; flex-wrap: wrap; gap: 6px; }
  .world-page-reader__toc strong { width: 100%; }
}
@media (max-width: 760px) {
  .world-page-reader__header { flex-direction: column; }
  .world-page-reader__actions { width: 100%; }
  .world-page-reader__actions .btn { min-height: 44px; }
  .world-page-reader__toc button { min-height: 44px; }
  .world-page-reader__section-head { min-height: 48px; }
}
</style>
