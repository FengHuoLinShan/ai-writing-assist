<template>
  <div class="card generate-world-source-bar">
    <div>
      <span class="generate-world-source-label">来源</span>
      <strong>{{ sourceLabel }}</strong>
      <span v-if="sourcePage" class="badge">v{{ sourcePage.version_number || 1 }}</span>
    </div>
    <button v-if="sourcePageId" class="btn btn-sm" data-action="return-world-bible" @click="$emit('return-world-bible')">返回世界书</button>
  </div>
  <div v-if="warning" class="generate-template-warning">{{ warning }}</div>
  <div class="generate-world-targets" role="group" aria-label="生成目标">
    <button class="generate-world-target" :class="{ active: targetKind === 'core_entity' }" type="button" :aria-pressed="targetKind === 'core_entity'" data-action="select-world-target" @click="$emit('select-target', 'core_entity')">世界对象</button>
    <button class="generate-world-target" :class="{ active: targetKind === 'world_bible_page' }" type="button" :aria-pressed="targetKind === 'world_bible_page'" :disabled="!sourcePageId" data-action="select-world-target" @click="$emit('select-target', 'world_bible_page')">完善当前页</button>
    <button class="generate-world-target" :class="{ active: targetKind === 'world_bible_new_page' }" type="button" :aria-pressed="targetKind === 'world_bible_new_page'" data-action="select-world-target" @click="$emit('select-target', 'world_bible_new_page')">新建世界书页</button>
  </div>

  <div v-if="targetKind === 'core_entity'" id="generate-template-row" class="generate-template-row generate-template-row--toolbar">
    <button v-for="template in templates" :key="template.value" class="generate-template-btn" :class="{ active: selectedTemplateId === template.value }"
      type="button" :aria-pressed="selectedTemplateId === template.value" data-action="select-object-template" :title="template.hint || template.prompt || ''" @click="selectedTemplateId = template.value">{{ template.label }}</button>
    <button class="btn btn-sm" data-action="edit-object-templates" @click="$emit('edit-templates')">编辑对象模板</button>
  </div>
  <div v-else-if="targetKind === 'world_bible_page'" class="generate-world-config">将以当前服务器工作稿优先，生成一份完整的整页重构提案。</div>
  <div v-else class="generate-world-config">
    <label>页面类别
      <select id="generate-new-page-type" v-model="newPageType" class="form-select">
        <option v-for="category in categories.filter((item) => item.status !== 'archived')" :key="category.category_key" :value="category.category_key">{{ category.name || category.category_key }}</option>
      </select>
    </label>
    <label>页面模板（仅作资料组织参考）
      <select id="generate-new-page-template" v-model="newPageTemplateKey" class="form-select">
        <option value="">不指定</option>
        <option v-for="template in pageTemplates.filter((item) => item.status !== 'archived')" :key="template.template_key" :value="template.template_key">{{ template.name || template.template_key }} · v{{ template.version_number || 1 }}</option>
      </select>
    </label>
  </div>

  <div class="generate-chatbox">
    <div class="generate-chat-main">
      <div class="card generate-chat-panel">
        <div id="generate-chat-messages" class="generate-chat-messages">
          <p v-if="!messages.length" class="generate-empty-copy">可以直接说“帮我设计一个反派”，也可以先粘贴外部聊完的内容。</p>
          <div v-for="(message, index) in messages" v-else :key="index" class="generate-chat-message" :class="[message.role, { pending: message.pending, error: message.error }]">
            <div class="generate-chat-role">{{ message.role === 'assistant' ? 'AI' : '你' }}</div>
            <div class="generate-chat-bubble">{{ message.content }}</div>
          </div>
        </div>
        <div class="generate-composer">
          <textarea
            id="generate-chat-input"
            v-model="composer"
            class="generate-chat-input"
            rows="4"
            placeholder="说明你想创造、推敲或重构的世界设定。AI 会同时关注创意与逻辑。"
            @compositionstart="composing = true"
            @compositionend="composing = false"
            @keydown="onComposerKeydown"
          />
          <button
            class="btn btn-sm generate-composer-send"
            data-action="send-chat-message"
            type="button"
            :disabled="busy || !composer.trim()"
            @click="$emit('send-chat')"
          >{{ chatPending ? "发送中…" : "发送" }}</button>
        </div>
      </div>
    </div>
    <details class="workspace-rail generate-side-rail workspace-rail--right" :open="railOpen" :data-workspace-rail-key="railKey" @toggle="onRailToggle">
      <summary class="workspace-rail__summary" :aria-label="`${railOpen ? '收起' : '展开'}上下文与结果`">
        <span class="workspace-rail__title">上下文与结果</span>
        <span class="workspace-rail__chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="workspace-rail__body"><div class="generate-chat-side">
        <div class="card generate-settings-card">
          <div class="generate-card-title-row"><div class="card-title">上下文</div></div>
          <div class="generate-side-options">
            <label class="generate-quality-toggle"><input id="generate-quality-pro" v-model="qualityPro" type="checkbox" /><span>高质量</span></label>
            <label class="generate-quality-toggle"><input id="generate-include-world-synopsis" v-model="includeWorldSynopsis" type="checkbox" /><span>使用世界观简介</span></label>
            <label class="generate-quality-toggle generate-quality-toggle--stacked"><span>已发布 AI 参考规则（显式启用）</span>
              <select id="generate-activation-profile" v-model="activationProfileId" class="form-select"><option :value="null">不启用</option><option v-for="profile in activationProfiles" :key="profile.id" :value="profile.id">{{ profile.name }} · v{{ profile.version_number }}</option></select>
            </label>
            <div id="generate-chat-context-usage"><button v-if="chatContextUsage" class="btn btn-sm" data-action="view-generation-context" @click="$emit('view-context', 'chat')">查看最近聊天上下文</button></div>
            <button class="btn btn-sm" data-action="select-source-chapters" @click="$emit('select-chapters')">附带正文</button>
          </div>
          <p class="generate-empty-copy">单次最多附带 20 章；长对话只发送最近 40 条消息。</p>
          <div id="generate-selected-chapters" class="generate-attachment-summary">{{ chapterSummary }}</div>
          <details class="generate-world-context-panel"><summary>展开精确上下文</summary>
            <label>当前场景<select id="generate-world-scene" v-model="selectedSceneId" class="form-select"><option value="">不指定</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || scene.name || '未命名场景' }}</option></select></label>
            <label>剧情线<select id="generate-world-threads" v-model="selectedThreadIds" class="form-select" multiple size="4"><option v-for="thread in threads" :key="thread.id" :value="thread.id">{{ thread.title || thread.name || thread.id }}</option></select></label>
            <label>人物（未显式选择时由服务器 Top-6）<select id="generate-world-characters" v-model="selectedCharacterIds" class="form-select" multiple size="4"><option v-for="item in characters" :key="characterId(item)" :value="characterId(item)">{{ item.name || item.display_name || characterId(item) }}</option></select></label>
            <label>物品 / 世界对象（未显式选择时由服务器 Top-16）<select id="generate-world-entities" v-model="selectedEntityIds" class="form-select" multiple size="5"><option v-for="item in entities" :key="item.id" :value="item.id">{{ item.name || item.id }} · {{ item.entity_type || '对象' }}</option></select></label>
          </details>
        </div>
        <div class="card"><div class="card-title">结果</div><div id="generate-result" class="generate-result">
          <div v-if="loadingResult" class="loading">正在{{ generateLabel }}...</div>
          <template v-else>
            <p v-if="resultError" class="generate-error-text">{{ resultError }}</p>
            <WorldResult v-if="result || !resultError" :result="result" :baseline="sourceDraft || sourcePage" :categories="categories" :context-usage="entityContextUsage" :proposal-draft="proposalDraft" :proposal-reset-token="proposalResetToken" :recovered="recoveredPageProposal" :busy="busy"
              @apply="$emit('apply-page', $event)" @dirty="$emit('proposal-dirty', $event)" @proposal-edit="$emit('proposal-edit', $event)" @clear="$emit('clear-result')" @continue-chat="focusComposer" @open-review="$emit('open-review')" @view-context="$emit('view-context', 'entity')" />
          </template>
        </div></div>
      </div></div>
    </details>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"
import { characterId } from "../logic/generateLogic.js"
import WorldResult from "./WorldResult.vue"

const props = defineProps({
  projectId: String, sourcePageId: String, targetKind: String, sourcePage: Object, sourceDraft: Object,
  warning: String, templates: Array, activationProfiles: Array, categories: Array, pageTemplates: Array,
  scenes: Array, threads: Array, characters: Array, entities: Array, result: Object,
  chatContextUsage: Object, entityContextUsage: Object, proposalDraft: Object, proposalResetToken: Number, recoveredPageProposal: Boolean, busy: Boolean, chatPending: Boolean, loadingResult: Boolean, resultError: String,
})
const emit = defineEmits(["send-chat", "select-target", "edit-templates", "return-world-bible", "select-chapters", "apply-page", "proposal-dirty", "proposal-edit", "clear-result", "open-review", "view-context"])
const selectedTemplateId = defineModel("selectedTemplateId", { type: String, required: true })
const messages = defineModel("messages", { type: Array, required: true })
const composer = defineModel("composer", { type: String, required: true })
const qualityMode = defineModel("qualityMode", { type: String, required: true })
const includeWorldSynopsis = defineModel("includeWorldSynopsis", { type: Boolean, required: true })
const activationProfileId = defineModel("activationProfileId", { default: null })
const selectedChapters = defineModel("selectedChapters", { type: Array, required: true })
const selectedSceneId = defineModel("selectedSceneId", { type: String, required: true })
const selectedThreadIds = defineModel("selectedThreadIds", { type: Array, required: true })
const selectedCharacterIds = defineModel("selectedCharacterIds", { type: Array, required: true })
const selectedEntityIds = defineModel("selectedEntityIds", { type: Array, required: true })
const newPageType = defineModel("newPageType", { type: String, required: true })
const newPageTemplateKey = defineModel("newPageTemplateKey", { type: String, required: true })
const qualityPro = computed({ get: () => qualityMode.value === "pro", set: (value) => { qualityMode.value = value ? "pro" : "fast" } })
const sourceLabel = computed(() => {
  const source = props.sourceDraft || props.sourcePage
  return source ? `${source.title || "未命名页面"}${props.sourceDraft ? " · 工作稿" : " · 已发布"}` : "整个项目"
})
const chapterSummary = computed(() => selectedChapters.value.length ? `已附带 ${selectedChapters.value.length} 章：${selectedChapters.value.map((item) => `第${item.chapter_index}章`).join("、")}` : "未附带正文")
const generateLabel = computed(() => ({ core_entity: "生成世界对象建议", world_bible_page: "生成整页提案", world_bible_new_page: "生成新页提案" })[props.targetKind] || "生成建议")
const railKey = computed(() => `workspace-rail:${props.projectId || "global"}:generate:assistant`)
const railOpen = ref(readRail())
const composing = ref(false)
function readRail() { try { return sessionStorage.getItem(`workspace-rail:${props.projectId || "global"}:generate:assistant`) !== "closed" } catch { return true } }
function onRailToggle(event) { railOpen.value = event.target.open; try { sessionStorage.setItem(railKey.value, railOpen.value ? "open" : "closed") } catch {} }
async function focusComposer() { await nextTick(); document.getElementById("generate-chat-input")?.focus() }
function onComposerKeydown(event) {
  if (composing.value || event.isComposing) return
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault()
    if (!props.busy && composer.value.trim()) emit("send-chat")
  }
}
defineExpose({ focusComposer })
</script>
