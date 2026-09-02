<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
  getApi,
  getAppState,
  getConfirm,
  getPrompt,
  getRouter,
  getToast,
} from "../../bridge/index.js"
import {
  clearJourneyScroll,
  interactionOperationKey,
  readOpeningDraft,
  writeOpeningDraft,
} from "./interactionSession.js"
import RpAdaptiveConfirmPopover from "./RpAdaptiveConfirmPopover.vue"
import RpSourceSetup from "./RpSourceSetup.vue"
import { safeInteractionError } from "./interactionErrors.js"

const props = defineProps({
  activeJourneys: { type: Array, default: () => [] },
  activeTotal: { type: Number, default: 0 },
  archivedJourneys: { type: Array, default: () => [] },
  archivedTotal: { type: Number, default: 0 },
  llmConnections: { type: Object, default: null },
  preferences: { type: Object, default: null },
  startNew: { type: Boolean, default: false },
  loadError: { type: String, default: null },
})

const active = ref([...props.activeJourneys])
const archived = ref([...props.archivedJourneys])
const activeTotal = ref(props.activeTotal)
const archivedTotal = ref(props.archivedTotal)
const loadError = ref(props.loadError)
const tab = ref("active")
const search = ref("")
const appliedSearch = ref("")
const searchOpen = ref(false)
const opening = ref(readOpeningDraft())
const composing = ref(false)
const seeSea = ref(false)
const actionOptions = ref(true)
const creating = ref(false)
const createError = ref("")
const createErrorAction = ref("")
const sourceSelection = ref({ enabled: false, setup: null })
const searching = ref(false)
const loadingMore = ref(false)
const seeSeaNoticeOpen = ref(false)
const seeSeaButton = ref(null)
const seeSeaConfirming = ref(false)
const seeSeaNoticeAcknowledged = ref(
  props.preferences?.see_sea_notice_acknowledged === true,
)

watch(opening, writeOpeningDraft)

const activeProvider = computed(() => (
  props.llmConnections?.providers?.find((provider) => provider.active) || null
))
const connectionStateKnown = computed(() => props.llmConnections !== null)
const hasActiveConnection = computed(() => (
  !connectionStateKnown.value || Boolean(activeProvider.value?.connected)
))
const hasAnyJourney = computed(() => active.value.length + archived.value.length > 0)
const showOpening = computed(() => (
  !loadError.value
  && (
    props.startNew
    || (!appliedSearch.value && !hasAnyJourney.value)
  )
))
const openingTooLong = computed(() => opening.value.length > 100_000)
const showOpeningCount = computed(() => opening.value.length >= 90_000)

const visibleJourneys = computed(() => {
  return tab.value === "active" ? active.value : archived.value
})
const currentTotal = computed(() => (
  tab.value === "active" ? activeTotal.value : archivedTotal.value
))
let reloadVersion = 0
let loadMoreVersion = 0
let disposed = false

function routeOwner() {
  const state = getAppState()
  return {
    view: state?.currentView || null,
    subView: state?.currentSubView || null,
  }
}

function ownsRoute(owner) {
  const state = getAppState()
  return !disposed
    && owner?.view === "journeys"
    && state?.currentView === owner.view
    && (state?.currentSubView || null) === owner.subView
}

async function reload(query = appliedSearch.value) {
  const owner = routeOwner()
  const normalizedQuery = String(query || "").trim()
  const requestVersion = ++reloadVersion
  loadMoreVersion += 1
  loadingMore.value = false
  searching.value = true
  try {
    const [activeData, archivedData] = await Promise.all([
      getApi().interactions.listJourneys({
        status: "active",
        search: normalizedQuery || undefined,
        limit: 50,
      }),
      getApi().interactions.listJourneys({
        status: "archived",
        search: normalizedQuery || undefined,
        limit: 50,
      }),
    ])
    if (requestVersion !== reloadVersion || !ownsRoute(owner)) return false
    active.value = activeData.items || []
    activeTotal.value = Number(activeData.total || 0)
    archived.value = archivedData.items || []
    archivedTotal.value = Number(archivedData.total || 0)
    appliedSearch.value = normalizedQuery
    loadError.value = null
    return true
  } catch {
    if (requestVersion !== reloadVersion || !ownsRoute(owner)) return false
    loadError.value = "旅程列表暂时无法加载，请稍后重试。"
    getToast()("旅程列表暂时无法加载，请稍后重试。", "error")
    return false
  } finally {
    if (requestVersion === reloadVersion && ownsRoute(owner)) searching.value = false
  }
}

async function searchJourneys() {
  await reload(search.value)
}

async function loadMore() {
  if (searching.value || loadingMore.value) return
  const status = tab.value
  const target = status === "active" ? active : archived
  const total = status === "active" ? activeTotal : archivedTotal
  if (target.value.length >= total.value) return
  const requestVersion = ++loadMoreVersion
  const currentReloadVersion = reloadVersion
  const offset = target.value.length
  const query = appliedSearch.value
  loadingMore.value = true
  try {
    const data = await getApi().interactions.listJourneys({
      status,
      search: query || undefined,
      offset,
      limit: 50,
    })
    if (
      requestVersion !== loadMoreVersion
      || currentReloadVersion !== reloadVersion
    ) return
    const byId = new Map(
      [...target.value, ...(data.items || [])]
        .map((journey) => [journey.id, journey]),
    )
    target.value = [...byId.values()]
    total.value = Number(data.total || target.value.length)
  } catch {
    if (
      requestVersion !== loadMoreVersion
      || currentReloadVersion !== reloadVersion
    ) return
    getToast()("更多旅程暂时无法加载，请稍后重试。", "error")
  } finally {
    if (requestVersion === loadMoreVersion) loadingMore.value = false
  }
}

async function createJourney() {
  if (!hasActiveConnection.value) {
    goConnect("journeys:new")
    return
  }
  if (
    !opening.value.trim()
    || openingTooLong.value
    || creating.value
    || (sourceSelection.value.enabled && !sourceSelection.value.setup)
  ) return
  creating.value = true
  createError.value = ""
  createErrorAction.value = ""
  const owner = routeOwner()
  const submittedOpening = opening.value
  try {
    const result = await getApi().interactions.createJourney({
      opening_text: submittedOpening.trim(),
      idempotency_key: interactionOperationKey("journey"),
      see_sea_enabled: seeSea.value,
      action_options_enabled: actionOptions.value,
      source_setup: sourceSelection.value.enabled
        ? sourceSelection.value.setup
        : null,
    })
    if (!ownsRoute(owner)) {
      if (readOpeningDraft() === submittedOpening) writeOpeningDraft("")
      return
    }
    writeOpeningDraft("")
    opening.value = ""
    await getRouter().navigate("interaction", result.journey.id)
  } catch (error) {
    if (!ownsRoute(owner)) return
    const safeError = safeInteractionError(error, { opening: true })
    createError.value = safeError.message
    createErrorAction.value = safeError.action
  } finally {
    if (ownsRoute(owner)) creating.value = false
  }
}

function formatActivity(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return ""
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function requestSeeSea() {
  if (seeSea.value) {
    seeSea.value = false
    return
  }
  if (seeSeaNoticeAcknowledged.value) {
    seeSea.value = true
    return
  }
  seeSeaNoticeOpen.value = true
}

async function confirmSeeSea() {
  if (seeSeaConfirming.value) return
  seeSeaConfirming.value = true
  try {
    await getApi().interactions.acknowledgeSeeSeaNotice()
    seeSeaNoticeAcknowledged.value = true
    seeSeaNoticeOpen.value = false
    seeSea.value = true
  } catch {
    getToast()("暂时无法保存提示状态，请重试。", "error")
  } finally {
    seeSeaConfirming.value = false
  }
}

function onOpeningKeydown(event) {
  if (event.isComposing || composing.value) return
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault()
    createJourney()
  }
}

function openJourney(id) {
  clearJourneyScroll(id)
  getRouter().navigate("interaction", id)
}

function goConnect(returnTarget = "journeys") {
  const query = new URLSearchParams({ return_to: returnTarget })
  getRouter().navigate("settings", null, true, query)
}

function openNewJourney() {
  if (!hasActiveConnection.value) {
    goConnect("journeys:new")
    return
  }
  getRouter().navigate("journeys", "new")
}

async function archiveJourney(journey) {
  const suffix = ["pending", "preparing_context", "running", "awaiting_continue"].includes(
    journey.attempt_status,
  )
    ? " 当前生成会停止，已经显示的正文会作为未完整片段保留。"
    : ""
  if (!getConfirm()(`归档「${journey.title}」？${suffix}`)) return
  const owner = routeOwner()
  try {
    await getApi().interactions.archiveJourney(journey.id)
    if (!ownsRoute(owner)) return
    await reload()
    if (!ownsRoute(owner)) return
    getToast()("旅程已归档", "success")
  } catch {
    if (ownsRoute(owner)) {
      getToast()("归档失败；旅程和正在生成的内容仍保留，请重试。", "error")
    }
  }
}

async function restoreJourney(journey) {
  const owner = routeOwner()
  try {
    await getApi().interactions.restoreJourney(journey.id)
    if (!ownsRoute(owner)) return
    await reload()
    if (!ownsRoute(owner)) return
    getToast()("旅程已恢复", "success")
  } catch {
    if (ownsRoute(owner)) {
      getToast()("恢复失败；归档中的旅程仍然保留，请重试。", "error")
    }
  }
}

async function deleteJourney(journey) {
  const answer = getPrompt()(
    `永久删除后无法恢复。请输入完整旅程标题：${journey.title}`,
    "",
  )
  if (answer === null) return
  const owner = routeOwner()
  try {
    await getApi().interactions.deleteJourney(journey.id, answer)
    if (!ownsRoute(owner)) return
    await reload()
    if (!ownsRoute(owner)) return
    getToast()("旅程已永久删除", "success")
  } catch {
    if (ownsRoute(owner)) {
      getToast()("永久删除失败；旅程仍在归档中，请确认标题后重试。", "error")
    }
  }
}

onMounted(() => {
  if (!loadError.value && !hasAnyJourney.value && !hasActiveConnection.value) {
    goConnect("journeys:new")
  }
})

onBeforeUnmount(() => {
  disposed = true
  reloadVersion += 1
  loadMoreVersion += 1
})
</script>

<template>
  <main class="rp-list-page">
    <header class="rp-list-header">
      <button
        class="rp-icon-button"
        type="button"
        :aria-label="showOpening && hasAnyJourney ? '返回旅程列表' : '返回使用方式'"
        @click="showOpening && hasAnyJourney ? getRouter().navigate('journeys') : getRouter().navigate('home')"
      >‹</button>
      <div>
        <h1>{{ showOpening ? "开始新旅程" : "互动故事" }}</h1>
        <p>{{ showOpening ? "进入你想体验的世界" : "继续你的角色扮演旅程" }}</p>
      </div>
      <button class="rp-text-button" type="button" @click="goConnect('journeys')">账户设置</button>
    </header>

    <section v-if="loadError" class="rp-list-load-error" role="alert">
      <strong>旅程历史暂时无法加载</strong>
      <span>{{ loadError }}</span>
      <button type="button" @click="reload()">重试</button>
    </section>

    <section
      v-else-if="showOpening"
      class="rp-opening-card rp-opening-page"
      aria-labelledby="rp-opening-title"
      :aria-busy="creating"
    >
      <div class="rp-opening-intro">
        <h2 id="rp-opening-title">你想从哪里开始？</h2>
        <p>{{ sourceSelection.enabled
          ? "先确认作品版本、剧情进度和玩家身份，再写下本次开场。"
          : "不需要先整理资料。写下世界、你的身份和故事起点即可。" }}</p>
      </div>
      <div v-if="connectionStateKnown && !hasActiveConnection" class="rp-connection-callout">
        <strong>开始故事前需要先连接模型</strong>
        <span>已有内容不受影响，连接只用于之后的新生成。</span>
        <button type="button" @click="goConnect('journeys:new')">去连接模型</button>
      </div>
      <RpSourceSetup
        :disabled="creating"
        @change="sourceSelection = $event"
      />
      <div class="rp-opening-composer">
        <textarea
          v-model="opening"
          rows="5"
          :disabled="creating"
          placeholder="例如：我想进入哪个世界；我是谁；从什么时间、什么地点开始；我正和谁在一起、想做什么……"
          aria-label="旅程开场"
          @keydown="onOpeningKeydown"
          @compositionstart="composing = true"
          @compositionend="composing = false"
        ></textarea>
        <button
          class="rp-send-button"
          type="button"
          :disabled="
            creating
            || !opening.trim()
            || openingTooLong
            || !hasActiveConnection
            || (sourceSelection.enabled && !sourceSelection.setup)
          "
          aria-label="开始旅程"
          @click="createJourney"
        >{{ creating ? "…" : "↑" }}</button>
      </div>
      <p v-if="showOpeningCount" class="rp-input-count" :class="{ error: openingTooLong }">
        {{ opening.length.toLocaleString() }} / 100,000
        <span v-if="openingTooLong">· 这次输入过长，请分几次发送</span>
      </p>
      <div class="rp-mode-row">
        <button
          ref="seeSeaButton"
          type="button"
          class="rp-mode-toggle"
          :class="{ active: seeSea }"
          :aria-pressed="seeSea"
          aria-haspopup="dialog"
          :aria-expanded="seeSeaNoticeOpen"
          aria-controls="rp-new-journey-see-sea-confirm"
          @click="requestSeeSea"
        >故事自主发展</button>
        <button
          type="button"
          class="rp-mode-toggle"
          :class="{ active: actionOptions }"
          :aria-pressed="actionOptions"
          @click="actionOptions = !actionOptions"
        >行动选项</button>
        <span>{{ seeSea ? "故事会持续自主发展，直到你关闭" : "关键行动由你决定" }}</span>
      </div>
      <RpAdaptiveConfirmPopover
        id="rp-new-journey-see-sea-confirm"
        :anchor="seeSeaButton"
        :busy="seeSeaConfirming"
        confirm-text="开始自主发展"
        message="故事会持续自主发展并使用你的模型额度；离开页面或关闭开关后会停止。"
        :open="seeSeaNoticeOpen"
        @close="seeSeaNoticeOpen = false"
        @confirm="confirmSeeSea"
      />
      <p v-if="createError" class="rp-inline-error" role="alert">
        {{ createError }}
        <button
          v-if="createErrorAction === 'connection'"
          type="button"
          @click="goConnect('journeys:new')"
        >检查模型连接</button>
      </p>
      <p class="rp-shortcut-hint">⌘/Ctrl + Enter 开始，Enter 换行</p>
      <p class="rp-data-notice">
        你的输入、当前旅程上下文和本轮需要的作品资料会发送给所选模型服务。旅程是私人分支，不会写回原作正文或世界资料。请仅使用你有权处理的内容。
      </p>
    </section>

    <section v-else class="rp-journey-catalog" :aria-busy="searching || loadingMore">
      <div v-if="connectionStateKnown && !hasActiveConnection" class="rp-list-connection-note">
        <span>连接模型后可以继续故事；现有旅程仍可阅读和管理。</span>
        <button type="button" @click="goConnect('journeys')">去连接模型</button>
      </div>
      <div class="rp-catalog-toolbar">
        <div class="rp-tabs" role="tablist" aria-label="旅程状态">
          <button type="button" role="tab" :aria-selected="tab === 'active'" :class="{ active: tab === 'active' }" @click="tab = 'active'">进行中</button>
          <button type="button" role="tab" :aria-selected="tab === 'archived'" :class="{ active: tab === 'archived' }" @click="tab = 'archived'">已归档</button>
        </div>
        <div class="rp-catalog-actions">
          <button class="rp-new-journey-button" type="button" @click="openNewJourney">开始新旅程</button>
          <button
            class="rp-search-toggle"
            type="button"
            :aria-expanded="searchOpen"
            @click="searchOpen = !searchOpen"
          >{{ searchOpen ? "收起搜索" : "搜索" }}</button>
          <input
            v-if="searchOpen"
            v-model="search"
            class="rp-catalog-search"
            type="search"
            placeholder="搜索旅程"
            aria-label="搜索旅程"
            @keydown.enter.prevent="searchJourneys"
          />
          <button
            v-if="searchOpen"
            type="button"
            :disabled="searching"
            @click="searchJourneys"
          >{{ searching ? "查找中…" : "查找" }}</button>
        </div>
      </div>

      <div v-if="visibleJourneys.length === 0" class="rp-empty-list" role="status">
        <p>{{ appliedSearch ? "没有找到匹配旅程" : (tab === "active" ? "没有进行中的旅程。" : "没有已归档的旅程。") }}</p>
      </div>
      <article
        v-for="journey in visibleJourneys"
        :key="journey.id"
        class="rp-journey-card"
        :class="{ 'is-generating': ['pending', 'preparing_context', 'running'].includes(journey.attempt_status) }"
      >
        <button v-if="journey.status === 'active'" class="rp-journey-card__main" type="button" @click="openJourney(journey.id)">
          <span v-if="['pending', 'preparing_context', 'running'].includes(journey.attempt_status)" class="rp-generating-dot" aria-label="正在生成"></span>
          <strong>{{ journey.title }}</strong>
          <small v-if="journey.source" class="rp-journey-source-label">
            {{ journey.source.source_title }} · 资料版本 {{ journey.source.version_number }} · {{ journey.source.progress_label }}
          </small>
          <span>{{ journey.current_excerpt || journey.opening_excerpt }}</span>
          <small class="rp-journey-card__meta">
            <span>{{
              journey.attempt_status === "preparing_context"
                ? "正在整理最近剧情"
                : (
                  journey.attempt_status === "awaiting_continue"
                    ? "等待继续写完"
                    : (
                      ["pending", "running"].includes(journey.attempt_status)
                        ? "正在生成故事"
                        : (journey.attempt_status === "failed" ? "上次生成未完成" : "继续旅程")
                    )
                )
            }}</span>
            <time :datetime="journey.latest_activity_at">
              {{ formatActivity(journey.latest_activity_at) }}
            </time>
          </small>
        </button>
        <div v-else class="rp-journey-card__main">
          <strong>{{ journey.title }}</strong>
          <small v-if="journey.source" class="rp-journey-source-label">
            {{ journey.source.source_title }} · 资料版本 {{ journey.source.version_number }} · {{ journey.source.progress_label }}
          </small>
          <span>{{ journey.current_excerpt || journey.opening_excerpt }}</span>
          <small class="rp-journey-card__meta">
            <span>已归档</span>
            <time :datetime="journey.latest_activity_at">
              {{ formatActivity(journey.latest_activity_at) }}
            </time>
          </small>
        </div>
        <div class="rp-journey-card__actions">
          <button v-if="journey.status === 'active'" type="button" :aria-label="`归档旅程：${journey.title}`" @click="archiveJourney(journey)">归档</button>
          <template v-else>
            <button type="button" :aria-label="`恢复旅程：${journey.title}`" @click="restoreJourney(journey)">恢复</button>
            <button class="danger" type="button" :aria-label="`永久删除旅程：${journey.title}`" @click="deleteJourney(journey)">永久删除</button>
          </template>
        </div>
      </article>
      <button
        v-if="visibleJourneys.length < currentTotal"
        class="rp-load-more"
        type="button"
        :disabled="searching || loadingMore"
        :aria-busy="loadingMore"
        @click="loadMore"
      >{{ searching ? "正在查找…" : (loadingMore ? "加载中…" : "加载更多") }}</button>
    </section>
  </main>
</template>
