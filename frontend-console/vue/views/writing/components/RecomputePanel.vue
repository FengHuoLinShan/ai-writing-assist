<template>
  <section class="writing-recompute-panel" aria-label="受影响内容与重算选项">
    <header class="writing-recompute-panel__head">
      <div>
        <span class="writing-recompute-panel__kicker">保存后的影响</span>
        <h4>受影响的内容</h4>
        <p>{{ notice.headline }}</p>
        <p v-if="notice.hasUnknownScope" class="writing-recompute-panel__unknown">
          部分影响范围待核实：下面标为「待核实」的条目没有登记依据，系统按保守方式把它们一并标记，重算前会再核对。
        </p>
      </div>
      <button type="button" class="btn btn-sm writing-recompute-panel__close" :disabled="adopting" @click="$emit('close')">
        {{ adopting ? '重算进行中…' : '暂不重算' }}
      </button>
    </header>

    <ul v-if="notice.entries.length" class="writing-recompute-panel__entries">
      <li v-for="entry in notice.entries" :key="entry.key">
        <em class="writing-recompute-panel__badge" :class="entry.basis === 'unknown' ? 'is-unknown' : 'is-known'">
          {{ entry.basis === 'unknown' ? '待核实' : '已知' }}
        </em>
        <span class="writing-recompute-panel__entry-main">
          <strong>{{ entry.scopeLabel }}</strong> · {{ entry.consumerLabel }}
          <small>{{ entry.reasonLabel }}</small>
          <small v-if="entry.note">{{ entry.note }}</small>
        </span>
      </li>
    </ul>
    <p v-else class="writing-recompute-panel__empty">
      暂时列不出具体条目；这不代表没有影响，重算前会按保守方式再核对一遍。
    </p>

    <p v-if="notice.invalidatedLabels.length" class="writing-recompute-panel__meta">
      已标记失效：{{ notice.invalidatedLabels.join('、') }}。
    </p>
    <p v-if="notice.unsupportedLabels.length" class="writing-recompute-panel__meta">
      尚未接入依赖登记、无法自动核对：{{ notice.unsupportedLabels.join('、') }}；需要时请手动检查。
    </p>
    <details v-if="notice.coverageNote" class="writing-recompute-panel__coverage">
      <summary>范围说明</summary>
      <p>{{ notice.coverageNote }}</p>
    </details>

    <fieldset class="writing-recompute-panel__scopes" :disabled="adopting">
      <legend>选择重算方式</legend>
      <label v-for="choice in scopeChoices" :key="choice.kind" class="writing-recompute-panel__scope">
        <input
          type="radio"
          name="writing-recompute-scope"
          :value="choice.kind"
          :checked="scope === choice.kind"
          :disabled="adopting"
          @change="chooseScope(choice.kind)"
        />
        <span class="writing-recompute-panel__scope-main">
          <strong>{{ choice.label }}</strong>
          <small>{{ choice.costNote }}</small>
          <small>{{ choice.effectNote }}</small>
        </span>
      </label>
    </fieldset>

    <div class="writing-recompute-panel__actions">
      <button
        type="button"
        class="btn btn-sm"
        :disabled="!scope || adopting || previewing"
        @click="runPreview"
      >
        {{ previewing ? '正在核对…' : '预览这次重算' }}
      </button>
      <button
        v-if="preview"
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="adopting || editorDirty || !preview.executable"
        @click="confirmAdopt"
      >
        {{ adopting ? '正在执行…' : `按预览执行${preview.label}` }}
      </button>
    </div>
    <p v-if="editorDirty" class="writing-recompute-panel__meta">先保存当前修改，再执行重算。</p>

    <section v-if="previewError" class="writing-recompute-panel__state is-error" role="alert">
      <p>{{ previewError }}</p>
      <button type="button" class="btn btn-sm" :disabled="previewing || adopting" @click="runPreview">重试预览</button>
    </section>

    <section v-if="preview && !previewError" class="writing-recompute-panel__preview" aria-label="重算预览">
      <h5>{{ preview.label }} · 预览</h5>
      <p>{{ preview.costNote }}</p>
      <p>{{ preview.effectNote }}</p>
      <p v-if="preview.targets.length">将处理：{{ preview.targets.join('、') }}。</p>
      <ul v-if="preview.actions.length" class="writing-recompute-panel__preview-actions">
        <li v-for="action in preview.actions" :key="action.key">
          <strong v-if="action.anchorLabel">{{ action.anchorLabel }}：</strong>{{ action.detail }}
        </li>
      </ul>
      <p v-if="!preview.executable" class="writing-recompute-panel__unsupported">
        需要你的明确确认与生成额度，当前不可自动执行：正文重生成请经写作伙伴的生成入口操作，本面板只说明范围与成本。
      </p>
      <p class="writing-recompute-panel__readonly">预览只核对范围与成本，不会改动任何内容；执行后旧结果与确认历史都保留。</p>
    </section>

    <section v-if="adoptError && !conflict" class="writing-recompute-panel__state is-error" role="alert">
      <p>{{ adoptError }}</p>
      <button type="button" class="btn btn-sm" :disabled="adopting" @click="confirmAdopt">重试执行</button>
    </section>

    <section v-if="conflict" class="writing-recompute-panel__conflict" aria-label="重算依据已变化">
      <h5>重算依据的内容已经变化</h5>
      <p>{{ conflict.message }}</p>
      <p v-if="conflict.rows.length">逐章核对（预览时 vs 当前）：</p>
      <ul v-if="conflict.rows.length" class="writing-recompute-panel__conflict-rows">
        <li v-for="row in conflict.rows" :key="row.chapterIndex">{{ row.label }}</li>
      </ul>
      <p class="writing-recompute-panel__meta">
        为避免覆盖，你的当前稿已原样保留；如仍要重算，请基于当前稿重新预览。
      </p>
      <div class="writing-recompute-panel__actions">
        <button type="button" class="btn btn-sm" :disabled="previewing || adopting" @click="runPreview">基于当前稿重新预览</button>
        <button type="button" class="btn btn-sm" @click="keepCurrentDraft">保留当前稿，暂不重算</button>
      </div>
      <p class="writing-recompute-panel__readonly">保留当前稿不会改动任何内容；之前的失效提示与本地回执仍保留可查。</p>
    </section>

    <p v-if="outcome" class="writing-recompute-panel__outcome" role="status">
      已完成{{ outcome.label }}（共 {{ outcome.handledCount }} 项）；旧结果与确认历史都保留。
    </p>

    <details class="writing-recompute-panel__history">
      <summary>本次会话的重算回执</summary>
      <ul v-if="historyItems.length">
        <li v-for="item in historyItems" :key="item.key">
          {{ item.label }} · 共 {{ item.handledCount }} 项 · {{ formatTime(item.rememberedAt) }}
        </li>
      </ul>
      <p v-else>本次写作会话里还没有执行过重算。</p>
      <p class="writing-recompute-panel__meta">
        回执只在本页会话内记录，刷新后不保留；如需核对同一操作的结果，用同一确认重试即可，不会重复执行。
      </p>
    </details>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getToast, registerAuxiliaryLeaveGuard } from "../../../bridge/index.js"
import {
  RECOMPUTE_SCOPES,
  driftRowLabel,
  listRecomputeReceipts,
  normalizeRecomputeOutcome,
  normalizeRecomputePreview,
  normalizeRecomputeDriftContext,
  recomputeAdoptPayload,
  recomputeOperationKey,
  recomputeConflictKind,
  recomputeRequestPayload,
  rememberRecomputeReceipt,
} from "../invalidationModel.js"

const props = defineProps({
  projectId: { type: String, default: null },
  chapterIndex: { type: Number, default: null },
  notice: { type: Object, required: true },
  editorDirty: { type: Boolean, default: false },
})
defineEmits(["close"])

const scope = ref("")
const operationId = ref("")
const preview = ref(null)
const previewing = ref(false)
const previewError = ref("")
const adopting = ref(false)
const adoptError = ref("")
const outcome = ref(null)
const conflict = ref(null)
const receiptVersion = ref(0)
let generation = 0

const scopeChoices = computed(() => RECOMPUTE_SCOPES.filter(
  (choice) => props.notice.recomputeOptions.includes(choice.kind),
))

const historyItems = computed(() => {
  void receiptVersion.value
  return listRecomputeReceipts(props.projectId)
})

function resetForNotice() {
  generation += 1
  scope.value = ""
  operationId.value = ""
  preview.value = null
  previewError.value = ""
  adoptError.value = ""
  conflict.value = null
  outcome.value = null
}

watch(() => props.notice, resetForNotice)

function chooseScope(kind) {
  if (adopting.value) return
  scope.value = kind
  operationId.value = recomputeOperationKey()
  preview.value = null
  previewError.value = ""
  adoptError.value = ""
  conflict.value = null
  outcome.value = null
}

function currentApi() {
  const api = getApi()?.evolution
  if (!api?.recomputePreview || !api?.recomputeExecute) {
    throw new Error("重算功能暂时不可用，请稍后再试。")
  }
  return api
}

async function runPreview() {
  if (!scope.value || previewing.value || adopting.value) return
  const token = generation
  previewing.value = true
  previewError.value = ""
  preview.value = null
  adoptError.value = ""
  conflict.value = null
  try {
    const payload = buildBasePayload()
    if (!payload) throw new Error("当前缺少章节信息，暂时无法预览这次重算。")
    const raw = await currentApi().recomputePreview(props.projectId, payload)
    if (token !== generation) return
    const normalized = normalizeRecomputePreview(raw, { scope: scope.value })
    if (!normalized) throw new Error("预览信息暂时无法解读，请稍后再试。")
    preview.value = normalized
  } catch (error) {
    if (token === generation) previewError.value = error?.message || "预览暂时失败，可以稍后重试。"
  } finally {
    if (token === generation) previewing.value = false
  }
}

function buildBasePayload() {
  return recomputeRequestPayload({
    novelId: props.projectId,
    scope: scope.value,
    notice: props.notice,
    operationId: operationId.value,
  })
}

async function confirmAdopt() {
  if (!scope.value || adopting.value || props.editorDirty || !preview.value || !preview.value.executable) return
  const token = generation
  adopting.value = true
  adoptError.value = ""
  conflict.value = null
  try {
    const payload = recomputeAdoptPayload({
      novelId: props.projectId,
      scope: scope.value,
      notice: props.notice,
      operationId: operationId.value,
      expectedSourceDigest: preview.value.sourceDigest,
    })
    if (!payload) throw new Error("当前缺少章节信息，暂时无法执行重算。")
    // 同一 operation_id 贯穿预览与执行（幂等对）；失败重试也复用同一键与来源指纹。
    const raw = await currentApi().recomputeExecute(props.projectId, operationId.value, payload)
    if (token !== generation) return
    const normalized = normalizeRecomputeOutcome(raw)
    if (!normalized) throw new Error("执行结果暂时无法解读；同一确认重试不会执行两次。")
    outcome.value = normalized
    preview.value = null
    rememberRecomputeReceipt(props.projectId, normalized)
    receiptVersion.value += 1
    getToast()("重算已完成，旧结果与确认历史都保留可查。", "success")
  } catch (error) {
    if (token !== generation) return
    const kind = recomputeConflictKind(error)
    if (kind === "source_drift") {
      const drift = normalizeRecomputeDriftContext(error, {
        previewChapters: preview.value?.sourceChapters || {},
      })
      conflict.value = {
        message: error?.message || "重算目标章节在预览后已再次修改。",
        rows: drift.rows.map((row) => ({ ...row, label: driftRowLabel(row) })),
        keepCurrentDraft: drift.keepCurrentDraft,
      }
      preview.value = null
    } else if (kind === "scope_unsupported") {
      adoptError.value = "正文重生成需要你的明确确认与生成额度，当前不可自动执行；请经写作伙伴的生成入口操作。"
      preview.value = null
    } else {
      adoptError.value = error?.message || "执行暂时失败，可以重试；同一确认重复发送不会执行两次。"
    }
  } finally {
    if (token === generation) adopting.value = false
  }
}

function keepCurrentDraft() {
  // 保留当前稿：零写入、零请求；回到选择状态，失效提示与本地回执保留可查。
  conflict.value = null
  adoptError.value = ""
  preview.value = null
  scope.value = ""
  operationId.value = ""
}

function formatTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

function canLeave() {
  return !adopting.value
}
defineExpose({ canLeave })

const unregisterGuard = registerAuxiliaryLeaveGuard(() => canLeave())
function beforeUnload(event) {
  if (adopting.value) {
    event.preventDefault()
    event.returnValue = ""
  }
}
globalThis.addEventListener?.("beforeunload", beforeUnload)
onBeforeUnmount(() => {
  generation += 1
  unregisterGuard()
  globalThis.removeEventListener?.("beforeunload", beforeUnload)
})
</script>

<style scoped>
.writing-recompute-panel {
  margin: 0 0 14px;
  padding: 12px 14px;
  border: 1px solid var(--border-color, var(--border));
  border-radius: 8px;
  background: var(--bg-muted, var(--bg-primary));
  display: grid;
  gap: 10px;
  min-width: 0;
  font-size: 13px;
  line-height: 1.7;
}
.writing-recompute-panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.writing-recompute-panel__head h4 { margin: 2px 0; font-size: 16px; }
.writing-recompute-panel__head p { margin: 2px 0; overflow-wrap: anywhere; }
.writing-recompute-panel__kicker { font-size: 11px; letter-spacing: .09em; color: var(--text-secondary); }
.writing-recompute-panel__unknown { color: var(--text-secondary); }
.writing-recompute-panel__entries { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.writing-recompute-panel__entries li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg-primary, var(--bg-base));
  border: 1px solid var(--border-color, var(--border));
  border-radius: 6px;
  min-width: 0;
}
.writing-recompute-panel__badge { flex: none; font-style: normal; padding: 0 6px; border-radius: 8px; font-size: 12px; }
.writing-recompute-panel__badge.is-known { background: rgba(46, 125, 80, 0.16); }
.writing-recompute-panel__badge.is-unknown { background: rgba(176, 132, 32, 0.2); }
.writing-recompute-panel__entry-main { min-width: 0; overflow-wrap: anywhere; }
.writing-recompute-panel__entry-main small { display: block; color: var(--text-secondary); }
.writing-recompute-panel__empty, .writing-recompute-panel__meta, .writing-recompute-panel__readonly, .writing-recompute-panel__unsupported {
  margin: 0;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.writing-recompute-panel__unsupported { color: inherit; }
.writing-recompute-panel__coverage summary { cursor: pointer; color: var(--text-secondary); }
.writing-recompute-panel__scopes { border: 1px solid var(--border-color, var(--border)); border-radius: 6px; padding: 8px 10px; }
.writing-recompute-panel__scope { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; min-width: 0; }
.writing-recompute-panel__scope-main { display: grid; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
.writing-recompute-panel__scope-main small { color: var(--text-secondary); }
.writing-recompute-panel__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.writing-recompute-panel__actions .btn { min-height: 34px; }
.writing-recompute-panel__preview, .writing-recompute-panel__conflict, .writing-recompute-panel__state {
  border-left: 3px solid var(--accent, var(--primary));
  padding: 8px 10px;
  background: var(--bg-primary, var(--bg-base));
  display: grid;
  gap: 4px;
}
.writing-recompute-panel__preview h5, .writing-recompute-panel__conflict h5 { margin: 0; font-size: 14px; }
.writing-recompute-panel__preview p, .writing-recompute-panel__conflict p { margin: 0; overflow-wrap: anywhere; }
.writing-recompute-panel__preview-actions { margin: 0; padding-left: 18px; overflow-wrap: anywhere; }
.writing-recompute-panel__state.is-error { border-left-color: var(--danger); color: inherit; }
.writing-recompute-panel__conflict { border-left-color: #b08420; }
.writing-recompute-panel__conflict-rows { margin: 0; padding-left: 18px; overflow-wrap: anywhere; }
.writing-recompute-panel__outcome { margin: 0; }
.writing-recompute-panel__history summary { cursor: pointer; color: var(--text-secondary); }
.writing-recompute-panel__history ul { margin: 6px 0 0; padding-left: 18px; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .writing-recompute-panel { padding: 10px; }
  .writing-recompute-panel__actions { display: grid; grid-template-columns: minmax(0, 1fr); }
}
</style>
