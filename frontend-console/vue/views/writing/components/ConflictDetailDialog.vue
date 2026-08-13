<template>
  <div
    v-if="model.open"
    ref="overlayRef"
    class="modal-overlay"
    @keydown="onKeydown"
    @focusin="onFocusin"
  >
    <div ref="dialogRef" class="modal-content modal-content--wide writing-conflict-modal" role="dialog" aria-modal="true" aria-label="剧情设定冲突检查" aria-labelledby="conflict-detail-dialog-title" :aria-busy="model.busy" tabindex="-1">
      <div class="modal-header">
        <h3 id="conflict-detail-dialog-title">剧情设定冲突检查</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
      </div>
      <div class="modal-body">
        <p v-if="model.error" class="writing-conflict-empty is-error" role="alert">{{ model.error }}</p>
        <p v-if="!check" class="writing-conflict-empty">暂无检查记录</p>
        <template v-else>
          <div class="writing-conflict-modal__meta">
            <span>检查范围：第 {{ check.chapter_index || '-' }} 章</span>
            <span>来源版本：{{ sourceVersionLabel }}</span>
            <span>定向复检：{{ recheckScopeLabel }}</span>
            <span>问题 {{ items.length }} 条</span>
            <span v-if="check.include_candidates" class="pill pill-warning">包含待处理内容
            </span>
          </div>

          <p v-if="check.status === 'degraded'" class="writing-conflict-empty" role="status" data-author-action="needs_decision">
            <strong>需要决定</strong> · 本次检查未覆盖{{ degradedSourceLabels }}；请决定是否先重新运行当前范围的检查。
          </p>

          <section class="writing-conflict-group">
            <div class="writing-conflict-group__head">
              <strong>规则命中</strong>
              <span>{{ ruleItems.length }} 条</span>
            </div>
            <ConflictRows
              :items="ruleItems"
              :busy="model.busy"
              :drafts="suggestionDrafts"
              @status="forwardStatus"
              @suggestion="forwardSuggestion"
              @apply="forwardApply"
              @locate="$emit('locate', $event)"
              @source="$emit('source', $event)"
              @update-draft="updateDraft"
              @copy="copySuggestion"
            />
          </section>

          <section class="writing-conflict-group writing-conflict-group--ai">
            <div class="writing-conflict-group__head">
              <strong>AI 判断</strong>
              <span>{{ aiItems.length }} 条</span>
            </div>
            <div class="writing-conflict-ai-toolbar">
              <button
                type="button"
                class="btn btn-sm btn-primary"
                data-action="conflict-ai-review"
                :disabled="model.busy || check.ai_review_status === 'running'"
                @click="$emit('ai-review')"
              >补充 AI 软冲突判断</button>
              <span class="pill">状态：{{ aiReviewStatusLabel(check.ai_review_status) }}</span>
            </div>
            <ConflictRows
              :items="aiItems"
              :busy="model.busy"
              :drafts="suggestionDrafts"
              @status="forwardStatus"
              @suggestion="forwardSuggestion"
              @apply="forwardApply"
              @locate="$emit('locate', $event)"
              @source="$emit('source', $event)"
              @update-draft="updateDraft"
              @copy="copySuggestion"
            />
          </section>

          <aside v-if="model.sourcePreview" class="writing-conflict-source-modal" aria-label="冲突来源详情">
            <div class="writing-conflict-group__head">
              <strong>{{ model.sourcePreview.title || '来源详情' }}</strong>
              <button type="button" class="btn btn-sm" @click="$emit('dismiss-source')">收起</button>
            </div>
            <template v-if="model.sourcePreview.kind === 'memory'">
              <p><strong>章节</strong>：第 {{ model.sourcePreview.chapterIndex ?? '-' }} 章</p>
              <p><strong>角色</strong>：{{ model.sourcePreview.characterId || '-' }}</p>
            </template>
            <p v-else>{{ model.sourcePreview.message || '该来源暂无可打开视图' }}</p>
          </aside>
        </template>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-ghost" @click="requestClose">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, reactive, watch } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"

const props = defineProps({
  model: {
    type: Object,
    default: () => ({ open: false, check: null, busy: false, error: null, sourcePreview: null }),
  },
})
const emit = defineEmits(["close", "status", "ai-review", "suggestion", "apply", "locate", "source", "dismiss-source"])
const requestClose = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({
  isOpen: () => props.model.open,
  requestClose,
  canClose: () => true,
})

const severityLabels = { high: "高", medium: "中", low: "低", info: "提示" }
const statusLabels = { open: "未处理", resolved: "已处理", ignored: "忽略", later: "稍后" }
const kindLabels = {
  forbidden_present: "禁止项出现在正文",
  required_missing: "必须发生项缺失",
  continuity_location_mismatch: "前后连续性风险",
  motivation_gap: "动机衔接风险",
  emotion_jump: "情绪跳变",
  foreshadowing_misfire: "伏笔承接风险",
  premature_reveal: "过早揭示",
  implicit_lore_conflict: "隐含设定风险",
  voice_or_pov_drift: "声音/视角漂移",
  scene_goal_drift: "场景目标偏离",
  scene_commitment_missing: "场景必要承诺缺失",
  scene_forbidden_deviation: "场景出现禁止偏离内容",
  continuity_soft_risk: "软连续性风险",
}

const authorActionLabels = {
  needs_decision: { key: "needs_decision", label: "需要决定", className: "pill pill-warning" },
  can_improve: { key: "can_improve", label: "可以改进", className: "pill" },
}

function authorActionOf(item) {
  if ((item.status || "open") !== "open") return null
  if (item.is_ai_judgment) {
    return item.needs_review ? authorActionLabels.needs_decision : authorActionLabels.can_improve
  }
  return authorActionLabels.needs_decision
}

function parseSuggestion(value) {
  if (value && typeof value === "object") return { suggested_text: value.suggested_text ?? "", ...value }
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === "object" ? { suggested_text: "", ...parsed } : { suggested_text: value || "" }
  } catch {
    return { suggested_text: value || "" }
  }
}

function humanReason(value) {
  return String(value || "").replaceAll("_", " ")
}

const ConflictRows = defineComponent({
  name: "ConflictRows",
  props: {
    items: { type: Array, default: () => [] },
    busy: Boolean,
    drafts: { type: Object, required: true },
  },
  emits: ["status", "suggestion", "apply", "locate", "source", "update-draft", "copy"],
  setup(rowProps, { emit: rowEmit }) {
    const button = (label, attrs, handler) => h("button", {
      type: "button",
      class: attrs.primary ? "btn btn-sm btn-primary" : "btn btn-sm",
      disabled: rowProps.busy || attrs.disabled,
      "data-action": attrs.action,
      onClick: attrs.disabled ? undefined : handler,
    }, label)
    const itemView = (item) => {
      const location = item.location_json || {}
      const source = location.source || {}
      const target = location.open_target || {}
      const textRange = location.text_range || location
      const canLocate = Number.isFinite(Number(textRange.start))
      const canOpenSource = target.kind === "text_range"
        ? canLocate
        : item.source_module === "world"
          || target.kind === "outline_scene"
          || item.source_module === "outline"
          || target.kind === "memory_chapter"
      const reason = humanReason(location.needs_review_reason || item.needs_review_reason)
      const authorAction = authorActionOf(item)
      const suggestion = item.ai_suggestion ? parseSuggestion(item.ai_suggestion) : null
      const evidence = source.module || source.label || source.field || source.type || source.excerpt || target.kind || reason
        ? h("details", { class: "writing-conflict-evidence-drawer" }, [
            h("summary", "证据"),
            h("div", { class: "writing-conflict-evidence-drawer__grid" }, [
              h("span", "模块"), h("strong", source.module || item.source_module || "-"),
              h("span", "来源"), h("strong", source.label || "-"),
              h("span", "字段"), h("strong", source.field || "-"),
              h("span", "类型"), h("strong", source.type || "-"),
              h("span", "摘录"), h("strong", source.excerpt || "-"),
              h("span", "注意原因"), h("strong", reason || "-"),
              h("span", "打开"), h("strong", target.kind || "-"),
            ]),
          ])
        : null
      const suggestionView = item.suggestion_status === "failed"
        ? h("div", { class: "writing-conflict-suggestion is-error" }, `AI 修复建议失败：${item.suggestion_error || "未知错误"}`)
        : suggestion
          ? h("div", { class: "writing-conflict-suggestion" }, [
              h("div", { class: "writing-conflict-suggestion__head" }, [
                h("strong", suggestion.strategy || "AI 修复建议"),
                button("复制", { action: "copy-conflict-suggestion" }, () => rowEmit("copy", item.id)),
                button("采用到工作稿", { action: "apply-conflict-suggestion", primary: true }, () => rowEmit("apply", item.id)),
              ]),
              h("textarea", {
                class: "form-textarea",
                rows: 4,
                "aria-label": `编辑 ${kindLabels[item.kind] || item.kind || "问题"} 的 AI 修复建议`,
                value: rowProps.drafts[item.id] ?? suggestion.suggested_text ?? "",
                onInput: (event) => rowEmit("update-draft", { itemId: item.id, text: event.target.value }),
              }),
              suggestion.rationale ? h("small", suggestion.rationale) : null,
              Array.isArray(suggestion.constraints) && suggestion.constraints.length ? h("small", `约束：${suggestion.constraints.join("；")}`) : null,
              Array.isArray(suggestion.risk_notes) && suggestion.risk_notes.length ? h("small", `注意：${suggestion.risk_notes.join("；")}`) : null,
            ])
          : null
      return h("article", { key: item.id, class: "writing-conflict-item", "data-conflict-item-id": item.id }, [
        h("div", { class: "writing-conflict-item__head" }, [
          authorAction ? h("span", {
            class: authorAction.className,
            "data-author-action": authorAction.key,
          }, authorAction.label) : null,
          h("span", { class: "badge badge-conflicted" }, severityLabels[item.severity] || item.severity || "-"),
          h("strong", kindLabels[item.kind] || item.kind || "问题"),
          h("span", { class: "pill" }, item.source_module || "-"),
          item.is_ai_judgment ? h("span", { class: "pill" }, "AI 判断") : null,
          item.needs_review ? h("span", { class: "pill pill-warning" }, "需要人工检查") : null,
          typeof item.confidence === "number" ? h("span", { class: "pill" }, `置信度 ${Math.round(item.confidence * 100)}%`) : null,
          h("span", { class: "writing-conflict-status" }, statusLabels[item.status] || item.status || "未处理"),
        ]),
        h("p", { class: "writing-conflict-evidence" }, item.evidence_summary || ""),
        item.llm_rationale ? h("p", { class: "writing-conflict-rationale" }, item.llm_rationale) : null,
        evidence,
        h("div", { class: "writing-conflict-actions" }, [
          button(canLocate ? "定位正文" : "无正文定位", { action: "locate-conflict", disabled: !canLocate }, () => rowEmit("locate", item.id)),
          button(canOpenSource ? "打开来源" : "无可打开来源", { action: "open-conflict-source", disabled: !canOpenSource }, () => rowEmit("source", item.id)),
          button("已处理", { action: "resolve-conflict" }, () => rowEmit("status", { itemId: item.id, status: "resolved" })),
          button("忽略", { action: "ignore-conflict" }, () => rowEmit("status", { itemId: item.id, status: "ignored" })),
          button("稍后", { action: "later-conflict" }, () => rowEmit("status", { itemId: item.id, status: "later" })),
          button("生成 AI 修复建议", { action: "generate-conflict-suggestion" }, () => rowEmit("suggestion", item.id)),
        ]),
        suggestionView,
      ])
    }
    return () => rowProps.items.length
      ? h("div", { class: "writing-conflict-list" }, rowProps.items.map(itemView))
      : h("div", { class: "writing-conflict-empty" }, "暂无记录")
  },
})

const check = computed(() => props.model.check)
const items = computed(() => Array.isArray(check.value?.items) ? check.value.items : [])
const sourceVersionLabel = computed(() => (
  Number(check.value?.version_number) >= 1 ? `工作稿 v${check.value.version_number}` : "当前编辑内容"
))
const recheckScopeLabel = computed(() => (
  check.value?.scene_id ? `第 ${check.value.chapter_index || "-"} 章当前场景` : `第 ${check.value?.chapter_index || "-"} 章`
))
const degradedSourceLabels = computed(() => {
  const labels = (check.value?.summary_json?.degraded_sources || []).map((source) => {
    if (String(source).startsWith("outline")) return "故事结构"
    if (String(source).startsWith("world.map")) return "地图资料"
    if (String(source).startsWith("memory")) return "场景记忆"
    return "部分来源"
  })
  return Array.from(new Set(labels)).join("、") || "部分来源"
})
const ruleItems = computed(() => items.value.filter((item) => !item.is_ai_judgment))
const aiItems = computed(() => items.value.filter((item) => item.is_ai_judgment))
const suggestionDrafts = reactive({})

watch(items, (nextItems) => {
  const present = new Set(nextItems.map((item) => String(item.id)))
  for (const key of Object.keys(suggestionDrafts)) if (!present.has(key)) delete suggestionDrafts[key]
  for (const item of nextItems) {
    if (item.ai_suggestion && suggestionDrafts[item.id] == null) {
      suggestionDrafts[item.id] = parseSuggestion(item.ai_suggestion).suggested_text ?? ""
    }
  }
}, { immediate: true })

function aiReviewStatusLabel(status) {
  return { not_requested: "未生成", running: "生成中", done: "已生成", partial: "部分生成", failed: "失败" }[status] || status || "未生成"
}
function updateDraft({ itemId, text }) { suggestionDrafts[itemId] = text }
function forwardStatus(value) { emit("status", value) }
function forwardSuggestion(itemId) { emit("suggestion", itemId) }
function forwardApply(itemId) { emit("apply", { itemId, text: suggestionDrafts[itemId] || "" }) }
async function copySuggestion(itemId) {
  const text = suggestionDrafts[itemId] || ""
  if (!text) return
  try { await navigator.clipboard?.writeText?.(text) } catch { /* Clipboard availability is optional. */ }
}
</script>
