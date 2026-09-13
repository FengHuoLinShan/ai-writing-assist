<script setup>
import { computed } from 'vue'
import PreviewIcon from './PreviewIcon.vue'

const props = defineProps({
  candidate: {
    type: Object,
    default: () => ({ status: 'pending', source: '第三章 · 潮汐之间', review: '待审查', stale: false }),
  },
})
const emit = defineEmits(['update:status', 'update:stale', 'update:review', 'update:revision', 'open', 'navigate', 'close'])

const worldCandidate = computed(() => props.candidate.destination === '世界资料')
const isStale = computed(() => Boolean(props.candidate.stale))
const review = computed(() => props.candidate.review || '待审查')
const revision = computed(() => props.candidate.revision || '未开始')
const revisionRunning = computed(() => ['进行中', 'running'].includes(revision.value))
const reviewPassed = computed(() => ['通过', 'passed'].includes(review.value))
const reviewBlocked = computed(() => ['有阻断项', 'blocked'].includes(review.value))
const statusCopy = computed(() => {
  if (props.candidate.status === 'adopted') return { label: worldCandidate.value ? '已确认世界资料' : '已采用到工作稿', tone: 'green', detail: worldCandidate.value ? '本次资料决定已记录为演示，未写入真实作品。' : '采用只创建工作稿版本，尚未成为正式正文。' }
  if (props.candidate.status === 'rejected') return { label: '已拒绝', tone: 'teal', detail: worldCandidate.value ? '资料候选已拒绝，原资料保持不变。' : '建议已拒绝，原工作稿保持不变。' }
  if (isStale.value) return { label: '来源已过期', tone: 'red', detail: '来源发生变化，这份建议暂时不能采用。' }
  return { label: '待采用', tone: 'purple', detail: reviewBlocked.value ? '独立审查发现阻断项，处理前不能采用。' : reviewPassed.value ? '独立审查已通过，可以决定是否采用。' : worldCandidate.value ? '这份资料仍待作者决定。' : '这份建议还没有改动工作稿。' }
})
const canDecide = computed(() => props.candidate.status === 'pending' && !isStale.value && reviewPassed.value && !revisionRunning.value)
const canReject = computed(() => props.candidate.status === 'pending' && !revisionRunning.value)
function adopt() { if (canDecide.value) emit('update:status', 'adopted') }
function reject() { if (canReject.value) emit('update:status', 'rejected') }
function recheck() { emit('update:stale', false) }
function setReview(value) { emit('update:review', value) }
function setRevision(value) { emit('update:revision', value); if (value === '完成') emit('update:review', '待审查') }
</script>

<template>
  <section class="rd-candidate-review" aria-labelledby="candidate-review-title">
    <header class="rd-detail-heading">
      <div>
        <span class="rd-eyebrow">AI 建议 · 候选审阅 · 演示</span>
        <h1 id="candidate-review-title">{{ candidate.title || '把沉默留给灯塔' }}</h1>
        <p class="rd-candidate-source">来源：{{ candidate.source }} · {{ worldCandidate ? '原资料保持不变' : '当前工作稿保持不变' }}</p>
      </div>
      <span class="rd-badge" :class="`tone-${statusCopy.tone}`">{{ statusCopy.label }} · 演示</span>
    </header>

    <div v-if="isStale" class="rd-inline-notice tone-red" role="alert">
      <strong>! 来源已变化，暂不能采用</strong>
      <p>{{ statusCopy.detail }}请重新确认资料后再比较和决定。</p>
      <button class="rd-button" @click="recheck">演示重新确认来源</button>
    </div>
    <div v-else class="rd-inline-notice" :class="`tone-${statusCopy.tone}`" role="status">
      <strong>{{ statusCopy.label }} · 演示</strong>
      <p>{{ statusCopy.detail }}</p>
    </div>

    <div class="rd-candidate-summary" aria-label="候选摘要">
      <div><span>来源范围</span><strong>{{ candidate.source }}</strong></div>
      <div><span>审查状态</span><strong>{{ review }}</strong></div>
      <div><span>差异</span><strong>{{ candidate.diffSummary || '局部段落改写 · 示例' }}</strong></div>
    </div>

    <div class="rd-comparison" aria-label="候选与原工作稿比较">
      <section>
        <span class="rd-eyebrow">{{ worldCandidate ? '来源原文' : '原工作稿' }}</span>
        <h2>{{ candidate.original || '年轻人没有立刻回答。' }}</h2>
        <p v-if="!candidate.original">他看着海图，似乎想起了什么。</p>
      </section>
      <section>
        <span class="rd-eyebrow rd-purple-text">候选建议</span>
        <h2>{{ candidate.suggestion || '年轻人没有立刻回答。' }}</h2>
        <p v-if="!candidate.suggestion">他的手指收紧了一瞬，<mark>像是认出了什么，又决定不说。</mark></p>
      </section>
    </div>

    <section class="rd-candidate-review-result" aria-label="独立审查结果">
      <div class="rd-detail-heading"><div><span class="rd-eyebrow">独立审查</span><h2>{{ review === '通过' || review === 'passed' ? '可以进入作者决定' : reviewBlocked ? '需要先处理阻断项' : '尚未完成审查' }}</h2></div><span class="rd-badge" :class="reviewPassed ? 'tone-green' : reviewBlocked ? 'tone-red' : 'tone-orange'">{{ review }} · 演示</span></div>
      <p v-if="reviewBlocked" class="rd-candidate-blocker">阻断项：人物知识边界需要重新核对；当前候选不能采用。</p>
      <p v-else-if="reviewPassed">未发现阻断项。审查结果只针对这份候选及其来源。</p>
      <p v-else>请先运行独立审查，不能把待审查状态当成通过。</p>
      <details class="rd-candidate-state-controls"><summary class="rd-text-button">状态演示</summary><div class="rd-local-toolbar"><button class="rd-text-button" @click="setReview('待审查')">待审查</button><button class="rd-text-button" @click="setReview('有阻断项')">有阻断项</button><button class="rd-text-button" @click="setReview('通过')">审查通过</button><button class="rd-text-button" @click="emit('update:stale', true)">来源过期</button></div></details>
    </section>

    <details class="rd-candidate-revision" aria-label="定向返修">
      <summary class="rd-detail-heading"><div><span class="rd-eyebrow">定向返修</span><h2>{{ revision === '未开始' ? '只修复审查指出的问题' : `返修：${revision}` }}</h2></div><span class="rd-badge tone-purple">候选仍未采用 · 演示</span></summary>
      <p>返修会生成新的候选版本，原候选、原工作稿和来源记录保持可回看。</p>
      <div class="rd-local-toolbar"><input aria-label="返修要求" placeholder="例如：收紧人物知识边界"/><button class="rd-button purple" :disabled="!reviewBlocked" @click="setRevision('进行中')">开始定向返修</button><button v-if="revision === '进行中'" class="rd-button" @click="setRevision('完成')">演示返修完成</button><button v-if="revision === '进行中'" class="rd-button danger" @click="setRevision('失败')">演示返修失败</button><button v-if="revision === '失败'" class="rd-button" @click="setRevision('进行中')">重新返修</button><button class="rd-text-button" @click="emit('open', '重新生成候选', 'ai', true)">重新生成候选 →</button></div>
    </details>

    <div class="rd-candidate-actions">
      <button class="rd-button" @click="emit('close')">关闭审阅</button>
      <button class="rd-button" @click="worldCandidate ? emit('close') : emit('navigate', 'writing')">{{ worldCandidate ? '返回资料' : '返回正文' }}</button>
      <button class="rd-button" :disabled="!canReject" @click="reject">拒绝建议</button>
      <button class="rd-button purple" :disabled="!canDecide" @click="adopt"><span class="rd-button-content">{{ worldCandidate ? '确认资料候选' : '采用到工作稿' }} <PreviewIcon name="forward" /></span></button>
    </div>
    <p class="rd-demonstration">{{ worldCandidate ? '本次资料决定只用于预览，不写入真实世界资料。' : '采用到工作稿后仍需作者确认正式正文；本预览不会替换正文。' }}</p>
  </section>
</template>

<style>
#redesign-root .rd-candidate-review { max-width: 1080px; margin: 0 auto; padding: 26px 30px 44px; color: var(--ink); }
#redesign-root .rd-candidate-review .rd-candidate-source { margin: 9px 0 0; color: var(--muted); font-size: 12px; }
#redesign-root .rd-candidate-review .rd-candidate-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; margin: 28px 0; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--line); }
#redesign-root .rd-candidate-review .rd-candidate-summary div { display: grid; gap: 7px; padding: 16px; background: var(--surface); }
#redesign-root .rd-candidate-review .rd-candidate-summary span { color: var(--muted); font-size: 11px; }
#redesign-root .rd-candidate-review .rd-candidate-summary strong { font-size: 14px; }
#redesign-root .rd-candidate-review .rd-candidate-review-result, #redesign-root .rd-candidate-review .rd-candidate-revision { margin: 22px 0; padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); }
#redesign-root .rd-candidate-review .rd-candidate-review-result h2, #redesign-root .rd-candidate-review .rd-candidate-revision h2 { margin: 5px 0 0; font-size: 17px; }
#redesign-root .rd-candidate-review .rd-candidate-blocker { color: var(--red); }
#redesign-root .rd-candidate-review .rd-candidate-state-controls { margin-top: 12px; }
#redesign-root .rd-candidate-review .rd-comparison { grid-template-columns: repeat(2, minmax(0, 1fr)); }
#redesign-root .rd-candidate-review .rd-comparison section { min-height: 230px; }
#redesign-root .rd-candidate-review .rd-comparison h2 { margin: 15px 0 10px; font-size: 18px; }
#redesign-root .rd-candidate-review .rd-comparison p { line-height: 2; }
#redesign-root .rd-candidate-review .rd-candidate-actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; margin-top: 24px; }
#redesign-root .rd-candidate-review .rd-candidate-actions .rd-button:first-child { margin-right: auto; }
#redesign-root .rd-candidate-review .rd-demonstration { color: var(--muted); font-size: 11px; text-align: right; }
@media (max-width: 760px) {
  #redesign-root .rd-candidate-review { padding: 26px 20px 44px; }
  #redesign-root .rd-candidate-review .rd-candidate-summary { grid-template-columns: 1fr; }
  #redesign-root .rd-candidate-review .rd-comparison { grid-template-columns: 1fr; }
  #redesign-root .rd-candidate-review .rd-candidate-actions { justify-content: stretch; }
  #redesign-root .rd-candidate-review .rd-candidate-actions .rd-button { flex: 1 1 calc(50% - 10px); }
  #redesign-root .rd-candidate-review .rd-candidate-actions .rd-button:first-child { margin-right: 0; }
}
</style>
