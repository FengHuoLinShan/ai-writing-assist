<template>
  <div v-if="bundle" class="generate-context-review">
    <section class="generate-context-overview" aria-labelledby="generate-context-overview-title">
      <div class="generate-context-overview__heading">
        <div>
          <span class="generate-context-eyebrow">AI 实际会参考</span>
          <h4 id="generate-context-overview-title">已准备 {{ sections.length }} 类参考资料</h4>
          <p>{{ sourceSummary }}</p>
        </div>
        <div class="generate-context-overview__badges" aria-label="本次参考边界">
          <span>{{ scopeLabel }}</span>
          <span>{{ revealLabel }}</span>
        </div>
      </div>

      <div v-if="hasAttention" class="generate-context-attention" role="note">
        <strong>{{ attentionTitle }}</strong>
        <ul v-if="incompleteItems.length">
          <li v-for="item in incompleteItems" :key="item.key">{{ item.text }}</li>
        </ul>
        <details v-if="warnings.length">
          <summary>查看 {{ warnings.length }} 条范围提示</summary>
          <ul><li v-for="warning in warnings" :key="warning">{{ authorText(warning) }}</li></ul>
        </details>
        <p v-if="incompleteItems.length">系统已优先保留任务、当前场景和更重要的设定；如需更多资料，可返回调整长度上限后重新整理。</p>
      </div>

      <div v-if="!sections.length" class="generate-context-empty">
        <strong>这次没有找到可用的参考资料</strong>
        <p>可以返回补充任务范围、章节或重点人物，再重新整理。</p>
      </div>
    </section>

    <section v-for="group in sectionGroups" :key="group.key" class="generate-context-group" :aria-labelledby="`generate-context-group-${group.key}`">
      <div class="generate-context-group__heading">
        <div><h4 :id="`generate-context-group-${group.key}`">{{ group.title }}</h4><p>{{ group.hint }}</p></div>
        <span>{{ group.items.length }} 类</span>
      </div>
      <div class="generate-context-sections">
        <article v-for="section in group.items" :key="section.key" class="generate-context-section">
          <div class="generate-context-section__heading">
            <strong>{{ sectionTitle(section) }}</strong>
            <span :class="`is-${section.status || 'unknown'}`">{{ statusLabel(section.status) }}</span>
          </div>
          <p v-if="reasonText(section.activation_reason)" class="generate-context-section__reason"><strong>为什么会用：</strong>{{ reasonText(section.activation_reason) }}</p>
          <p v-if="previewText(section)" class="generate-context-section__preview">{{ previewText(section) }}</p>
          <div v-if="sectionSources(section).length" class="generate-context-section__sources">
            <span>来源</span>
            <ul>
              <li v-for="source in sectionSources(section)" :key="sourceKey(section, source)">{{ sourceLabel(source) }}</li>
            </ul>
          </div>
          <p v-if="sectionTruncated(section)" class="generate-context-section__limited">这里只保留了与本次任务最相关的部分。</p>
        </article>
      </div>
    </section>

    <details class="generate-context-diagnostics">
      <summary><span>查看整理细节</span><small>内部分区、估算长度与裁剪记录</small></summary>
      <div class="generate-context-diagnostics__body">
        <dl class="generate-context-diagnostics__summary">
          <div><dt>内部范围</dt><dd>{{ bundle.scope || "未标明" }}</dd></div>
          <div><dt>内部可见模式</dt><dd>{{ bundle.reveal_mode || "未标明" }}</dd></div>
          <div><dt>估算长度</dt><dd>{{ budgetSummary }}</dd></div>
        </dl>
        <div v-if="sections.length" class="generate-context-diagnostics__table-wrap">
          <table class="data-table generate-context-table">
            <thead><tr><th>优先级</th><th>内部分区</th><th>估算长度</th><th>处理</th></tr></thead>
            <tbody>
              <tr v-for="section in sections" :key="`diagnostic-${section.key}`">
                <td>{{ diagnosticTier(section.tier) }}</td>
                <td>{{ section.key }}</td>
                <td>{{ section.token_count || 0 }}</td>
                <td>{{ sectionTruncated(section) ? "已裁剪" : "完整" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul v-if="budgetEvents.length" class="generate-context-diagnostics__events">
          <li v-for="event in budgetEvents" :key="`${event.event_type}:${event.section_key}:${event.before_tokens}:${event.after_tokens}:${event.reason}`">{{ budgetEventText(event) }}</li>
        </ul>
      </div>
    </details>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { authorFacingStateText } from "../../../../shared/assetDisplayState.js"
import { REVEAL_OPTIONS, SCOPE_OPTIONS, tierName } from "../logic/generateLogic.js"

const props = defineProps({ bundle: { type: Object, default: null } })

const SECTION_LABELS = {
  writing_objective: "本次任务",
  project: "项目概况",
  scene_blueprint: "当前场景",
  world_bible_synopsis: "世界观简介",
  world_bible_working_pages: "世界书工作稿",
  world_bible_activation: "按规则选入的世界资料",
  world_entities: "相关世界对象",
  characters: "相关人物",
  pov_knowledge: "视角人物所知",
  delta_timeline: "世界变化时间线",
  memory: "相关前情",
  memory_records: "相关前情",
  events: "相关事件",
  plot_threads: "相关剧情线",
  outline_arc: "相关篇章",
  outline_analysis_scenes: "范围内场景",
  outline_analysis_arcs: "相关篇章",
  outline_analysis_threads: "相关剧情线",
  outline_analysis_foreshadowing: "相关伏笔",
  outline_analysis_reveals: "相关揭示",
  open_narrative_obligations: "尚待推进的叙事事项",
  retrieval_evidence_packs: "正文与导入资料",
  rag_chunks: "正文与导入资料",
  style_assets: "文风参考",
  hard_constraints: "必须遵守的边界",
  compiler_warnings: "整理提示",
  role_profile: "视角人物档案",
  role_visible_knowledge: "角色可见知识",
  role_relationship_context: "角色可见关系",
  role_scene_perception: "当前场景可感知信息",
  scene_director_constraints: "场景写作边界",
  scene_time_boundary: "场景时间边界",
  current_scene_evidence: "当前场景证据",
}

const sections = computed(() => Array.isArray(props.bundle?.sections) ? props.bundle.sections : [])
const warnings = computed(() => Array.isArray(props.bundle?.warnings) ? [...new Set(props.bundle.warnings.filter(Boolean))] : [])
const budgetEvents = computed(() => Array.isArray(props.bundle?.budget_events) ? props.bundle.budget_events : [])
const sourceCount = computed(() => new Set(sections.value.flatMap((section) => (section.sources || []).map((source) => `${source.type || "source"}:${source.id || source.label || "unknown"}`))).size)
const sourceSummary = computed(() => sourceCount.value
  ? `来自 ${sourceCount.value} 项可核对来源；先看标题和来源是否符合这次任务。`
  : "本次没有返回可核对的来源明细；可以在整理细节中查看系统记录。")
const scopeLabel = computed(() => SCOPE_OPTIONS.find((item) => item.value === props.bundle?.scope)?.label || ({ scene: "当前场景", generation_center: "当前创作任务" })[props.bundle?.scope] || "当前任务范围")
const revealLabel = computed(() => REVEAL_OPTIONS.find((item) => item.value === props.bundle?.reveal_mode)?.label || "按当前可见边界")
const sectionGroups = computed(() => {
  const model = sections.value.filter((section) => section.status !== "director_only")
  const authorOnly = sections.value.filter((section) => section.status === "director_only")
  return [
    model.length ? { key: "model", title: "会交给 AI 的资料", hint: "核对这些资料是否足以支持本次任务。", items: model } : null,
    authorOnly.length ? { key: "author", title: "仅供作者约束", hint: "这些信息不会被当成角色已经知道的事实。", items: authorOnly } : null,
  ].filter(Boolean)
})
const evictedKeys = computed(() => [...new Set([...(props.bundle?.evicted || []), ...budgetEvents.value.filter((event) => event.event_type === "evicted").map((event) => event.section_key)].filter(Boolean))])
const truncatedKeys = computed(() => [...new Set([...(props.bundle?.truncated || []), ...sections.value.filter((section) => section.truncated || section.truncated_reason).map((section) => section.key), ...budgetEvents.value.filter((event) => event.event_type === "truncated").map((event) => event.section_key)].filter(Boolean))])
const incompleteItems = computed(() => [
  ...evictedKeys.value.map((key) => ({ key: `removed-${key}`, text: `${sectionTitle({ key })}未加入本次资料。` })),
  ...truncatedKeys.value.filter((key) => !evictedKeys.value.includes(key)).map((key) => ({ key: `limited-${key}`, text: `${sectionTitle(sections.value.find((section) => section.key === key) || { key })}只保留了相关部分。` })),
])
const hasAttention = computed(() => incompleteItems.value.length > 0 || warnings.value.length > 0)
const attentionTitle = computed(() => incompleteItems.value.length
  ? `${incompleteItems.value.length} 类资料没有完整加入`
  : `有 ${warnings.value.length} 条范围提示`)
const budgetSummary = computed(() => props.bundle?.budget_tokens > 0
  ? `${props.bundle?.total_tokens || 0} / ${props.bundle.budget_tokens}`
  : `${props.bundle?.total_tokens || 0}（未设置应用层上限）`)

function authorText(value) {
  return authorFacingStateText(String(value || ""))
    .replace(/当前\s*scene_id/gi, "当前场景")
    .replaceAll("scene_id", "当前场景")
    .replace(/\s*tokens?\s*预算/gi, "资料长度上限")
    .replace(/\btokens?\b/gi, "资料长度")
    .replaceAll("author_safe", "作者可见范围")
    .replaceAll("author_full", "作者全部资料")
}
function sectionTitle(section) { return authorText(section?.title || SECTION_LABELS[section?.key] || "其他相关资料") }
function reasonText(value) { return authorText(value).trim() }
function previewText(section) {
  const value = authorText(section?.preview).trim().replace(/\s+/g, " ")
  if (!value || /^[{<[]/.test(value)) return ""
  return value.length > 240 ? `${value.slice(0, 240)}…` : value
}
function statusLabel(status) {
  return ({ system: "本次要求", canonical: "已采用", working: "工作稿", candidate: "待处理", review: "待处理", mixed: "多种来源", director_only: "作者约束", unknown: "状态未说明" })[status] || "状态未说明"
}
function sourceLabel(source) { return authorText(source?.label || ({ character: "人物", entity: "世界资料", rag: "正文资料", chapter: "章节", scene: "场景", task: "本次任务" })[source?.type] || "来源资料") }
function sourceKey(section, source) { return `${section.key}:${source?.type || "source"}:${source?.id || source?.label || "unknown"}` }
function sectionSources(section) { return [...new Map((section?.sources || []).map((source) => [sourceKey(section, source), source])).values()] }
function sectionTruncated(section) { return Boolean(section?.truncated || section?.truncated_reason || truncatedKeys.value.includes(section?.key)) }
function diagnosticTier(tier) { return Number.isInteger(tier) ? `P${tier}` : tierName(tier) }
function budgetEventText(event) {
  const action = event.event_type === "evicted" ? "移除" : "裁剪"
  const title = sectionTitle(sections.value.find((section) => section.key === event.section_key) || { key: event.section_key })
  return `${action}${title}：${event.before_tokens || 0} → ${event.after_tokens || 0}，${authorText(event.reason)}`
}
</script>
