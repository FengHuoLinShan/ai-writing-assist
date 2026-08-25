<script setup>
import { computed } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"
import { isWorldObjectRef } from "../useEvidenceDrawer.js"
import { ragSearchSession } from "../ragSearchSession.js"

/**
 * 证据抽屉 — 状态与动作由 useEvidenceDrawer（父组件）驱动。
 * 复用全站模态焦点管理，保留 #rag-evidence-drawer 与 data-action 契约。
 */
const props = defineProps({
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
const requestClose = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({
  isOpen: () => props.open,
  requestClose,
})

const heading = computed(() => {
  if (props.loading) return props.loading === "追踪中" ? "正在追踪原文证据" : "正在读取原文"
  if (props.content?.type === "error") return "证据暂时无法打开"
  return props.content?.title || "证据详情"
})

const detailFields = [
  ["摘要", "summary"],
  ["公开信息", "public_info"],
  ["隐藏真相", "hidden_truth"],
  ["目标", "goal"],
  ["核心冲突", "core_conflict"],
  ["人物所知", "known_content"],
  ["别名", "aliases"],
]

const objectDetails = computed(() => detailFields.flatMap(([label, key]) => {
  const value = props.content?.item?.[key]
  if (Array.isArray(value)) return value.length ? [{ label, value: value.join("、") }] : []
  return typeof value === "string" && value.trim() ? [{ label, value: value.trim() }] : []
}))

function refLabel(ref, index) {
  const isScene = ref.target_type === "outline_scene"
  return ref.target_name || ref.name || (isScene ? `场景 ${index + 1}` : `关联对象 ${index + 1}`)
}

function precisionLabel(value) {
  return value === "exact" ? "精确位置" : value === "range" ? "相关片段" : "原文位置"
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="overlayRef"
      class="rag-evidence-overlay"
      @keydown="onKeydown"
      @focusin="onFocusin"
      @click.self="requestClose"
    >
      <aside
        id="rag-evidence-drawer"
        ref="dialogRef"
        class="novel-evidence-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rag-evidence-drawer-title"
        :aria-busy="Boolean(loading)"
        tabindex="-1"
      >
        <header class="novel-evidence-drawer__header">
          <div>
            <span class="novel-evidence-drawer__eyebrow">查找证据</span>
            <h2 id="rag-evidence-drawer-title">{{ heading }}</h2>
          </div>
          <button type="button" class="btn btn-sm" data-action="close-drawer" autofocus @click="requestClose">关闭</button>
        </header>

        <div class="novel-evidence-drawer__body modal-body">
          <div v-if="loading" class="novel-evidence-loading" role="status" aria-live="polite">
            <span class="sr-only">{{ loading }}</span>
            <div class="skeleton novel-evidence-loading__heading" aria-hidden="true"></div>
            <div class="skeleton novel-evidence-loading__line" aria-hidden="true"></div>
            <div class="skeleton novel-evidence-loading__line novel-evidence-loading__line--short" aria-hidden="true"></div>
          </div>

          <template v-else-if="content && content.type === 'chapter'">
            <p class="novel-evidence-source-meta">第 {{ content.chapterIndex }} 章 · v{{ content.versionNumber }}</p>
            <div class="novel-evidence-text">{{ content.before }}<mark>{{ content.mark }}</mark>{{ content.after }}</div>
            <button type="button" class="btn btn-sm" data-action="navigate-chapter-ref" :data-chapter-index="content.chapterIndex" @click="emit('navigate-chapter', content.chapterIndex)">跳转章节</button>
            <div v-if="session.drawerRefs.length" class="novel-evidence-links">
              <template v-for="(ref, index) in session.drawerRefs" :key="index">
                <button v-if="ref.target_type !== 'outline_scene'" type="button" class="btn btn-sm" data-action="trace-drawer-ref" :data-ref-index="index" @click="emit('trace', index)">查看{{ refLabel(ref, index) }}的证据</button>
                <button v-if="ref.target_type === 'outline_scene'" type="button" class="btn btn-sm" data-action="navigate-scene-ref" :data-ref-index="index" @click="emit('navigate-scene', index)">跳转 {{ refLabel(ref, index) }}</button>
                <button v-else-if="isWorldObjectRef(ref)" type="button" class="btn btn-sm" data-action="navigate-object-ref" :data-ref-index="index" @click="emit('navigate-object', index)">跳转{{ refLabel(ref, index) }}</button>
              </template>
            </div>
            <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
          </template>

          <template v-else-if="content && content.type === 'object'">
            <dl v-if="objectDetails.length" class="novel-evidence-object">
              <template v-for="detail in objectDetails" :key="detail.label">
                <dt>{{ detail.label }}</dt>
                <dd>{{ detail.value }}</dd>
              </template>
            </dl>
            <p v-else class="rag-search-empty">已找到这个对象，但目前没有可展示的摘要。</p>
            <div class="novel-evidence-links">
              <button type="button" class="btn btn-sm" data-action="trace-drawer-ref" data-ref-index="0" @click="emit('trace', 0)">追踪原文证据（{{ content.evidenceCount }}）</button>
              <button v-if="content.isWorldObject" type="button" class="btn btn-sm" data-action="navigate-object-ref" data-ref-index="0" @click="emit('navigate-object', 0)">跳转世界对象</button>
            </div>
            <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
          </template>

          <template v-else-if="content && content.type === 'trace'">
            <article v-for="(link, index) in content.links" :key="index" class="novel-evidence-trace">
              <p>{{ link.read?.text || (link.status === "needs_review" ? "待人工定位原文" : "") }}</p>
              <small>第 {{ link.source_ref?.chapter_index || "-" }} 章 · {{ precisionLabel(link.precision) }}</small>
            </article>
            <p v-if="!content.links.length" class="rag-search-empty">该对象暂未建立当前视角可见的原文证据；本次检索命中的原文仍可从结果卡“阅读原文”查看。</p>
            <p v-for="(warning, index) in content.warnings" :key="index" class="rag-diagnostics-warning">{{ warning }}</p>
          </template>

          <p v-else-if="content && content.type === 'error'" class="rag-error-text" role="alert">{{ content.message }}</p>
        </div>
      </aside>
    </div>
  </Teleport>
</template>
