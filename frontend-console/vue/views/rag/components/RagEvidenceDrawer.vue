<script setup>
import { isWorldObjectRef } from "../useEvidenceDrawer.js"
import { ragSearchSession } from "../ragSearchSession.js"

/**
 * 证据抽屉 — DOM 契约对齐 vanilla 的 #rag-evidence-drawer 各内容形态。
 * 状态（open/loading/content）与动作由 useEvidenceDrawer（父组件）驱动。
 */
defineProps({
  open: { type: Boolean, default: false },
  loading: { type: String, default: "" },
  content: { type: Object, default: null },
})

const emit = defineEmits([
  "close",
  "trace",
  "navigate-object",
  "navigate-scene",
  "navigate-chapter",
])

const session = ragSearchSession

function refLabel(ref, index) {
  const isScene = ref.target_type === "outline_scene"
  return ref.target_name || ref.name || (isScene ? `场景 ${index + 1}` : `关联对象 ${index + 1}`)
}
</script>

<template>
  <aside id="rag-evidence-drawer" class="novel-evidence-drawer" :hidden="!open">
    <div v-if="loading" class="loading">{{ loading }}</div>

    <template v-else-if="content && content.type === 'chapter'">
      <div class="novel-evidence-drawer__header">
        <strong>{{ content.title }}</strong>
        <button class="btn btn-sm" data-action="close-drawer" @click="emit('close')">关闭</button>
      </div>
      <p class="novel-evidence-source-meta">第 {{ content.chapterIndex }} 章 · v{{ content.versionNumber }}</p>
      <div class="novel-evidence-text">{{ content.before }}<mark>{{ content.mark }}</mark>{{ content.after }}</div>
      <button class="btn btn-sm" data-action="navigate-chapter-ref" :data-chapter-index="content.chapterIndex" @click="emit('navigate-chapter', content.chapterIndex)">跳转章节</button>
      <div v-if="session.drawerRefs.length" class="novel-evidence-links">
        <template v-for="(ref, index) in session.drawerRefs" :key="index">
          <button v-if="ref.target_type !== 'outline_scene'" class="btn btn-sm" data-action="trace-drawer-ref" :data-ref-index="index" @click="emit('trace', index)">查看{{ refLabel(ref, index) }}的证据</button>
          <button v-if="ref.target_type === 'outline_scene'" class="btn btn-sm" data-action="navigate-scene-ref" :data-ref-index="index" @click="emit('navigate-scene', index)">跳转 {{ refLabel(ref, index) }}</button>
          <button v-else-if="isWorldObjectRef(ref)" class="btn btn-sm" data-action="navigate-object-ref" :data-ref-index="index" @click="emit('navigate-object', index)">跳转{{ refLabel(ref, index) }}</button>
        </template>
      </div>
      <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
    </template>

    <template v-else-if="content && content.type === 'object'">
      <div class="novel-evidence-drawer__header">
        <strong>{{ content.title }}</strong>
        <button class="btn btn-sm" data-action="close-drawer" @click="emit('close')">关闭</button>
      </div>
      <pre class="novel-evidence-object">{{ content.itemJson }}</pre>
      <button class="btn btn-sm" data-action="trace-drawer-ref" data-ref-index="0" @click="emit('trace', 0)">追踪原文证据（{{ content.evidenceCount }}）</button>
      <button v-if="content.isWorldObject" class="btn btn-sm" data-action="navigate-object-ref" data-ref-index="0" @click="emit('navigate-object', 0)">跳转世界对象</button>
      <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
    </template>

    <template v-else-if="content && content.type === 'trace'">
      <div class="novel-evidence-drawer__header">
        <strong>{{ content.title }}</strong>
        <button class="btn btn-sm" data-action="close-drawer" @click="emit('close')">关闭</button>
      </div>
      <article v-for="(link, index) in content.links" :key="index" class="novel-evidence-trace">
        <p>{{ link.read?.text || (link.status === "needs_review" ? "待人工定位原文" : "") }}</p>
        <small>第 {{ link.source_ref?.chapter_index || "-" }} 章 · {{ link.precision || "range" }}</small>
      </article>
      <p v-if="!content.links.length" class="rag-search-empty">该对象暂未建立当前视角可见的原文证据；本次检索命中的原文仍可从结果卡“阅读原文”查看。</p>
      <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
    </template>

    <template v-else-if="content && content.type === 'error'">
      <p class="rag-error-text">{{ content.message }}</p>
    </template>
  </aside>
</template>
