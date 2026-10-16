<template>
  <dialog ref="dialog" class="chapter-order-dialog" aria-labelledby="chapter-order-title" @close="handleDialogClose">
    <div class="chapter-order-dialog__layout">
      <header class="chapter-order-dialog__header">
        <div>
          <p class="chapter-order-dialog__eyebrow">正文结构 · R3</p>
          <h2 id="chapter-order-title">章节顺序</h2>
          <p class="chapter-order-dialog__intro">调整正文目录顺序。所有版本和批注会随原章节移动；Story 的精确来源会迁移或在冲突时停止。</p>
        </div>
        <button type="button" class="btn btn-sm btn-ghost" aria-label="关闭章节顺序" @click="close">关闭</button>
      </header>

      <nav class="chapter-order-dialog__tabs" aria-label="章节顺序操作">
        <button type="button" class="btn btn-sm" :aria-pressed="tab === 'reorder'" @click="tab = 'reorder'">预览新顺序</button>
        <button type="button" class="btn btn-sm" :aria-pressed="tab === 'history'" @click="openHistory">历史与恢复</button>
      </nav>

      <aside v-if="targetProjectId && targetProjectId !== projectId" class="chapter-order-dialog__notice chapter-order-dialog__notice--warning" role="alert">
        <strong>当前项目已切换</strong>
        <p>这份章节顺序意图仍保留。返回原项目后可以继续；当前项目不会收到这项操作。</p>
      </aside>
      <p v-if="error" class="chapter-order-dialog__error" role="alert">{{ error }}</p>

      <section v-if="tab === 'reorder'" class="chapter-order-dialog__section" aria-labelledby="chapter-order-list-title">
        <div class="chapter-order-dialog__section-heading">
          <div>
            <h3 id="chapter-order-list-title">目标目录</h3>
            <p>用上移、下移按钮排列章节。编号空洞会保留，但内容会按此列表顺序重新分配到现有章节位置。</p>
          </div>
          <button type="button" class="btn btn-sm" :disabled="busy || !canUseTargetProject || !hasReorder" @click="requestPreview">
            {{ loadingPreview ? '正在核对…' : '预览影响' }}
          </button>
        </div>

        <ol class="chapter-order-list" aria-label="目标章节顺序">
          <li v-for="(chapter, index) in targetOrder" :key="chapter" class="chapter-order-row">
            <span class="chapter-order-row__position" :aria-label="`目标位置 ${index + 1}`">{{ index + 1 }}</span>
            <span class="chapter-order-row__chapter">
              <strong>第 {{ chapter }} 章</strong>
              <span>{{ labels[chapter]?.title || '未命名章节' }}</span>
              <small>{{ Number(labels[chapter]?.word_count || 0).toLocaleString() }} 字</small>
            </span>
            <span class="chapter-order-row__actions">
              <button type="button" class="btn btn-sm" :aria-label="`第 ${chapter} 章上移`" :disabled="busy || index === 0" @click="moveChapter(index, -1)">上移</button>
              <button type="button" class="btn btn-sm" :aria-label="`第 ${chapter} 章下移`" :disabled="busy || index === targetOrder.length - 1" @click="moveChapter(index, 1)">下移</button>
            </span>
          </li>
        </ol>
        <p v-if="!targetOrder.length" class="chapter-order-dialog__empty">当前作品没有可重排的正文章节。</p>

        <section v-if="preview" class="chapter-order-review" aria-labelledby="chapter-order-review-title" :aria-busy="busy ? 'true' : undefined">
          <header>
            <p class="chapter-order-dialog__eyebrow">预览已保存 · 作者确认前不会移动正文</p>
            <h3 id="chapter-order-review-title">确认前检查影响</h3>
          </header>
          <p class="chapter-order-review__summary">本操作会改变章节的实际正文位置，且可能改变 Story 对章节顺序的解释。请确认下列映射和待重验项。</p>

          <ol class="chapter-order-moves" aria-label="章节位置变化">
            <li v-for="move in preview.moves" :key="`${move.from_chapter_index}-${move.to_chapter_index}`">
              <strong>{{ move.title || `第 ${move.from_chapter_index} 章` }}</strong>
              <span>第 {{ move.from_chapter_index }} 章 → 第 {{ move.to_chapter_index }} 章</span>
              <small>{{ move.version_count }} 个版本{{ move.has_published_version ? ' · 含正式正文' : '' }}</small>
            </li>
          </ol>

          <dl class="chapter-order-impact">
            <div><dt>Scene 章节绑定</dt><dd>{{ Number(preview.story_impact?.scene_binding_count || 0) }}</dd></div>
            <div><dt>正文片段来源</dt><dd>{{ Number(preview.story_impact?.scene_span_count || 0) }}</dd></div>
            <div><dt>事实事件</dt><dd>{{ Number(preview.story_impact?.fact_event_count || 0) }} <span>历史事件保留，时间线按新顺序标待重验</span></dd></div>
            <div><dt>待重验计划</dt><dd>{{ Number(preview.story_impact?.plan_review_count || 0) }}</dd></div>
            <div><dt>失效快照与检查点</dt><dd>{{ Number(preview.story_impact?.snapshot_count || 0) + Number(preview.story_impact?.scene_checkpoint_count || 0) + Number(preview.story_impact?.scene_snapshot_count || 0) + Number(preview.story_impact?.scene_summary_count || 0) }}</dd></div>
          </dl>

          <section v-if="preview.story_impact?.plan_review_refs?.length" class="chapter-order-review__plans" aria-labelledby="chapter-order-plans-title">
            <h4 id="chapter-order-plans-title">章节锚点将迁移并待重验</h4>
            <ul>
              <li v-for="(item, index) in preview.story_impact.plan_review_refs" :key="`${item.target_type}-${item.target_id}-${index}`">
                <strong>{{ item.label || planTypeLabel(item.target_type) }}</strong>
                <span>{{ formatAnchors(item.before) }} → {{ formatAnchors(item.after) }}</span>
              </li>
            </ul>
          </section>

          <section v-if="preview.story_impact?.blockers?.length" class="chapter-order-blockers" aria-labelledby="chapter-order-blockers-title">
            <h4 id="chapter-order-blockers-title">这些来源无法安全迁移</h4>
            <ul>
              <li v-for="blocker in preview.story_impact.blockers" :key="blocker.kind">
                <strong>{{ blocker.message }}</strong>
                <small v-if="blocker.count">{{ blocker.count }} 项</small>
                <span v-for="(example, index) in blocker.examples || []" :key="`${blocker.kind}-${index}`">
                  {{ example.label || example.title || planTypeLabel(example.target_type || blocker.kind) }}
                  <template v-if="example.before && example.after"> · {{ formatAnchors(example.before) }} → {{ formatAnchors(example.after) }}</template>
                </span>
              </li>
            </ul>
          </section>

          <aside class="chapter-order-review__confirm" role="note">
            <strong>这是 R3 章节结构操作</strong>
            <p>确认后会原子移动全部版本、跟随章节的批注和 Story 章节绑定；旧事实事件与 Evolution 冻结记录保持不变。恢复也会先检查重排后是否出现了新编辑。</p>
            <button type="button" class="btn btn-primary" :disabled="busy || !canConfirm" @click="confirmOrder">
              {{ confirming ? '正在执行…' : '确认并重排章节' }}
            </button>
          </aside>
        </section>
      </section>

      <section v-else class="chapter-order-dialog__section" aria-labelledby="chapter-order-history-title">
        <div class="chapter-order-dialog__section-heading">
          <div>
            <h3 id="chapter-order-history-title">重排历史</h3>
            <p>可以恢复最近已执行的调整。恢复会重验正文、批注与 Story 来源，任何新编辑都会阻止覆盖。</p>
          </div>
          <button type="button" class="btn btn-sm" :disabled="busy || !canUseTargetProject" @click="loadHistory">{{ loadingHistory ? '正在读取…' : '刷新' }}</button>
        </div>
        <p v-if="!history.length && !loadingHistory" class="chapter-order-dialog__empty">还没有章节重排记录。</p>
        <ul v-else class="chapter-order-history">
          <li v-for="item in history" :key="item.receipt_id" class="chapter-order-history__item">
            <div class="chapter-order-history__copy">
              <strong>{{ historyLabel(item) }}</strong>
              <span>{{ orderSummary(item.source_order) }} → {{ orderSummary(item.target_order) }}</span>
              <small>{{ formatDate(item.created_at) }}</small>
            </div>
            <button
              v-if="item.can_restore"
              type="button"
              class="btn btn-sm"
              :disabled="busy || !canUseTargetProject"
              @click="requestRestorePreview(item)"
            >{{ selectedRestore?.receipt_id === item.receipt_id && loadingRestore ? '正在核对…' : '预览恢复' }}</button>
            <span v-else class="chapter-order-history__status">{{ statusLabel(item.status) }}</span>
          </li>
        </ul>

        <section v-if="restorePreview" class="chapter-order-review chapter-order-restore" aria-labelledby="chapter-order-restore-title">
          <p class="chapter-order-dialog__eyebrow">恢复预览 · R3</p>
          <h3 id="chapter-order-restore-title">{{ restorePreview.can_restore ? '可以恢复原顺序' : '当前来源有变化' }}</h3>
          <p>{{ restorePreview.can_restore
            ? '恢复会按这次调整之前的顺序放回所有正文版本与 Story 绑定。请再确认一次。'
            : '重排后正文、批注或 Story 绑定已变化。为保护新内容，系统不会覆盖恢复。' }}</p>
          <ul v-if="restorePreview.blockers?.length" class="chapter-order-blockers__list">
            <li v-for="blocker in restorePreview.blockers" :key="blocker.kind">{{ blocker.message }}</li>
          </ul>
          <button
            v-if="restorePreview.can_restore"
            type="button"
            class="btn btn-primary"
            :disabled="busy || !canUseTargetProject"
            @click="confirmRestore"
          >{{ confirmingRestore ? '正在恢复…' : '确认恢复章节顺序' }}</button>
        </section>
      </section>
    </div>
  </dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: String, default: null },
  chapterList: { type: Array, default: () => [] },
  chapters: { type: Object, default: () => ({}) },
  selectedChapter: { type: Number, default: null },
  blocked: { type: Boolean, default: false },
})
const emit = defineEmits(["close", "completed"])

const dialog = ref(null)
const tab = ref("reorder")
const targetProjectId = ref(null)
const sourceOrder = ref([])
const sourceSelectedChapter = ref(null)
const targetOrder = ref([])
const labels = ref({})
const preview = ref(null)
const restorePreview = ref(null)
const selectedRestore = ref(null)
const history = ref([])
const error = ref("")
const busy = ref(false)
const loadingPreview = ref(false)
const loadingHistory = ref(false)
const loadingRestore = ref(false)
const confirming = ref(false)
const confirmingRestore = ref(false)

const canUseTargetProject = computed(() => Boolean(targetProjectId.value) && targetProjectId.value === props.projectId)
const hasReorder = computed(() => targetOrder.value.length > 1
  && targetOrder.value.some((chapter, index) => chapter !== sourceOrder.value[index]))
const canConfirm = computed(() => Boolean(
  preview.value
  && !preview.value.story_impact?.blockers?.length
  && JSON.stringify(preview.value.target_order) === JSON.stringify(targetOrder.value)
  && !props.blocked
  && canUseTargetProject.value
))

watch(() => props.open, async (isOpen) => {
  if (!isOpen) {
    if (dialog.value?.open) dialog.value.close()
    return
  }
  targetProjectId.value = props.projectId
  sourceOrder.value = [...props.chapterList]
  sourceSelectedChapter.value = Number(props.selectedChapter) || null
  targetOrder.value = [...sourceOrder.value]
  labels.value = Object.fromEntries(props.chapterList.map((chapter) => [chapter, { ...(props.chapters[chapter] || {}) }]))
  preview.value = null
  restorePreview.value = null
  selectedRestore.value = null
  error.value = ""
  tab.value = "reorder"
  await nextTick()
  if (dialog.value && !dialog.value.open) dialog.value.showModal()
  dialog.value?.querySelector("[data-autofocus]")?.focus()
  void loadHistory()
}, { immediate: true })

function close() {
  if (dialog.value?.open) dialog.value.close()
  else emit("close")
}

function handleDialogClose() {
  emit("close")
}

function moveChapter(index, offset) {
  const nextIndex = index + offset
  if (nextIndex < 0 || nextIndex >= targetOrder.value.length) return
  const next = [...targetOrder.value]
  ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
  targetOrder.value = next
  preview.value = null
  error.value = ""
}

async function requestPreview() {
  if (!canUseTargetProject.value || busy.value || !hasReorder.value) return
  busy.value = true
  loadingPreview.value = true
  error.value = ""
  restorePreview.value = null
  try {
    preview.value = await getApi().writing.previewChapterOrder(targetProjectId.value, targetOrder.value)
  } catch (cause) {
    error.value = cause?.message || "影响预览失败。章节顺序意图已保留；可以重试或重新读取章节目录。"
  } finally {
    busy.value = false
    loadingPreview.value = false
  }
}

async function confirmOrder() {
  if (!canConfirm.value || busy.value) return
  busy.value = true
  confirming.value = true
  error.value = ""
  try {
    const result = await getApi().writing.confirmChapterOrder(
      targetProjectId.value,
      preview.value.receipt_id,
      preview.value.preview_hash,
    )
    emit("completed", {
      result,
      projectId: targetProjectId.value,
      selectedChapter: sourceSelectedChapter.value,
      restored: false,
    })
    close()
  } catch (cause) {
    error.value = cause?.message || "章节顺序没有完成。预览和目标顺序仍保留；请重新核对后重试。"
  } finally {
    busy.value = false
    confirming.value = false
  }
}

async function openHistory() {
  tab.value = "history"
  restorePreview.value = null
  await loadHistory()
}

async function loadHistory() {
  if (!props.open || !targetProjectId.value || !canUseTargetProject.value || loadingHistory.value) return
  loadingHistory.value = true
  error.value = ""
  try {
    const result = await getApi().writing.listChapterOrderHistory(targetProjectId.value)
    if (canUseTargetProject.value) history.value = result.items || []
  } catch (cause) {
    error.value = cause?.message || "重排历史暂时无法读取。"
  } finally {
    loadingHistory.value = false
  }
}

async function requestRestorePreview(item) {
  if (!canUseTargetProject.value || busy.value) return
  busy.value = true
  loadingRestore.value = true
  error.value = ""
  selectedRestore.value = item
  restorePreview.value = null
  preview.value = null
  try {
    restorePreview.value = await getApi().writing.previewChapterOrderRestore(
      targetProjectId.value,
      item.receipt_id,
    )
  } catch (cause) {
    error.value = cause?.message || "恢复预览失败；历史记录仍保留，可以重试。"
  } finally {
    busy.value = false
    loadingRestore.value = false
  }
}

async function confirmRestore() {
  if (!restorePreview.value?.can_restore || busy.value || !canUseTargetProject.value) return
  busy.value = true
  confirmingRestore.value = true
  error.value = ""
  try {
    const result = await getApi().writing.restoreChapterOrder(
      targetProjectId.value,
      restorePreview.value.receipt_id,
      restorePreview.value.restore_preview_hash,
    )
    emit("completed", {
      result,
      projectId: targetProjectId.value,
      selectedChapter: sourceSelectedChapter.value,
      restored: true,
    })
    close()
  } catch (cause) {
    error.value = cause?.message || "恢复没有完成。可能有新编辑；刷新历史并重新核对后再试。"
  } finally {
    busy.value = false
    confirmingRestore.value = false
  }
}

function formatAnchors(anchors = {}) {
  return Object.entries(anchors).map(([field, value]) => `${anchorLabel(field)}：${formatAnchorValue(field, value)}`).join("；") || "章节锚点不变"
}

function formatAnchorValue(field, value) {
  if (field === "reveal_stages" && Array.isArray(value)) {
    return value.map((stage) => `第 ${stage?.chapter_index ?? "?"} 章`).join("、") || "暂无阶段"
  }
  if (Array.isArray(value)) return value.map((item) => `第 ${item} 章`).join("、") || "暂无"
  return `第 ${value} 章`
}

function anchorLabel(field) {
  return ({
    start_chapter: "起始章",
    end_chapter: "结束章",
    planned_seed_chapter: "埋设章",
    planned_payoff_chapter: "兑现章",
    planned_reinforce_chapters: "强化章",
    reveal_stages: "揭示阶段",
  })[field] || field
}

function planTypeLabel(type) {
  return ({
    outline_arc: "篇章",
    plot_thread: "剧情线",
    foreshadowing_plan: "伏笔计划",
    reveal_plan: "揭示计划",
    scene_span_order: "正文片段",
    scene_cross_chapter_order: "跨章 Scene",
    scene_multi_chapter_binding_order: "多章 Scene",
    plan_interval_inverted: "计划区间",
    plan_interval_non_contiguous: "计划区间",
  })[type] || "章节来源"
}

function orderSummary(order = []) {
  return order.map((chapter) => `第 ${chapter} 章`).join("、") || "无章节"
}

function historyLabel(item) {
  if (item.status === "executed") return "已执行 · 可预览恢复"
  if (item.status === "restored") return "已恢复"
  return "未执行的预览"
}

function statusLabel(status) {
  return status === "previewed" ? "未执行" : status === "restored" ? "已恢复" : "不可恢复"
}

function formatDate(value) {
  if (!value) return "时间未知"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? "时间未知" : parsed.toLocaleString("zh-CN")
}
</script>

<style scoped>
.chapter-order-dialog {
  width: min(46rem, calc(100vw - 1.5rem));
  max-width: none;
  max-height: min(92dvh, 58rem);
  margin: auto;
  padding: 0;
  overflow: auto;
  color: var(--text-primary, #202a32);
  background: var(--surface-primary, #fff);
  border: 1px solid var(--border-subtle, #d8e0e4);
  border-radius: 1rem;
  box-shadow: 0 1.5rem 5rem rgb(20 32 42 / 24%);
}
.chapter-order-dialog::backdrop { background: rgb(14 24 32 / 52%); }
.chapter-order-dialog__layout { display: grid; gap: 1rem; padding: clamp(1rem, 3vw, 1.5rem); }
.chapter-order-dialog__header,
.chapter-order-dialog__section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.chapter-order-dialog__header h2,
.chapter-order-dialog__section h3 { margin: .15rem 0 .4rem; }
.chapter-order-dialog__eyebrow { margin: 0; color: var(--accent-strong, #306a65); font-size: .75rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.chapter-order-dialog__intro,
.chapter-order-dialog__section-heading p,
.chapter-order-review__summary { max-width: 58ch; margin: .35rem 0 0; color: var(--text-secondary, #59676e); line-height: 1.5; }
.chapter-order-dialog__tabs { display: flex; flex-wrap: wrap; gap: .5rem; border-bottom: 1px solid var(--border-subtle, #d8e0e4); padding-bottom: .65rem; }
.chapter-order-dialog__tabs [aria-pressed="true"] { color: var(--accent-strong, #245d58); border-color: var(--accent-strong, #306a65); }
.chapter-order-dialog__section { display: grid; gap: 1rem; }
.chapter-order-list,
.chapter-order-history,
.chapter-order-moves,
.chapter-order-review__plans ul,
.chapter-order-blockers ul { display: grid; gap: .5rem; margin: 0; padding: 0; list-style: none; }
.chapter-order-row,
.chapter-order-history__item { display: flex; align-items: center; gap: .75rem; min-width: 0; padding: .7rem; border: 1px solid var(--border-subtle, #d8e0e4); border-radius: .75rem; background: var(--surface-secondary, #f7f9f8); }
.chapter-order-row__position { display: grid; flex: 0 0 2rem; width: 2rem; height: 2rem; place-items: center; border-radius: 50%; color: var(--text-secondary, #59676e); background: var(--surface-primary, #fff); font-weight: 700; }
.chapter-order-row__chapter,
.chapter-order-history__copy { display: grid; flex: 1; min-width: 0; gap: .16rem; }
.chapter-order-row__chapter span { overflow-wrap: anywhere; }
.chapter-order-row__chapter small,
.chapter-order-history__copy small,
.chapter-order-moves small { color: var(--text-secondary, #59676e); }
.chapter-order-row__actions { display: flex; flex-wrap: wrap; gap: .35rem; }
.chapter-order-row button,
.chapter-order-dialog button { min-height: 2.75rem; }
.chapter-order-review { display: grid; gap: .8rem; padding: 1rem; border: 1px solid var(--border-subtle, #d8e0e4); border-radius: .9rem; background: var(--surface-primary, #fff); }
.chapter-order-moves { grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); }
.chapter-order-moves li { display: grid; gap: .25rem; padding: .65rem; border-radius: .65rem; background: var(--surface-secondary, #f7f9f8); }
.chapter-order-impact { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr)); gap: .55rem; margin: 0; }
.chapter-order-impact div { min-width: 0; padding: .65rem; border-radius: .65rem; background: var(--surface-secondary, #f7f9f8); }
.chapter-order-impact dt { color: var(--text-secondary, #59676e); font-size: .82rem; }
.chapter-order-impact dd { margin: .25rem 0 0; font-size: 1.2rem; font-weight: 700; }
.chapter-order-impact dd span { display: block; margin-top: .25rem; color: var(--text-secondary, #59676e); font-size: .76rem; font-weight: 400; }
.chapter-order-review__plans,
.chapter-order-blockers { display: grid; gap: .5rem; }
.chapter-order-review__plans h4,
.chapter-order-blockers h4 { margin: 0; }
.chapter-order-review__plans li,
.chapter-order-blockers li { display: grid; gap: .22rem; padding: .6rem .7rem; border-left: 3px solid var(--accent-strong, #306a65); background: var(--surface-secondary, #f7f9f8); }
.chapter-order-review__plans li span,
.chapter-order-blockers li span { overflow-wrap: anywhere; color: var(--text-secondary, #59676e); }
.chapter-order-blockers li { border-color: var(--status-warning, #a86613); }
.chapter-order-review__confirm { display: grid; justify-items: start; gap: .5rem; padding: .9rem; border: 1px solid color-mix(in srgb, var(--accent-strong, #306a65) 32%, transparent); border-radius: .7rem; background: color-mix(in srgb, var(--accent-strong, #306a65) 6%, white); }
.chapter-order-review__confirm p { margin: 0; max-width: 66ch; line-height: 1.5; }
.chapter-order-restore { margin-top: .5rem; }
.chapter-order-dialog__notice,
.chapter-order-dialog__error { padding: .7rem .85rem; border-radius: .65rem; }
.chapter-order-dialog__notice p { margin: .25rem 0 0; }
.chapter-order-dialog__notice--warning,
.chapter-order-dialog__error { color: var(--status-warning-text, #6a450d); background: var(--status-warning-bg, #fff5df); }
.chapter-order-dialog__error { color: var(--status-danger-text, #872d2d); background: var(--status-danger-bg, #fff0ed); }
.chapter-order-history__item { align-items: center; }
.chapter-order-history__status { flex: 0 0 auto; color: var(--text-secondary, #59676e); font-size: .82rem; }
.chapter-order-dialog__empty { padding: .75rem; color: var(--text-secondary, #59676e); }
@media (max-width: 480px) {
  .chapter-order-dialog { width: calc(100vw - .75rem); max-height: 96dvh; border-radius: .8rem; }
  .chapter-order-dialog__layout { gap: .8rem; padding: .8rem; }
  .chapter-order-dialog__header, .chapter-order-dialog__section-heading { align-items: stretch; flex-direction: column; }
  .chapter-order-dialog__header > button { align-self: flex-end; }
  .chapter-order-row { align-items: flex-start; gap: .5rem; padding: .55rem; }
  .chapter-order-row__actions { flex-direction: column; }
  .chapter-order-row__actions button { padding-inline: .5rem; }
  .chapter-order-history__item { align-items: flex-start; flex-direction: column; }
}
</style>
