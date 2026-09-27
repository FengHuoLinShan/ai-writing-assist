<template>
  <article class="editorial-issue" :class="{ 'editorial-issue--stale': issue.source_may_be_stale }">
    <div class="editorial-issue__head"><span>{{ categoryLabel(issue.finding.category) }} · {{ severityLabel(issue.finding.severity) }}</span><span>{{ dispositionLabel(issue.disposition) }}</span></div>
    <h5>{{ issue.finding.judgment }}</h5>
    <p><strong>读者可能的感受：</strong>{{ issue.finding.reader_impact }}</p>
    <p v-if="issue.finding.why_now"><strong>现在值得处理：</strong>{{ issue.finding.why_now }}</p>
    <p v-if="issue.source_may_be_stale" class="editorial-issue__warning">正文已变化，这条旧意见需要重新核对。</p>
    <details>
      <summary>依据、反证和处理方向</summary>
      <div v-for="(evidence, index) in issue.finding.evidence" :key="`${index}-${evidence.draft_id}`" class="editorial-issue__quote">
        <span>第 {{ evidence.chapter_index }} 章 · 原文</span>
        <blockquote>{{ evidence.quote }}</blockquote>
        <button type="button" class="btn btn-sm" @click="$emit('locate', evidence)">回到这处正文</button>
      </div>
      <div v-for="(source, index) in issue.finding.context_evidence || []" :key="`context-${index}`" class="editorial-issue__quote"><span>{{ source.source_kind === 'world' ? '世界资料' : '故事结构' }} · {{ source.title }}</span><blockquote>{{ source.quote }}</blockquote></div>
      <p v-if="issue.finding.counterevidence"><strong>可能反证：</strong>{{ issue.finding.counterevidence }}</p>
      <p v-if="issue.finding.intent_relation"><strong>与作者意图：</strong>{{ issue.finding.intent_relation }}<span v-if="issue.finding.intent_quote"> · 约定原文：{{ issue.finding.intent_quote }}</span></p>
      <p v-if="issue.finding.unchecked"><strong>尚未核对：</strong>{{ issue.finding.unchecked }}</p>
      <div v-if="issue.finding.directions?.length"><strong>可考虑的方向</strong><ol><li v-for="(direction, index) in issue.finding.directions" :key="index">{{ direction.approach }}<span v-if="direction.affected_chapters?.length"> · 涉及第 {{ direction.affected_chapters.join('、') }} 章</span> · 代价：{{ direction.tradeoff }}</li></ol></div>
      <p>这是一条编辑建议；不等于领域已核实问题，也不会改变正文。</p>
    </details>
    <div class="editorial-issue__decision">
      <label>我的决定<select v-model="choice"><option value="prepare">准备处理</option><option value="later">稍后处理</option><option value="intentional">这是刻意安排</option><option value="invalid">判断不成立</option><option value="modified">已自行修改</option><option value="closed">确认关闭</option></select></label>
      <label>原因或备忘 <small>可选</small><textarea v-model="note" rows="2" maxlength="2000" /></label>
      <div class="editorial-issue__actions"><button type="button" class="btn btn-sm" :disabled="busy" @click="saveDecision">保存决定</button><button v-if="issue.disposition === 'modified'" type="button" class="btn btn-sm" :disabled="busy" @click="$emit('recheck', issue)">重新检查修改</button><button v-if="issue.disposition === 'intentional'" type="button" class="btn btn-sm" @click="$emit('add-intent', issue)">放入长期约定草稿</button></div>
    </div>
    <details v-if="issue.decisions?.length || issue.rechecks?.length || issue.history?.length"><summary>处理与复核历史</summary>
      <div v-for="(item, index) in issue.decisions" :key="`d${index}`"><p>{{ dispositionLabel(item.disposition) }} · {{ item.at?.slice(0, 16) }}<span v-if="item.note"> · {{ item.note }}</span><span v-if="item.brief_version !== undefined"> · 编辑约定第 {{ item.brief_version }} 版</span></p><details v-if="item.evidence?.length"><summary>当时的原文依据</summary><blockquote v-for="(evidence, n) in item.evidence" :key="n">第 {{ evidence.chapter_index }} 章：{{ evidence.quote }}</blockquote></details></div>
      <div v-for="(item, index) in issue.rechecks" :key="`r${index}`"><strong>改后复核：{{ recheckLabel(item) }}</strong><p v-if="item.reason">{{ item.reason }}</p><p v-if="item.unchecked">未检查：{{ item.unchecked }}</p><blockquote v-for="(evidence, n) in item.new_evidence || []" :key="n">{{ evidence.quote }}</blockquote></div>
      <p v-for="(item, index) in issue.history" :key="`h${index}`">旧报告：{{ item.finding.judgment }}</p>
    </details>
  </article>
</template>

<script setup>
import { ref, watch } from "vue"
const props = defineProps({ issue: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(["locate", "decide", "recheck", "add-intent"])
const choice = ref("prepare"), note = ref("")
watch(() => props.issue.disposition, value => { choice.value = value === "open" ? "prepare" : value }, { immediate: true })
function saveDecision() { emit("decide", props.issue, choice.value, note.value); note.value = "" }
function categoryLabel(value) { return ({ structure: "结构", scene: "场景", reader: "读者体验", line: "行文", copy: "文字" })[value] || "编辑意见" }
function severityLabel(value) { return ({ high: "优先核对", medium: "值得处理", low: "可稍后看" })[value] || "待核对" }
function dispositionLabel(value) { return ({ open: "待决定", prepare: "准备处理", later: "稍后处理", intentional: "刻意安排", invalid: "判断不成立", modified: "已自行修改", closed: "已由作者关闭" })[value] || "待决定" }
function recheckLabel(value) { return ({ queued: "等待检查", running: "检查中", failed: "未完成", still: "问题仍在", possibly_improved: "可能已改善", unknown: "无法判断" })[value.verdict || value.status] || "待查看" }
</script>

<style scoped>
.editorial-issue{border:1px solid var(--border);border-radius:10px;padding:12px;background:var(--surface);overflow-wrap:anywhere}.editorial-issue--stale{border-style:dashed}.editorial-issue__head{display:flex;justify-content:space-between;gap:8px;color:var(--text-secondary);font-size:12px}.editorial-issue h5{font-size:15px;margin:8px 0}.editorial-issue p{margin:8px 0}.editorial-issue summary{cursor:pointer;margin:8px 0;font-weight:600}.editorial-issue__quote{border-left:3px solid var(--accent);padding-left:10px;margin:10px 0}.editorial-issue__quote span{color:var(--text-secondary);font-size:12px}.editorial-issue blockquote{margin:5px 0 8px;white-space:pre-wrap}.editorial-issue__warning{color:var(--danger,#b42318)}.editorial-issue__decision{border-top:1px solid var(--border);margin-top:12px;padding-top:8px}.editorial-issue__decision label{display:block;margin:8px 0}.editorial-issue__decision select,.editorial-issue__decision textarea{display:block;width:100%;min-height:36px;margin-top:3px;border:1px solid var(--border);border-radius:7px;padding:6px;background:var(--surface);color:var(--text-primary)}.editorial-issue__actions{display:flex;flex-wrap:wrap;gap:8px}
</style>
