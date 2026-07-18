<script setup>
import { computed } from "vue"
import { highlightParts, hitKindLabel, resultCountLabel, searchErrorReason } from "../logic/searchPayload.js"
import { ragSearchSession } from "../ragSearchSession.js"

/**
 * 检索结果区 — DOM 契约对齐 vanilla _renderSearchResults/_renderSearchError。
 * 结果读取 ragSearchSession（会话状态，跨 island 重挂载存活）。
 */
const props = defineProps({
  searching: { type: Boolean, default: false },
  searchError: { type: Object, default: null },
})

const emit = defineEmits(["load-more", "open-hit", "retry", "retry-literal"])

const session = ragSearchSession

const visibleHits = computed(() => session.hits.slice(0, session.visibleCount))
const remaining = computed(() => Math.max(0, session.hits.length - visibleHits.value.length))
const searched = computed(() => Boolean(session.lastSearchPayload))

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
</script>

<template>
  <div id="rag-results">
    <div v-if="searching" class="loading">搜索中</div>

    <div v-else-if="searchError?.validation" class="empty-state">
      <p class="rag-search-empty">请完善可见性条件</p>
    </div>

    <section v-else-if="searchError" class="card rag-search-error" role="alert">
      <div class="card-title">暂时无法完成检索</div>
      <p class="rag-error-text">{{ errorReasonText }}</p>
      <p class="rag-empty-copy">关键词和筛选条件已保留，失败不会被记作空结果。</p>
      <div class="rag-result-actions">
        <button class="btn btn-primary" data-action="retry-search" @click="emit('retry')">重试</button>
        <button v-if="searchError.searchKind !== 'literal'" class="btn" data-action="retry-literal-search" @click="emit('retry-literal')">切换字面搜索重试</button>
      </div>
    </section>

    <template v-else-if="session.hits.length === 0">
      <div v-if="warnings.length" class="card rag-search-warning rag-status-warning-card">
        <div class="card-title rag-status-warning-title">本次结果可能不准确</div>
        <p class="rag-empty-copy"><template v-for="(warning, index) in warnings" :key="index">{{ warning }}<br v-if="index < warnings.length - 1" /></template></p>
      </div>
      <div class="empty-state">
        <p class="rag-search-empty">{{ searched ? "未找到匹配结果" : "输入关键词后搜索。" }}</p>
      </div>
    </template>

    <template v-else>
      <div class="rag-results-list">
        <div v-if="warnings.length" class="card rag-search-warning rag-status-warning-card">
          <div class="card-title rag-status-warning-title">本次结果可能不准确</div>
          <p class="rag-empty-copy"><template v-for="(warning, index) in warnings" :key="index">{{ warning }}<br v-if="index < warnings.length - 1" /></template></p>
        </div>
        <p class="rag-result-count">{{ countLabel }}</p>
        <article v-for="(hit, index) in visibleHits" :key="index" class="card rag-result-card">
          <div class="card-title rag-result-title">
            <span>{{ hit.title || "检索结果" }}</span>
            <span v-if="hit.score" class="rag-result-score">{{ (hit.score * 100).toFixed(0) }}%</span>
          </div>
          <p class="rag-result-text">{{ highlightParts(hit.snippet, session.query).before }}<mark v-if="highlightParts(hit.snippet, session.query).mark">{{ highlightParts(hit.snippet, session.query).mark }}</mark>{{ highlightParts(hit.snippet, session.query).after }}</p>
          <div class="card-meta">
            {{ hitKindLabel(hit.kind) }}<template v-if="hit.chapter_index"> · 第 {{ hit.chapter_index }} 章</template><template v-if="hit.match_count > 1"> · {{ hit.match_basis === "occurrence" ? `本章 ${hit.match_count} 处命中` : `聚合 ${hit.match_count} 个相关片段` }}</template><template v-if="hit.source_ref"> · {{ hitMode(hit) }} v{{ hit.source_ref.version_number || "-" }}</template><template v-if="hit.index_fresh === false"> · 索引待更新</template><template v-if="(hit.scene_refs || []).length"> · Scene {{ hit.scene_refs.length }}</template><template v-if="(hit.object_refs || []).length"> · 对象 {{ hit.object_refs.length }}</template>
          </div>
          <div class="rag-result-actions">
            <button class="btn btn-sm" data-action="open-hit" :data-hit-index="index" @click="emit('open-hit', index)">{{ hit.source_ref ? "阅读原文" : "查看对象" }}</button>
          </div>
        </article>
        <div v-if="remaining > 0" class="rag-load-more">
          <button class="btn" data-action="load-more-results" @click="emit('load-more')">加载更多</button>
          <span>还有 {{ remaining }} 条已获取结果</span>
        </div>
        <p v-else-if="session.total > session.hits.length" class="rag-search-limit-note">已显示本次返回的 {{ session.hits.length }} 条结果；可缩小章节或检索范围继续查找。</p>
      </div>
      <slot name="drawer"></slot>
    </template>
  </div>
</template>
