<template>
  <section class="writing-comments" aria-labelledby="writing-comments-title">
    <header class="writing-comments__header">
      <div>
        <small>本章修改线索</small>
        <h2 id="writing-comments-title">正文批注</h2>
      </div>
      <span>{{ comments.length }} 条</span>
    </header>
    <p class="writing-comments__hint">选中文字添加批注；Agent 只生成候选，正文由你决定是否采用。</p>
    <form v-if="selection" class="writing-comments__form" @submit.prevent="$emit('save-comment', note)">
      <p>选中：{{ selection.selection.slice(0, 160) }}</p>
      <label for="writing-comment-note">希望怎么修改？</label>
      <textarea id="writing-comment-note" v-model="note" rows="3" maxlength="4000" required :disabled="busy" />
      <div class="writing-comments__actions">
        <button type="submit" class="btn btn-sm btn-primary" :disabled="busy || !note.trim()">保存批注</button>
        <button type="button" class="btn btn-sm" @click="note = ''; $emit('cancel-comment')">取消</button>
      </div>
    </form>
    <div class="writing-comments__actions">
      <button type="button" class="btn btn-sm" :disabled="busy || !canRun" @click="$emit('run-review', selectedIds)">审稿并修订</button>
      <button type="button" class="btn btn-sm" :disabled="busy || !canRun || !selectedIds.length" @click="$emit('run-comments', selectedIds)">执行待处理评论</button>
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <button v-if="error && task?.task_id" type="button" class="btn btn-sm" @click="$emit('refresh-task', task.task_id)">重新查询任务</button>
    <p v-if="task && ['pending', 'running'].includes(task.status)" role="status">Agent 正在处理… {{ Math.round(Number(task.progress || 0) * 100) }}%</p>
    <div v-if="task?.status === 'done'" class="writing-comments__result" role="status">
      <p v-if="task.result?.candidate_draft_id">局部修订候选已生成，正文尚未改变。</p>
      <p v-else>审稿已结束；本轮没有可采用的修订候选。</p>
      <p v-if="task.result?.unlocated_comment_ids?.length">有问题无法精确定位，请重新选择原文后再执行。</p>
      <p v-if="task.result?.post_review_error">候选复审未完成，暂时不能采用。</p>
      <p v-if="task.result?.asset_proposal_error">相关资料提案：{{ task.result.asset_proposal_error }}</p>
      <div class="writing-comments__actions">
        <button v-if="task.result?.candidate_draft_id" type="button" class="btn btn-sm btn-primary" @click="$emit('open-candidate', task.result.candidate_draft_id)">比较修订候选</button>
        <button v-if="task.result?.asset_proposal_run_id" type="button" class="btn btn-sm" @click="$emit('open-proposals', task.result.asset_proposal_run_id)">查看相关资料提案</button>
      </div>
    </div>
    <p v-else-if="task && ['failed', 'cancelled'].includes(task.status)" class="field-error" role="alert">任务未完成：{{ task.error_message || '请检查本章版本后重试' }}</p>
    <ul v-if="comments.length" class="writing-comments__list">
      <li v-for="item in comments" :key="item.id" :class="{ 'is-stale': item.status === 'stale' }">
        <div class="writing-comments__meta">
          <label v-if="item.status === 'open'" :for="`comment-select-${item.id}`"><input :id="`comment-select-${item.id}`" v-model="selectedIds" type="checkbox" :value="item.id" :disabled="busy" /> 待执行</label>
          <span v-else>{{ item.status === 'stale' ? '定位失效' : '已处理' }}</span>
          <span>{{ item.origin === 'ai' ? 'AI 审稿' : '我的批注' }}</span>
          <span v-if="item.severity">{{ severityLabel(item.severity) }}</span>
        </div>
        <div class="writing-comments__focus" role="button" :tabindex="item.status === 'stale' ? -1 : 0" :aria-disabled="item.status === 'stale'" @click="item.status !== 'stale' && $emit('locate', item)" @keydown.enter.prevent="item.status !== 'stale' && $emit('locate', item)" @keydown.space.prevent="item.status !== 'stale' && $emit('locate', item)">
          <blockquote>{{ item.excerpt.slice(0, 160) }}</blockquote>
          <p>{{ item.body }}</p>
        </div>
        <div class="writing-comments__actions">
          <button v-if="item.status !== 'stale'" type="button" class="btn btn-sm btn-ghost" @click="$emit('locate', item)">定位原文</button>
          <button v-if="item.status !== 'stale'" type="button" class="btn btn-sm btn-ghost" :disabled="busy" @click="$emit('set-status', item, item.status === 'open' ? 'resolved' : 'open')">{{ item.status === 'open' ? '标为已处理' : '重新打开' }}</button>
        </div>
      </li>
    </ul>
    <p v-else class="writing-comments__empty">还没有批注。</p>
  </section>
</template>

<script setup>
import { ref, watch } from "vue"

const props = defineProps({
  comments: { type: Array, default: () => [] },
  selection: { type: Object, default: null },
  canRun: Boolean,
  busy: Boolean,
  error: { type: String, default: "" },
  task: { type: Object, default: null },
})
defineEmits(["save-comment", "cancel-comment", "run-review", "run-comments", "refresh-task", "locate", "set-status", "open-candidate", "open-proposals"])
const note = ref("")
const selectedIds = ref([])
const severityLabel = value => ({ blocker: "阻断", major: "重要", minor: "建议" }[value] || "问题")
watch(() => props.comments, items => {
  const available = new Set(items.filter(item => item.status === "open").map(item => item.id))
  selectedIds.value = [...new Set([
    ...selectedIds.value.filter(id => available.has(id)),
    ...items.filter(item => item.status === "open" && item.origin === "author" && !item.last_run_task_id).map(item => item.id),
  ])]
}, { immediate: true })
watch(() => props.selection, value => { if (!value) note.value = "" })
</script>

<style scoped>
.writing-comments { border-bottom: 1px solid var(--border); padding: 18px 14px; }
.writing-comments__header, .writing-comments__meta, .writing-comments__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.writing-comments__header { justify-content: space-between; }
.writing-comments__header h2 { margin: 2px 0; font-size: 17px; }
.writing-comments__hint, .writing-comments__empty { color: var(--text-secondary); font-size: 13px; }
.writing-comments__form, .writing-comments__result { padding: 10px; background: var(--surface-secondary, var(--surface)); border: 1px solid var(--border); margin: 12px 0; }
.writing-comments__form textarea { display: block; width: 100%; margin: 8px 0; }
.writing-comments__list { list-style: none; padding: 0; margin: 14px 0 0; }
.writing-comments__list li { padding: 12px 0; border-top: 1px solid var(--border); overflow-wrap: anywhere; }
.writing-comments__list li.is-stale { opacity: .65; }
.writing-comments__focus:not([aria-disabled="true"]) { cursor: pointer; }
.writing-comments__focus:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.writing-comments__list blockquote { margin: 8px 0; padding-left: 9px; border-left: 2px solid var(--accent); color: var(--text-secondary); }
.writing-comments__list p { margin: 8px 0; }
.writing-comments__meta { font-size: 12px; color: var(--text-secondary); }
.writing-comments__meta input { vertical-align: middle; }
.writing-comments__actions .btn { min-height: 36px; }
@media (max-width: 760px) { .writing-comments { padding: 16px; } .writing-comments__actions .btn { min-height: 44px; } }
</style>
