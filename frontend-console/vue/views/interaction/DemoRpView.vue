<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import "./rp-redesign.css"
import { getApi } from "../../bridge/index.js"
import { interactionOperationKey } from "./interactionSession.js"
import RpMarkdownContent from "./RpMarkdownContent.vue"
import { safeInteractionError } from "./interactionErrors.js"
import {
  clearEphemeralDeepSeekKey,
  readEphemeralDeepSeekKey,
  writeEphemeralDeepSeekKey,
} from "../../../shared/ephemeralDeepSeekKey.js"

const api = getApi()
const authConfig = globalThis.accountAuthConfig || {}
const source = ref(null)
const sessionReady = ref(false)
const loading = ref(true)
const busy = ref(false)
const error = ref("")
const apiKey = ref(readEphemeralDeepSeekKey())
const showKey = ref(false)
const opening = ref("")
const composer = ref("")
const actionOptions = ref(true)
const consent = ref(false)
const journey = ref(null)
const messages = ref([])
const attempt = ref(null)
const streamText = ref("")
const streamError = ref("")
const editingNodeId = ref("")
const branches = ref({})
const overview = ref(null)
const overviewOpen = ref(false)
const overviewEditing = ref(false)
const overviewDraft = ref({})
let streamController = null
let disposed = false

const overviewSections = [
  { key: "long_term_agreements", label: "长期约定", maxLength: 4000, description: "希望持续遵守的规则和偏好。" },
  { key: "world_and_start", label: "世界与起点" },
  { key: "player_character", label: "我的角色" },
  { key: "current_situation", label: "当前局面" },
  { key: "important_people_and_factions", label: "重要人物与势力" },
  { key: "key_turning_points", label: "关键转折" },
  { key: "open_threads", label: "正在发展的事情" },
  { key: "must_remember", label: "必须继续记住" },
]

const isGenerating = computed(() => ["pending", "preparing_context", "running"].includes(attempt.value?.status))
const sourceAnchor = computed(() => source.value?.anchors?.[0] || null)
const sourceSetup = computed(() => {
  if (!source.value?.id || !sourceAnchor.value?.anchor_key) return null
  return {
    source_revision_id: source.value.id,
    progress_anchor_key: sourceAnchor.value.anchor_key,
    player_identity: { kind: "original", name: "旅人" },
    pinned_reference_keys: [],
  }
})
const latestStory = computed(() => [...messages.value].reverse().find((message) => (
  message.role === "assistant" && message.message_kind === "story"
)) || null)
const actionChoices = computed(() => {
  const choices = latestStory.value?.action_options || journey.value?.action_options || []
  return Array.isArray(choices) ? choices : []
})
const termsUrl = String(authConfig.terms_url || "")
const privacyUrl = String(authConfig.privacy_url || "")

function textOf(message) {
  return String(message?.content || message?.text || "")
}

function cloneOverviewSections(sections) {
  return Object.fromEntries(overviewSections.map(({ key }) => [key, String(sections?.[key] || "")]))
}

function clearKey() {
  abortStream()
  apiKey.value = ""
  clearEphemeralDeepSeekKey()
}

function saveKey() {
  apiKey.value = writeEphemeralDeepSeekKey(apiKey.value)
  if (isGenerating.value && attempt.value?.id && !streamController) void followAttempt(attempt.value)
}

function resetExpiredSession() {
  clearKey()
  sessionReady.value = false
}

function showError(requestError, fallback) {
  if (requestError?.status === 401) resetExpiredSession()
  error.value = requestError?.status === 401
    ? "演示会话已过期，请重新开始；临时 Key 已清除。"
    : fallback
}

async function initialize() {
  if (loading.value) return
  loading.value = true
  error.value = ""
  try {
    source.value = await api.interactions.demoSource()
    sessionReady.value = await restoreExistingDemoJourney()
  } catch (requestError) {
    showError(requestError, "演示 RP 暂时无法准备，请重试。")
  } finally {
    loading.value = false
  }
}

async function restoreExistingDemoJourney() {
  try {
    const result = await api.interactions.listDemoJourneys({ status: "active", limit: 1 })
    const recent = result?.items?.[0]
    if (!recent?.id) return true
    const restored = await api.interactions.getJourney(recent.id)
    if (disposed || restored?.id !== recent.id) return true
    applyJourney(restored)
    if (isGenerating.value && readEphemeralDeepSeekKey()) void followAttempt(attempt.value)
    return true
  } catch (requestError) {
    if (requestError?.status === 401) return false
    throw requestError
  }
}

async function startAnonymousSession() {
  if (sessionReady.value) return true
  if (!consent.value) {
    error.value = "请先阅读并同意用户协议和隐私政策。"
    return false
  }
  try {
    await api.auth.anonymousRp({ accept_terms: true, accept_privacy: true })
    sessionReady.value = true
    return true
  } catch (requestError) {
    showError(requestError, "暂时无法开始演示会话，请重试。")
    return false
  }
}

function applyJourney(nextJourney) {
  if (!nextJourney) return
  journey.value = nextJourney
  messages.value = [...(nextJourney.messages || [])]
  attempt.value = nextJourney.active_attempt || attempt.value
}

async function refreshJourney() {
  if (!journey.value?.id) return null
  const nextJourney = await api.interactions.getJourney(journey.value.id)
  if (!disposed && nextJourney?.id === journey.value.id) applyJourney(nextJourney)
  return nextJourney
}

function abortStream() {
  streamController?.abort()
  streamController = null
}

function setTerminalStreamError(data) {
  if (!["failed", "cancelled"].includes(data?.status)) return
  streamError.value = data?.error_message
    || attempt.value?.error_message
    || safeInteractionError({ error_kind: data?.error_kind || attempt.value?.error_kind }).message
}

async function followAttempt(nextAttempt) {
  if (!nextAttempt?.id || disposed) return
  const key = readEphemeralDeepSeekKey()
  if (!key) {
    streamError.value = "请输入临时 DeepSeek API Key 后再开始生成。"
    return
  }
  abortStream()
  attempt.value = nextAttempt
  streamText.value = nextAttempt.visible_text || ""
  streamError.value = ""
  const controller = new AbortController()
  streamController = controller
  try {
    for await (const event of api.interactions.streamDemoAttempt(
      journey.value.id,
      nextAttempt.id,
      key,
      { signal: controller.signal },
    )) {
      if (disposed || controller.signal.aborted) return
      if (event.event === "chunk") {
        streamText.value += event.data?.text || ""
      } else if (event.event === "status") {
        attempt.value = { ...attempt.value, ...event.data, id: nextAttempt.id }
        setTerminalStreamError(event.data)
      } else if (event.event === "done") {
        attempt.value = { ...attempt.value, ...event.data, id: nextAttempt.id }
        setTerminalStreamError(event.data)
      }
    }
    if (!disposed && !controller.signal.aborted) await refreshJourney()
  } catch (requestError) {
    if (!controller.signal.aborted && !disposed) {
      if (requestError?.status === 401) resetExpiredSession()
      await refreshJourney().catch(() => null)
      streamError.value = requestError?.status === 401
        ? "演示会话或临时 Key 已失效，请重新输入 Key 后重试。"
        : (attempt.value?.error_message
          || (["failed", "cancelled"].includes(attempt.value?.status)
            ? safeInteractionError({ error_kind: attempt.value?.error_kind }).message
            : "流式连接中断；开场和已显示内容仍保留，可以重试。"))
    }
  }
}

async function startJourney() {
  const value = opening.value.trim()
  saveKey()
  if (!value || busy.value || isGenerating.value) return
  if (!apiKey.value) {
    error.value = "请输入临时 DeepSeek API Key 后再开始生成。"
    return
  }
  if (!sourceSetup.value) {
    error.value = "演示作品资料尚未准备好，请稍后重试。"
    return
  }
  busy.value = true
  error.value = ""
  try {
    if (!await startAnonymousSession()) return
    const result = await api.interactions.createDemoJourney({
      opening_text: value,
      source_setup: sourceSetup.value,
      action_options_enabled: actionOptions.value,
      see_sea_enabled: false,
      web_search_enabled: false,
      idempotency_key: interactionOperationKey("demo-opening"),
    })
    if (disposed) return
    applyJourney(result.journey)
    opening.value = ""
    if (result.attempt) void followAttempt(result.attempt)
  } catch (requestError) {
    showError(requestError, "这次旅程没能开始；开场仍保留，可以重试。")
  } finally {
    if (!disposed) busy.value = false
  }
}

async function mutate(run, { clearComposer = true } = {}) {
  if (!journey.value || busy.value || isGenerating.value) return
  saveKey()
  if (!apiKey.value) {
    error.value = "请输入临时 DeepSeek API Key 后再继续生成。"
    return
  }
  busy.value = true
  error.value = ""
  try {
    const result = await run()
    if (disposed) return
    applyJourney(result.journey)
    if (clearComposer) composer.value = ""
    editingNodeId.value = ""
    if (result.attempt) void followAttempt(result.attempt)
  } catch (requestError) {
    showError(requestError, "这次操作未完成；你的输入仍保留，可以重试。")
  } finally {
    if (!disposed) busy.value = false
  }
}

async function send() {
  const content = composer.value.trim()
  if (!content) return
  const payload = {
    content,
    expected_selection_epoch: journey.value.selection_epoch,
    idempotency_key: interactionOperationKey(editingNodeId.value ? "demo-correct" : "demo-message"),
  }
  if (editingNodeId.value) {
    await mutate(() => api.interactions.editUserMessage(journey.value.id, editingNodeId.value, payload))
  } else {
    await mutate(() => api.interactions.sendMessage(journey.value.id, payload))
  }
}

function onComposerKeydown(event) {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault()
    void send()
  }
}

async function regenerate(message) {
  await mutate(() => api.interactions.regenerate(journey.value.id, message.id, {
    expected_selection_epoch: journey.value.selection_epoch,
    idempotency_key: interactionOperationKey("demo-regenerate"),
  }), { clearComposer: false })
}

function beginCorrection(message) {
  editingNodeId.value = message.id
  composer.value = textOf(message)
}

async function loadBranches(message) {
  if (!journey.value?.id || branches.value[message.id]) return
  try {
    const result = await api.interactions.listBranches(journey.value.id, message.id)
    branches.value = { ...branches.value, [message.id]: result.items || result || [] }
  } catch (requestError) {
    showError(requestError, "分支暂时无法载入，请稍后重试。")
  }
}

async function selectBranch(node) {
  const nodeId = node?.id || node?.node_id
  if (!nodeId) return
  await mutate(() => api.interactions.selectBranch(journey.value.id, nodeId, {
    expected_selection_epoch: journey.value.selection_epoch,
  }), { clearComposer: false })
  branches.value = {}
}

function chooseAction(choice) {
  composer.value = typeof choice === "string"
    ? choice
    : String(choice?.label || choice?.content || choice?.text || "")
  if (composer.value) void send()
}

async function openOverview() {
  if (!journey.value?.id) return
  overviewOpen.value = true
  try {
    overview.value = await api.interactions.getOverview(journey.value.id)
    overviewDraft.value = cloneOverviewSections(overview.value?.sections)
    overviewEditing.value = false
  } catch (requestError) {
    showError(requestError, "回顾暂时无法载入，请稍后重试。")
  }
}

async function saveOverview() {
  if (!overview.value || busy.value) return
  busy.value = true
  try {
    overview.value = await api.interactions.updateOverview(journey.value.id, {
      sections: overviewDraft.value,
      expected_overview_epoch: overview.value.overview_epoch,
      expected_selection_epoch: journey.value.selection_epoch,
      base_revision_id: overview.value.base_revision_id,
      base_selected_leaf_node_id: overview.value.base_selected_leaf_node_id,
      base_selected_path_hash: overview.value.base_selected_path_hash,
    })
    overviewEditing.value = false
  } catch (requestError) {
    showError(requestError, "回顾修改没有保存；内容仍保留，可以重试。")
  } finally {
    if (!disposed) busy.value = false
  }
}

onMounted(() => {
  loading.value = false
  void initialize()
})
onBeforeUnmount(() => {
  disposed = true
  abortStream()
})
</script>

<template>
  <main class="demo-rp-page" :aria-busy="loading || busy">
    <header class="demo-rp-header">
      <div>
        <span class="demo-rp-eyebrow">DEMO ROLE PLAY</span>
        <h1>进入演示故事</h1>
        <p v-if="source">{{ source.title }} · 已准备的作品资料</p>
        <p v-else>用一把临时 Key 体验流式互动故事。</p>
      </div>
      <a class="demo-rp-back" href="?demo=1#today">查看演示项目</a>
    </header>

    <section v-if="error" class="demo-rp-error" role="alert">
      <span>{{ error }}</span><button type="button" @click="initialize">重试</button>
    </section>

    <section v-if="!journey" class="demo-rp-opening" aria-labelledby="demo-rp-opening-title">
      <div class="demo-rp-key">
        <label for="demo-deepseek-key">临时 DeepSeek API Key</label>
        <div>
          <input id="demo-deepseek-key" v-model="apiKey" :type="showKey ? 'text' : 'password'" autocomplete="off" spellcheck="false" placeholder="仅保留在此浏览器标签页期间" @change="saveKey">
          <button type="button" :aria-label="showKey ? '隐藏临时 Key' : '显示临时 Key'" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
          <button type="button" :disabled="!apiKey" @click="clearKey">清除</button>
        </div>
        <p>Key 只保存在本标签页的临时会话中，仅在开始流式生成时发送；登录、账户切换或会话失效都会清除。</p>
      </div>
      <h2 id="demo-rp-opening-title">从哪里开始？</h2>
      <p v-if="sourceAnchor">从{{ sourceAnchor.chapter_title || '已准备的剧情点' }}开始；你可以在开场里写下自己的身份和愿望。</p>
      <textarea v-model="opening" rows="6" :disabled="loading || busy" aria-label="演示旅程开场" placeholder="例如：我是初到此地的旅人，想在雨夜找到一条不被注意的小路……" @keydown="onComposerKeydown"></textarea>
      <label class="demo-rp-options"><input v-model="actionOptions" type="checkbox">生成后给我行动选项</label>
      <label v-if="!sessionReady" class="demo-rp-consent"><input v-model="consent" type="checkbox">我已阅读并同意 <a v-if="termsUrl" :href="termsUrl" target="_blank" rel="noopener noreferrer">用户协议</a><span v-else>用户协议</span>和<a v-if="privacyUrl" :href="privacyUrl" target="_blank" rel="noopener noreferrer">隐私政策</a><span v-else>隐私政策</span></label>
      <button class="demo-rp-primary" type="button" :disabled="loading || busy || !opening.trim() || (!sessionReady && !consent)" @click="startJourney">{{ busy ? '正在开始…' : '开始演示故事' }}</button>
    </section>

    <section v-else class="demo-rp-story" aria-label="演示故事">
      <div class="demo-rp-storybar">
        <div><strong>{{ journey.title || '这段演示旅程' }}</strong><span v-if="isGenerating" role="status">正在流式生成…</span></div>
        <div class="demo-rp-storybar-actions"><button type="button" @click="openOverview">回顾</button><details class="demo-rp-key-control"><summary>临时 Key</summary><label>临时 DeepSeek API Key<input v-model="apiKey" :type="showKey ? 'text' : 'password'" autocomplete="off" spellcheck="false" @change="saveKey"></label><div><button type="button" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button><button type="button" :disabled="!apiKey" @click="clearKey">清除临时 Key</button></div></details></div>
      </div>
      <article v-for="message in messages" :key="message.id" class="demo-rp-message" :class="`is-${message.role}`">
        <small>{{ message.role === 'assistant' ? '故事' : '你' }}</small>
        <RpMarkdownContent :source="textOf(message)" />
        <div v-if="!isGenerating" class="demo-rp-message-actions">
          <button v-if="message.role === 'assistant' && message.message_kind === 'story'" type="button" @click="regenerate(message)">重抽</button>
          <button v-if="message.role === 'assistant' && message.message_kind === 'story'" type="button" @click="loadBranches(message)">分支</button>
          <button v-if="message.role === 'user'" type="button" @click="beginCorrection(message)">纠正这句话</button>
        </div>
        <div v-if="branches[message.id]?.length" class="demo-rp-branches" aria-label="可选分支">
          <button v-for="branch in branches[message.id]" :key="branch.id || branch.node_id" type="button" @click="selectBranch(branch)">{{ branch.label || branch.excerpt || branch.content || '选择这条分支' }}</button>
        </div>
      </article>
      <article v-if="streamText" class="demo-rp-message is-assistant is-streaming">
        <small>故事正在抵达</small><RpMarkdownContent :source="streamText" />
      </article>
      <p v-if="streamError" class="demo-rp-error" role="alert">{{ streamError }}</p>
      <div v-if="actionChoices.length && !isGenerating" class="demo-rp-actions" aria-label="行动选项">
        <span>你想怎么做？</span><button v-for="choice in actionChoices" :key="typeof choice === 'string' ? choice : choice.id || choice.label" type="button" @click="chooseAction(choice)">{{ typeof choice === 'string' ? choice : choice.label || choice.content || choice.text }}</button>
      </div>
      <div class="demo-rp-composer">
        <textarea v-model="composer" rows="3" :disabled="busy || isGenerating" aria-label="继续演示故事" :placeholder="editingNodeId ? '修改后重新生成这句话' : '写下你的行动或纠正…'" @keydown="onComposerKeydown"></textarea>
        <button class="demo-rp-primary" type="button" :disabled="busy || isGenerating || !composer.trim()" @click="send">{{ editingNodeId ? '提交纠正' : '继续' }}</button>
      </div>
    </section>

    <aside v-if="overviewOpen" class="demo-rp-overview" role="dialog" aria-modal="true" aria-label="旅程回顾">
      <header><h2>旅程回顾</h2><button type="button" @click="overviewOpen = false">关闭</button></header>
      <p v-if="!overview">正在载入回顾…</p>
      <template v-else-if="overviewEditing">
        <label v-for="section in overviewSections" :key="section.key"><span>{{ section.label }}</span><small v-if="section.description">{{ section.description }}</small><textarea v-model="overviewDraft[section.key]" rows="3" :maxlength="section.maxLength"></textarea></label>
        <footer><button type="button" @click="overviewEditing = false">取消</button><button class="demo-rp-primary" type="button" :disabled="busy" @click="saveOverview">保存纠正</button></footer>
      </template>
      <template v-else>
        <section v-for="section in overviewSections" :key="section.key" v-show="overview.sections?.[section.key]"><h3>{{ section.label }}</h3><p>{{ overview.sections?.[section.key] }}</p></section>
        <footer><button type="button" @click="overviewDraft = cloneOverviewSections(overview.sections); overviewEditing = true">手动纠正</button></footer>
      </template>
    </aside>
  </main>
</template>

<style scoped>
.demo-rp-page{min-height:100dvh;max-width:920px;margin:auto;padding:clamp(20px,4vw,52px);color:var(--text-body);background:var(--bg-base)}.demo-rp-header,.demo-rp-storybar,.demo-rp-key>div,.demo-rp-composer,.demo-rp-overview header{display:flex;gap:12px;align-items:center;justify-content:space-between}.demo-rp-header{align-items:flex-start;margin-bottom:28px}.demo-rp-eyebrow{font-size:12px;letter-spacing:.12em;color:var(--text-secondary)}.demo-rp-header h1,.demo-rp-header p{margin:4px 0}.demo-rp-back{color:var(--nc-primary);white-space:nowrap}.demo-rp-opening,.demo-rp-story,.demo-rp-overview{display:grid;gap:16px;padding:clamp(18px,3vw,30px);border:1px solid var(--border);border-radius:18px;background:var(--bg-panel)}.demo-rp-key{display:grid;gap:8px;padding-bottom:16px;border-bottom:1px solid var(--border)}.demo-rp-key input{flex:1;min-width:0}.demo-rp-key p{margin:0;color:var(--text-secondary);font-size:13px;line-height:1.5}.demo-rp-options,.demo-rp-consent{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.demo-rp-consent a{color:var(--nc-primary)}.demo-rp-page textarea,.demo-rp-page input{box-sizing:border-box;width:100%;padding:11px;border:1px solid var(--nc-hairline-strong);border-radius:9px;background:var(--bg-base);color:inherit;font:inherit;line-height:1.55}.demo-rp-page button{min-height:38px;padding:8px 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-muted);color:inherit;font:inherit;cursor:pointer}.demo-rp-page button:disabled{opacity:.55;cursor:not-allowed}.demo-rp-primary{background:var(--nc-primary)!important;color:var(--nc-on-primary)!important;border-color:var(--nc-primary)!important}.demo-rp-error{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px;border-radius:10px;background:var(--nc-error-soft);color:var(--error)}.demo-rp-story{gap:22px}.demo-rp-storybar{position:sticky;top:0;padding-bottom:12px;border-bottom:1px solid var(--border);background:var(--bg-panel);z-index:1}.demo-rp-storybar div{display:grid;gap:3px}.demo-rp-storybar span{font-size:13px;color:var(--text-secondary)}.demo-rp-message{display:grid;gap:7px;max-width:78%;padding:15px;border-radius:14px;background:var(--bg-muted)}.demo-rp-message.is-user{margin-left:auto;background:var(--nc-primary-soft)}.demo-rp-message small{color:var(--text-secondary)}.demo-rp-message-actions,.demo-rp-branches,.demo-rp-actions{display:flex;gap:8px;flex-wrap:wrap}.demo-rp-message-actions button,.demo-rp-branches button,.demo-rp-actions button{min-height:32px;font-size:13px}.demo-rp-branches{padding-top:6px}.demo-rp-composer{align-items:flex-end;border-top:1px solid var(--border);padding-top:16px}.demo-rp-composer textarea{flex:1}.demo-rp-overview{position:fixed;z-index:50;inset:5vh max(16px,calc((100vw - 820px)/2));overflow:auto;box-shadow:0 18px 55px rgb(0 0 0 / .25)}.demo-rp-overview h2,.demo-rp-overview h3,.demo-rp-overview p{margin:0}.demo-rp-overview section,.demo-rp-overview label{display:grid;gap:7px}.demo-rp-overview h3{font-size:14px;color:var(--text-secondary)}.demo-rp-overview footer{display:flex;gap:8px;justify-content:flex-end}@media(max-width:620px){.demo-rp-header,.demo-rp-key>div,.demo-rp-composer{align-items:stretch;flex-direction:column}.demo-rp-message{max-width:100%}.demo-rp-overview{inset:12px}.demo-rp-header{gap:16px}.demo-rp-back{align-self:flex-start}}
</style>
