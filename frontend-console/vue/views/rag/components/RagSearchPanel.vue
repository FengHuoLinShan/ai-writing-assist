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
  searchPending: { type: Boolean, default: false },
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
    ? "只查正文里的原词，并汇总每章的出现位置。"
    : "按意思查找，适合核对设定、人物和事件。"
))

const contentModeHelpText = computed(() => (
  form.value.contentMode === "working"
    ? "包含当前工作稿，适合核对正在修改的内容。"
    : "只查已发布正文，结果更稳定。"
))

const advancedSummaryText = computed(() => (
  summary.value.length ? summary.value.join("、") : "视角、章节和资料范围"
))

// 字面搜索锁定范围为正文（vanilla _toggleSearchScopes）
watch(() => form.value.searchKind, (kind) => {
  if (kind === "literal") {
    form.value.scopes = ["manuscript"]
    form.value.includePending = false
  }
})

function scopeDisabled(scope) {
  return form.value.searchKind === "literal" && scope !== "manuscript"
}

function toggleScope(scope, checked) {
  const current = new Set(form.value.scopes)
  if (checked) current.add(scope)
  else current.delete(scope)
  form.value.scopes = current.size ? [...current] : ["manuscript"]
  if (!form.value.scopes.includes("world")) form.value.includePending = false
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
  <form class="card novel-search-panel" @submit.prevent="emit('submit')">
    <header class="rag-search-panel__header">
      <h2 class="card-title">查找小说资料</h2>
      <p class="rag-empty-copy">回查人物、场景、设定和原文出处，为当前创作核对事实。</p>
    </header>
    <div class="rag-search-form">
      <label class="rag-query-field" for="rag-search-input">
        <span>想查什么</span>
        <input
          class="form-input"
          id="rag-search-input"
          aria-label="检索关键词"
          autocomplete="off"
          placeholder="例如：旧塔铜铃、林晚的身世、雨夜原文…"
          required
          v-model="form.query"
        />
      </label>
      <div class="rag-search-actions">
        <button type="submit" class="btn btn-primary" data-action="do-search" :disabled="searchPending">{{ searchPending ? "查找中…" : "查找资料" }}</button>
        <button type="button" class="btn" data-action="ask-world" :disabled="askWorldPending" @click="emit('ask-world')">{{ askWorldPending ? "问答中…" : "问世界" }}</button>
      </div>
    </div>
    <p class="rag-search-action-help"><strong>查找资料</strong>会列出可核对的来源；<strong>问世界</strong>会用正式资料直接回答并附上来源。</p>

    <div class="novel-search-filters rag-search-common-filters" aria-label="常用查找条件">
      <label>查找方式
        <select class="form-input" id="rag-search-kind" aria-describedby="rag-search-kind-help" v-model="form.searchKind">
          <option value="smart">智能搜索</option>
          <option value="literal">字面搜索</option>
        </select>
        <small class="rag-search-kind-help" id="rag-search-kind-help">{{ kindHelpText }}</small>
      </label>
      <label>查找哪一版
        <select class="form-input" id="rag-content-mode" aria-describedby="rag-content-mode-help" v-model="form.contentMode">
          <option value="canonical">已发布</option>
          <option value="working">最新工作稿</option>
        </select>
        <small class="rag-search-kind-help" id="rag-content-mode-help">{{ contentModeHelpText }}</small>
      </label>
    </div>

    <details
      class="rag-advanced-filters"
      data-role="rag-advanced-filters"
      :open="advancedOpen"
      @toggle="advancedOpen = $event.target.open"
    >
      <summary>
        <span class="rag-advanced-summary__title">更多条件</span>
        <span class="rag-advanced-summary__value" data-role="rag-advanced-summary">{{ advancedSummaryText }}</span>
      </summary>
      <div class="rag-advanced-filters__body">
        <fieldset class="rag-filter-group">
          <legend>从哪里查</legend>
          <div class="novel-search-filters rag-chapter-filters">
            <label>从第几章 <input class="form-input" id="rag-chapter-from" data-rag-advanced-filter type="number" min="1" inputmode="numeric" placeholder="第一章" v-model="form.chapterFrom" :aria-invalid="chapterRangeError ? 'true' : undefined" :aria-describedby="chapterRangeError ? 'rag-chapter-range-error' : undefined" /></label>
            <label>到第几章 <input class="form-input" id="rag-chapter-to" data-rag-advanced-filter type="number" min="1" inputmode="numeric" placeholder="最后一章" v-model="form.chapterTo" :aria-invalid="chapterRangeError ? 'true' : undefined" :aria-describedby="chapterRangeError ? 'rag-chapter-range-error' : undefined" /></label>
          </div>
          <p v-if="chapterRangeError" id="rag-chapter-range-error" class="rag-chapter-range-error" role="alert">{{ chapterRangeError }}</p>
          <div class="novel-search-scopes" role="group" aria-labelledby="rag-search-scope-label">
            <span id="rag-search-scope-label">资料范围</span>
            <label><input type="checkbox" data-search-scope="manuscript" data-rag-advanced-filter :checked="form.scopes.includes('manuscript')" :disabled="scopeDisabled('manuscript')" @change="toggleScope('manuscript', $event.target.checked)" /> 正文</label>
            <label><input type="checkbox" data-search-scope="world" data-rag-advanced-filter :checked="form.scopes.includes('world')" :disabled="scopeDisabled('world')" @change="toggleScope('world', $event.target.checked)" /> 世界设定</label>
            <label><input type="checkbox" data-search-scope="outline" data-rag-advanced-filter :checked="form.scopes.includes('outline')" :disabled="scopeDisabled('outline')" @change="toggleScope('outline', $event.target.checked)" /> 故事结构</label>
          </div>
          <p v-if="form.searchKind === 'literal'" class="rag-filter-hint">字面搜索只查正文；切回智能搜索即可查世界设定和故事结构。</p>
          <label class="rag-pending-option" for="rag-include-pending">
            <span><input type="checkbox" id="rag-include-pending" data-rag-advanced-filter :disabled="!form.scopes.includes('world')" aria-describedby="rag-include-pending-help" v-model="form.includePending" /> 同时查找待处理的世界设定</span>
            <small id="rag-include-pending-help">{{ form.scopes.includes('world') ? '这些内容还未采用，结果需要你确认。' : '先勾选“世界设定”，才能包含待处理内容。' }}</small>
          </label>
        </fieldset>

        <fieldset class="rag-filter-group">
          <legend>按谁能看到的内容查</legend>
          <div class="novel-search-filters">
            <label>可见视角
              <select class="form-input" id="rag-visibility-mode" data-rag-advanced-filter v-model="form.visibilityMode">
                <option value="author">作者（全部可见）</option>
                <option value="reader">读者（按阅读进度）</option>
                <option value="character">角色（按人物所知）</option>
              </select>
            </label>
            <label id="rag-cutoff-field" :hidden="form.visibilityMode === 'author'">可见到第几章 <input class="form-input" id="rag-cutoff-chapter" data-rag-advanced-filter type="number" min="1" inputmode="numeric" v-model="form.cutoffChapter" /></label>
            <label id="rag-cutoff-scene-field" :hidden="form.visibilityMode === 'author'">可见到哪个场景
              <select class="form-input" id="rag-cutoff-scene-id" data-rag-advanced-filter v-model="form.cutoffSceneId">
                <option value="">可选</option>
                <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ sceneOptionLabel(scene) }}</option>
              </select>
            </label>
            <label id="rag-cutoff-offset-field" :hidden="form.visibilityMode === 'author'">本章前多少个字可见 <input class="form-input" id="rag-cutoff-offset" data-rag-advanced-filter type="number" min="0" inputmode="numeric" placeholder="可选" v-model="form.cutoffOffset" /></label>
            <label id="rag-character-field" :hidden="form.visibilityMode !== 'character'">视角人物
              <select class="form-input" id="rag-character-id" data-rag-advanced-filter v-model="form.characterId">
                <option value="">请选择</option>
                <option v-for="character in characters" :key="characterIdOf(character)" :value="characterIdOf(character)">{{ character.name || "未命名人物" }}</option>
              </select>
            </label>
          </div>
        </fieldset>
      </div>
    </details>
  </form>
</template>
