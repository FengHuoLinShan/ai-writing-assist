<script setup>
import { computed } from "vue"
import {
  highlightParts,
  hitKindLabel,
  parentSceneContexts,
  parentSceneLabel,
  resultCountLabel,
  searchErrorReason,
} from "../logic/searchPayload.js"
import { ragSearchSession } from "../ragSearchSession.js"

/**
 * 检索结果区 — DOM 契约对齐 vanilla _renderSearchResults/_renderSearchError。
 * 结果读取 ragSearchSession（会话状态，跨 island 重挂载存活）。
 */
const props = defineProps({
  searching: { type: Boolean, default: false },
  searchError: { type: Object, default: null },
})

const emit = defineEmits(["load-more", "open-hit", "open-scene", "retry", "retry-literal"])

const session = ragSearchSession

const visibleHits = computed(() => session.hits.slice(0, session.visibleCount))
const remaining = computed(() => Math.max(0, session.hits.length - visibleHits.value.length))
const searched = computed(() => Boolean(session.lastSearchPayload))
const canRetryLiteral = computed(() => (
  searched.value && session.lastSearchPayload?.search_kind !== "literal"
))
const authorMode = computed(() => (
  (session.lastSearchPayload?.visibility?.mode || "author") === "author"
))
const showsScore = computed(() => visibleHits.value.some((hit) => (
  hit.score != null && Number.isFinite(Number(hit.score))
)))

const warnings = computed(() => {
  const meta = session.resultMeta || {}
  if (!meta.degraded && !(meta.warnings || []).length) return []
  return (meta.warnings || []).length ? meta.warnings : ["检索已降级，请检查索引任务结果。"]
})

const errorReasonText = computed(() => (
  props.searchError?.validation ? "" : searchErrorReason(props.searchError?.reason)
))

const countLabel = computed(() => (
  resultCountLabel(session.total, session.hits, visibleHits.value.length)
))

function hitMode(hit) {
  return hit.source_ref?.content_mode === "working" ? "工作稿" : "已发布"
}

function hitScore(hit) {
  if (hit.score == null) return ""
  const score = Number(hit.score)
  return Number.isFinite(score) ? `${Math.round(score * 100)}%` : ""
}
</script>

<template>
  <div id="rag-results" :aria-busy="searching ? 'true' : undefined">
    <div v-if="searching" class="loading-skeleton rag-results-loading" role="status">
      <span class="sr-only">正在查找作品资料</span>
      <div class="skeleton rag-results-loading__heading" aria-hidden="true"></div>
      <article v-for="index in 2" :key="index" class="card rag-result-card rag-result-card--loading" aria-hidden="true">
        <div class="skeleton loading-skeleton__heading"></div>
        <div class="skeleton loading-skeleton__line"></div>
        <div class="skeleton loading-skeleton__line loading-skeleton__line--medium"></div>
        <div class="skeleton loading-skeleton__line loading-skeleton__line--short"></div>
      </article>
    </div>

    <div v-else-if="searchError?.validation" class="empty-state">
      <p class="rag-search-empty">请完善可见性条件</p>
    </div>

    <section v-else-if="searchError" class="card error-card rag-search-error" role="alert">
      <div class="card-title">暂时无法完成检索</div>
      <p class="rag-error-text">{{ errorReasonText }}</p>
      <p class="rag-empty-copy">关键词和筛选条件已保留，失败不会被记作空结果。</p>
      <div class="rag-result-actions">
        <button type="button" class="btn btn-primary" data-action="retry-search" @click="emit('retry')">重试</button>
        <button v-if="searchError.searchKind !== 'literal'" type="button" class="btn" data-action="retry-literal-search" @click="emit('retry-literal')">切换字面搜索重试</button>
      </div>
    </section>

    <template v-else-if="session.hits.length === 0">
      <div v-if="warnings.length" class="card rag-search-warning rag-status-warning-card">
        <div class="card-title rag-status-warning-title">本次结果可能不准确</div>
        <p class="rag-empty-copy"><template v-for="(warning, index) in warnings" :key="index">{{ warning }}<br v-if="index < warnings.length - 1" /></template></p>
      </div>
      <section class="empty-state rag-results-empty" role="status">
        <h2>{{ searched ? "没有找到匹配资料" : "从作品中找回需要的资料" }}</h2>
        <p class="rag-search-empty">{{ searched ? "试试缩短关键词，或换用字面搜索。" : "输入人物、地点、事件或原文片段开始查找。" }}</p>
        <div v-if="canRetryLiteral" class="actions">
          <button type="button" class="btn" data-action="retry-literal-search" @click="emit('retry-literal')">用字面搜索重试</button>
        </div>
      </section>
    </template>

    <template v-else>
      <div class="rag-results-list">
        <div v-if="warnings.length" class="card rag-search-warning rag-status-warning-card">
          <div class="card-title rag-status-warning-title">本次结果可能不准确</div>
          <p class="rag-empty-copy"><template v-for="(warning, index) in warnings" :key="index">{{ warning }}<br v-if="index < warnings.length - 1" /></template></p>
        </div>
        <header class="rag-results-summary">
          <div>
            <h2>查找结果</h2>
            <p class="rag-result-count">{{ countLabel }}</p>
          </div>
          <p v-if="showsScore" class="rag-result-score-help">匹配度仅用于本次结果排序</p>
        </header>
        <article v-for="(hit, index) in visibleHits" :key="index" class="card rag-result-card">
          <header class="rag-result-title">
            <h3>{{ hit.title || "检索结果" }}</h3>
            <span v-if="hitScore(hit)" class="rag-result-score"><span>匹配度</span><strong>{{ hitScore(hit) }}</strong></span>
          </header>
          <div class="rag-result-evidence-label">匹配内容</div>
          <p class="rag-result-text">{{ highlightParts(hit.snippet, session.query).before }}<mark v-if="highlightParts(hit.snippet, session.query).mark">{{ highlightParts(hit.snippet, session.query).mark }}</mark>{{ highlightParts(hit.snippet, session.query).after }}</p>
          <div class="card-meta rag-result-meta">
            {{ hitKindLabel(hit.kind) }}<template v-if="hit.chapter_index"> · 第 {{ hit.chapter_index }} 章</template><template v-if="hit.match_count > 1"> · {{ hit.match_basis === "occurrence" ? `本章 ${hit.match_count} 处命中` : `找到 ${hit.match_count} 个相关片段` }}</template><template v-if="hit.source_ref"> · {{ hitMode(hit) }} v{{ hit.source_ref.version_number || "-" }}</template><template v-if="hit.index_fresh === false"> · 资料待更新</template><template v-if="(hit.scene_refs || []).length"> · 场景 {{ hit.scene_refs.length }}</template><template v-if="(hit.object_refs || []).length"> · 对象 {{ hit.object_refs.length }}</template><template v-if="hit.kind === 'manuscript' && authorMode && !parentSceneContexts(hit).length"> · 未关联剧情场景</template>
          </div>
          <section v-if="hit.kind === 'manuscript' && authorMode && (parentSceneContexts(hit).length || hit.writing_relevance?.label)" class="rag-result-context">
            <div class="rag-result-context__row">
              <span class="rag-result-context__label">剧情关联</span>
              <div class="rag-result-scene-list">
                <div
                  v-for="ref in parentSceneContexts(hit)"
                  :key="`${ref.target_id}:${ref.scene_span_id || ''}`"
                  class="rag-result-scene-item"
                >
                  <button
                    type="button"
                    class="rag-result-scene-link"
                    data-action="open-scene-context"
                    @click="emit('open-scene', ref)"
                  >{{ parentSceneLabel(ref) }}</button>
                  <p v-if="ref.context_summary" class="rag-result-context__summary">{{ ref.context_summary }}</p>
                </div>
              </div>
            </div>
            <p v-if="hit.writing_relevance?.label" class="rag-result-context__relevance"><strong>与当前创作：</strong>{{ hit.writing_relevance.label.replaceAll("Scene", "场景") }}</p>
          </section>
          <div class="rag-result-actions">
            <button type="button" class="btn btn-sm" data-action="open-hit" :data-hit-index="index" @click="emit('open-hit', index)">{{ hit.source_ref ? "阅读原文" : "查看对象" }}</button>
          </div>
        </article>
        <div v-if="remaining > 0" class="rag-load-more">
          <button type="button" class="btn" data-action="load-more-results" @click="emit('load-more')">加载更多</button>
          <span>还有 {{ remaining }} 条已获取结果</span>
        </div>
        <p v-else-if="session.total > session.hits.length" class="rag-search-limit-note">已显示本次返回的 {{ session.hits.length }} 条结果；可缩小章节或检索范围继续查找。</p>
      </div>
    </template>
  </div>
</template>
