<script setup>
import { computed, ref, watch } from "vue"
import { advancedFilterSummary } from "../logic/searchPayload.js"

/**
 * 检索面板（表单 + 高级筛选）— DOM 契约对齐 vanilla _renderSearch。
 * form 为 v-model 对象（由 RagSearchView 初始化自路由状态）。
 */
const form = defineModel("form", { type: Object, required: true })

const props = defineProps({
  characters: { type: Array, default: () => [] },
  scenes: { type: Array, default: () => [] },
  chapterRangeError: { type: String, default: "" },
  askWorldPending: { type: Boolean, default: false },
})

const emit = defineEmits(["submit", "ask-world"])

const summary = computed(() => advancedFilterSummary(form.value, {
  characters: props.characters,
  scenes: props.scenes,
}))

// 摘要或范围错误出现时展开；错误被修正后不自动收起，保留作者的阅读位置。
const hasAdvancedCondition = computed(() => (
  summary.value.length > 0 || Boolean(props.chapterRangeError)
))
const advancedOpen = ref(hasAdvancedCondition.value)
watch(hasAdvancedCondition, (value) => {
  if (value) advancedOpen.value = true
})

const kindHelpText = computed(() => (
  form.value.searchKind === "literal"
    ? "字面搜索：查找完全相同的文字，并按章节汇总该章的全部出现位置。"
    : "智能搜索：按语义相关性查找，并把同一章的相关片段聚合显示。"
))

// 字面搜索锁定范围为正文（vanilla _toggleSearchScopes）
watch(() => form.value.searchKind, (kind) => {
  if (kind === "literal") form.value.scopes = ["manuscript"]
})

function scopeDisabled(scope) {
  return form.value.searchKind === "literal" && scope !== "manuscript"
}

function toggleScope(scope, checked) {
  const current = new Set(form.value.scopes)
  if (checked) current.add(scope)
  else current.delete(scope)
  form.value.scopes = current.size ? [...current] : ["manuscript"]
}

function sceneOptionLabel(scene) {
  const title = scene.title || `场景 ${scene.scene_index ?? "-"}`
  const chapters = (scene.chapter_ids || []).join("/")
  return chapters ? `${title} · 第 ${chapters} 章` : title
}

function characterIdOf(character) {
  return character.id || character.entity_id || ""
}
</script>

<template>
  <div class="card novel-search-panel">
    <div class="card-title">查找小说资料</div>
    <p class="rag-empty-copy">回查人物、场景、设定和原文出处，为当前创作核对事实。</p>
    <div class="rag-search-form">
      <input
        class="form-input"
        id="rag-search-input"
        aria-label="检索关键词"
        placeholder="输入问题、原文或对象关键词…"
        v-model="form.query"
        @keydown.enter="emit('submit')"
      />
      <div class="rag-search-actions">
        <button class="btn btn-primary" data-action="do-search" @click="emit('submit')">检索</button>
        <button class="btn" data-action="ask-world" :disabled="askWorldPending" @click="emit('ask-world')">{{ askWorldPending ? "问答中…" : "问世界" }}</button>
      </div>
    </div>
    <p class="rag-ask-world-note">“问世界”只按当前项目的作者视角回读正式世界笔记与已发布正文，并为回答附上可打开的来源。</p>
    <div class="novel-search-filters">
      <label>检索方式
        <select class="form-input" id="rag-search-kind" v-model="form.searchKind">
          <option value="smart">智能搜索</option>
          <option value="literal">字面搜索</option>
        </select>
      </label>
      <label>正文版本
        <select class="form-input" id="rag-content-mode" v-model="form.contentMode">
          <option value="canonical">已发布</option>
          <option value="working">最新工作稿</option>
        </select>
      </label>
    </div>
    <p class="rag-search-kind-help" id="rag-search-kind-help">{{ kindHelpText }}</p>
    <details
      class="rag-advanced-filters"
      data-role="rag-advanced-filters"
      :open="advancedOpen"
      @toggle="advancedOpen = $event.target.open"
    >
      <summary>
        <span>高级筛选</span>
        <span data-role="rag-advanced-summary">{{ summary.length ? ` · ${summary.join("、")}` : "" }}</span>
      </summary>
      <div class="novel-search-filters">
        <label>可见视角
          <select class="form-input" id="rag-visibility-mode" data-rag-advanced-filter v-model="form.visibilityMode">
            <option value="author">作者</option>
            <option value="reader">读者</option>
            <option value="character">角色</option>
          </select>
        </label>
        <label>起始章 <input class="form-input" id="rag-chapter-from" data-rag-advanced-filter type="number" min="1" placeholder="可选" v-model="form.chapterFrom" :aria-invalid="chapterRangeError ? 'true' : undefined" :aria-describedby="chapterRangeError ? 'rag-chapter-range-error' : undefined" /></label>
        <label>结束章 <input class="form-input" id="rag-chapter-to" data-rag-advanced-filter type="number" min="1" placeholder="可选" v-model="form.chapterTo" :aria-invalid="chapterRangeError ? 'true' : undefined" :aria-describedby="chapterRangeError ? 'rag-chapter-range-error' : undefined" /></label>
        <label id="rag-cutoff-field" :hidden="form.visibilityMode === 'author'">可见截止章 <input class="form-input" id="rag-cutoff-chapter" data-rag-advanced-filter type="number" min="1" v-model="form.cutoffChapter" /></label>
        <label id="rag-cutoff-scene-field" :hidden="form.visibilityMode === 'author'">截止场景
          <select class="form-input" id="rag-cutoff-scene-id" data-rag-advanced-filter v-model="form.cutoffSceneId">
            <option value="">可选</option>
            <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ sceneOptionLabel(scene) }}</option>
          </select>
        </label>
        <label id="rag-cutoff-offset-field" :hidden="form.visibilityMode === 'author'">章内截止位置 <input class="form-input" id="rag-cutoff-offset" data-rag-advanced-filter type="number" min="0" placeholder="可选字符偏移" v-model="form.cutoffOffset" /></label>
        <label id="rag-character-field" :hidden="form.visibilityMode !== 'character'">视角人物
          <select class="form-input" id="rag-character-id" data-rag-advanced-filter v-model="form.characterId">
            <option value="">请选择</option>
            <option v-for="character in characters" :key="characterIdOf(character)" :value="characterIdOf(character)">{{ character.name || "未命名人物" }}</option>
          </select>
        </label>
      </div>
      <p v-if="chapterRangeError" id="rag-chapter-range-error" class="rag-chapter-range-error" role="alert">{{ chapterRangeError }}</p>
      <div class="novel-search-scopes">
        <span>检索范围</span>
        <label><input type="checkbox" data-search-scope="manuscript" data-rag-advanced-filter :checked="form.scopes.includes('manuscript')" :disabled="scopeDisabled('manuscript')" @change="toggleScope('manuscript', $event.target.checked)" /> 正文</label>
        <label><input type="checkbox" data-search-scope="world" data-rag-advanced-filter :checked="form.scopes.includes('world')" :disabled="scopeDisabled('world')" @change="toggleScope('world', $event.target.checked)" /> 世界对象</label>
        <label><input type="checkbox" data-search-scope="outline" data-rag-advanced-filter :checked="form.scopes.includes('outline')" :disabled="scopeDisabled('outline')" @change="toggleScope('outline', $event.target.checked)" /> 结构</label>
        <label title="待处理内容尚未采用，纳入后需人工检查">
          <input type="checkbox" id="rag-include-pending" data-rag-advanced-filter v-model="form.includePending" /> 包含待处理世界对象
        </label>
      </div>
    </details>
  </div>
</template>
