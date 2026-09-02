<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue"
import {
  getApi,
  getConfirm,
  getPrompt,
  getRouter,
  getToast,
} from "../../bridge/index.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import {
  cancelSeeSeaGrace,
  interactionOperationKey,
  readJourneyDraft,
  readJourneyScroll,
  readOverviewDraft,
  scheduleSeeSeaGrace,
  writeJourneyDraft,
  writeJourneyScroll,
  writeOverviewDraft,
} from "./interactionSession.js"
import {
  normalizeTheme,
  SHELL_THEMES,
} from "../../shell/composables/useTheme.js"
import RpAdaptiveConfirmPopover from "./RpAdaptiveConfirmPopover.vue"
import { safeInteractionError } from "./interactionErrors.js"
import { sourceEntityTypeLabel } from "./sourceLabels.js"
import RpMarkdownContent from "./RpMarkdownContent.vue"

const props = defineProps({
  initialJourney: { type: Object, default: null },
  llmConnections: { type: Object, default: null },
  preferences: { type: Object, default: null },
  initialPathIndex: { type: Object, default: null },
  loadError: { type: String, default: null },
})

const journey = ref(props.initialJourney)
const setupMessages = ref([...(props.initialJourney?.setup_messages || [])])
const messages = ref([...(props.initialJourney?.messages || [])])
const currentAttempt = ref(props.initialJourney?.active_attempt || null)
const streamText = ref(props.initialJourney?.active_attempt?.visible_text || "")
const streamOffset = ref(0)
const streamError = ref("")
const composer = ref(readJourneyDraft(props.initialJourney?.id))
const branchDraftNotice = ref(false)
const composing = ref(false)
const editingNodeId = ref(null)
const sending = ref(false)
const stopping = ref(false)
const conflict = ref(null)
const connectionProblem = ref(false)
const overviewOpen = ref(false)
const overview = ref(null)
const overviewSections = [
  { key: "world_and_start", label: "世界与起点" },
  { key: "player_character", label: "我的角色" },
  { key: "current_situation", label: "当前局面" },
  { key: "important_people_and_factions", label: "重要人物与势力" },
  { key: "key_turning_points", label: "关键转折" },
  { key: "open_threads", label: "正在发展的事情" },
  { key: "must_remember", label: "必须继续记住" },
]
const emptyOverviewSections = () => Object.fromEntries(
  overviewSections.map(({ key }) => [key, ""]),
)
const cloneOverviewSections = (sections) => Object.fromEntries(
  overviewSections.map(({ key }) => [key, String(sections?.[key] || "")]),
)
const overviewDraft = ref(emptyOverviewSections())
const overviewBaseline = ref("")
const overviewEditing = ref(false)
const overviewConflict = ref(null)
const overviewEditContext = ref(null)
const overviewDraftNotice = ref(false)
const overviewRetrying = ref(false)
const overviewSaving = ref(false)
const overviewLoading = ref(false)
const overviewLoadError = ref("")
const overviewDrawer = ref(null)
const overviewReturnFocus = ref(null)
const rememberButton = ref(null)
const generationRecordsOpen = ref(false)
const generationRecords = ref([])
const generationRecordsLoading = ref(false)
const treeOpen = ref(false)
const treeBranchPoints = ref([])
const treeOlderExpanded = ref(false)
const treeLoading = ref(false)
const treeLoadError = ref("")
const branchesByNode = ref({})
const branchOpenNode = ref(null)
const storyPane = ref(null)
const composerInput = ref(null)
const selectedStoryText = ref("")
const newContent = ref(false)
const newContentCount = ref(0)
const stopAfterCurrentNotice = ref(false)
const seeSeaNoticeOpen = ref(false)
const seeSeaButton = ref(null)
const seeSeaConfirming = ref(false)
const seeSeaNoticeAcknowledged = ref(
  props.preferences?.see_sea_notice_acknowledged === true,
)
const dataInfoOpen = ref(false)
const sourceInfoOpen = ref(false)
const sourceInfo = ref(null)
const sourceRevision = ref(null)
const sourceUpgrade = ref(null)
const sourceObjects = ref([])
const sourceCurrentAnchorKey = ref("")
const sourceUpgradeAnchorKey = ref("")
const sourceLoading = ref(false)
const sourceError = ref("")
const sourceDrawer = ref(null)
const hasNewerMessages = ref(false)
const moreMenu = ref(null)
const currentTheme = ref(normalizeTheme(
  globalThis.document?.documentElement?.getAttribute?.("data-theme")
  || globalThis.localStorage?.getItem?.("nc-theme"),
))
const pathIndex = ref(props.initialPathIndex?.items || [])
const pathIndexEpoch = ref(
  props.initialPathIndex?.selection_epoch ?? props.initialJourney?.selection_epoch ?? 0,
)
const locatorPosition = ref(Math.max(1, pathIndex.value.length))
const locatorBusy = ref(false)
const loadingOlder = ref(false)
const locatorPreviewItem = ref(null)
const locatorExpanded = ref(false)
let scrollFrame = null
let streamController = null
let heartbeatTimer = null
let disposed = false
let locatorGesture = null
let branchCacheGeneration = 0
let journeyRefreshVersion = 0
let overviewGeneration = 0
const branchLoads = new Map()
const unseenStoryNodeIds = new Set()
const knownStoryNodeIds = new Set([
  ...(props.initialPathIndex?.items || []).map((item) => item.id),
  ...(props.initialJourney?.messages || [])
    .filter((message) => (
      message.role === "assistant" && message.message_kind === "story"
    ))
    .map((message) => message.id),
])

const journeyId = computed(() => journey.value?.id || "")
const activeProvider = computed(() => (
  props.llmConnections?.providers?.find((provider) => provider.active) || null
))
const connectionStateKnown = computed(() => props.llmConnections !== null)
const hasActiveConnection = computed(() => (
  (
    !connectionStateKnown.value
    || Boolean(activeProvider.value?.connected)
  )
  && !connectionProblem.value
))
const isGenerating = computed(() => (
  ["pending", "preparing_context", "running"].includes(
    currentAttempt.value?.status,
  )
))
const awaitingContinue = computed(() => (
  currentAttempt.value?.status === "awaiting_continue"
))
const failedAttempt = computed(() => (
  ["failed", "cancelled"].includes(currentAttempt.value?.status)
))
const currentTerminalStoryMessage = computed(() => {
  if (hasNewerMessages.value) return null
  const last = messages.value.at(-1)
  if (
    !last
    || last.id !== journey.value?.selected_leaf_node_id
    || last.role !== "assistant"
    || last.message_kind !== "story"
  ) return null
  return last
})
const storyEnded = computed(() => (
  currentTerminalStoryMessage.value?.story_ended === true
))
const storyStarted = computed(() => (
  messages.value.some((message) => message.message_kind === "story")
))
const lastStoryMessageId = computed(() => (
  currentTerminalStoryMessage.value?.id || null
))
const awaitingSetupAnswer = computed(() => (
  messages.value.length === 0
  && setupMessages.value.at(-1)?.role === "assistant"
))
const overviewHasContent = computed(() => (
  overviewSections.some(({ key }) => overview.value?.sections?.[key]?.trim())
))
const overviewDraftHasContent = computed(() => (
  overviewSections.some(({ key }) => overviewDraft.value[key]?.trim())
))
const overviewDirty = computed(() => (
  overviewEditing.value
  && JSON.stringify(cloneOverviewSections(overviewDraft.value))
    !== overviewBaseline.value
))
const composerTooLong = computed(() => composer.value.length > 100_000)
const showComposerCount = computed(() => composer.value.length >= 90_000)
const locatorItem = computed(() => (
  pathIndex.value[Math.max(0, locatorPosition.value - 1)] || null
))
const locatorDisplayItem = computed(() => (
  locatorPreviewItem.value || locatorItem.value
))
const visibleTreeBranchPoints = computed(() => (
  treeOlderExpanded.value
    ? treeBranchPoints.value
    : treeBranchPoints.value.slice(0, 1)
))
const failedError = computed(() => safeInteractionError(
  currentAttempt.value?.error_kind || "generation_failed",
))
// attempt.error_message 由后端 _safe_story_error/blocker 写入,是面向用户的
// 固定文案(如具体的资料阻断原因);优先于按 kind 推导的通用文案展示。
const failedMessage = computed(() => {
  const serverMessage = String(currentAttempt.value?.error_message || "").trim()
  return serverMessage || failedError.value.message
})
const streamErrorRole = computed(() => (
  streamError.value.includes("正在从已保存位置恢复") ? "status" : "alert"
))

function goConnect() {
  const query = new URLSearchParams({
    return_to: `interaction:${journeyId.value}`,
  })
  getRouter().navigate("settings", null, true, query)
}

function requireModelConnection() {
  if (hasActiveConnection.value) return true
  goConnect()
  return false
}

function resizeComposer() {
  const input = composerInput.value
  if (!input) return
  input.style.height = "auto"
  const styles = globalThis.getComputedStyle?.(input)
  const lineHeight = Number.parseFloat(styles?.lineHeight || "24") || 24
  const verticalPadding = (
    Number.parseFloat(styles?.paddingTop || "0")
    + Number.parseFloat(styles?.paddingBottom || "0")
  )
  const minHeight = lineHeight * 2 + verticalPadding
  const maxHeight = lineHeight * 8 + verticalPadding
  input.style.height = `${Math.min(maxHeight, Math.max(minHeight, input.scrollHeight))}px`
  input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden"
}

watch(composer, (value) => {
  if (branchDraftNotice.value) branchDraftNotice.value = false
  writeJourneyDraft(journeyId.value, value)
  void nextTick(resizeComposer)
})

watch(overviewDraft, (sections) => {
  if (!overviewEditing.value) return
  writeOverviewDraft(
    journeyId.value,
    overviewEditContext.value?.nodeId || journey.value?.selected_leaf_node_id,
    {
      overviewEpoch: overviewEditContext.value?.overviewEpoch,
      selectionEpoch: overviewEditContext.value?.selectionEpoch,
      baseRevisionId: overviewEditContext.value?.baseRevisionId,
      baseSelectedLeafNodeId:
        overviewEditContext.value?.baseSelectedLeafNodeId,
      baseSelectedPathHash: overviewEditContext.value?.baseSelectedPathHash,
      sections: cloneOverviewSections(sections),
    },
  )
}, { deep: true })

function isNearBottom() {
  if (hasNewerMessages.value) return false
  const el = storyPane.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

async function scrollToBottom() {
  if (hasNewerMessages.value) {
    const requestVersion = ++journeyRefreshVersion
    const requestJourneyId = journeyId.value
    const requestEpoch = journey.value?.selection_epoch
    const next = await getApi().interactions.getJourney(journeyId.value)
    if (
      requestVersion !== journeyRefreshVersion
      || requestJourneyId !== journeyId.value
      || requestEpoch !== journey.value?.selection_epoch
      || Number(next.selection_epoch) < Number(requestEpoch)
    ) return
    applyJourney(next)
    void refreshPathIndex(next.selection_epoch)
  }
  await nextTick()
  const el = storyPane.value
  if (el) el.scrollTop = el.scrollHeight
  newContent.value = false
  newContentCount.value = 0
  unseenStoryNodeIds.clear()
  updateLocatorFromScroll()
}

function applyJourney(nextJourney, { preserveMessages = false } = {}) {
  if (!nextJourney) return
  journeyRefreshVersion += 1
  journey.value = nextJourney
  if (!preserveMessages) {
    selectedStoryText.value = ""
    setupMessages.value = [...(nextJourney.setup_messages || [])]
    messages.value = [...(nextJourney.messages || [])]
    for (const message of messages.value) {
      if (message.role === "assistant" && message.message_kind === "story") {
        knownStoryNodeIds.add(message.id)
      }
    }
    branchCacheGeneration += 1
    branchesByNode.value = {}
    branchOpenNode.value = null
    hasNewerMessages.value = false
    newContent.value = false
    newContentCount.value = 0
    unseenStoryNodeIds.clear()
  }
  currentAttempt.value = nextJourney.active_attempt || null
  if (!preserveMessages) void refreshLatestBranches()
}

function mergeJourneyMetadata(nextJourney, fields) {
  if (!nextJourney || !journey.value) return
  const updates = {}
  for (const field of fields) {
    if (Object.hasOwn(nextJourney, field)) updates[field] = nextJourney[field]
  }
  journeyRefreshVersion += 1
  journey.value = { ...journey.value, ...updates }
}

function applyModeJourney(nextJourney, expectedEpoch) {
  if (
    journey.value?.selection_epoch === expectedEpoch
    && nextJourney?.selection_epoch === expectedEpoch
  ) {
    applyJourney(nextJourney, { preserveMessages: true })
    return true
  }
  mergeJourneyMetadata(nextJourney, [
    "see_sea_enabled",
    "action_options_enabled",
  ])
  return false
}

async function refreshPathIndex(expectedEpoch = journey.value?.selection_epoch) {
  try {
    const result = await getApi().interactions.getPathIndex(journeyId.value)
    if (
      result.selection_epoch !== expectedEpoch
      || result.selection_epoch !== journey.value?.selection_epoch
    ) return false
    pathIndex.value = result.items || []
    pathIndexEpoch.value = result.selection_epoch
    if (!hasNewerMessages.value) {
      for (const item of pathIndex.value) knownStoryNodeIds.add(item.id)
    }
    locatorPosition.value = Math.min(
      Math.max(1, locatorPosition.value),
      Math.max(1, pathIndex.value.length),
    )
    return true
  } catch {
    return false
  }
}

function stopHeartbeat() {
  if (heartbeatTimer != null) clearInterval(heartbeatTimer)
  heartbeatTimer = null
}

async function sendHeartbeat() {
  if (
    disposed
    || document.visibilityState === "hidden"
    || !journey.value?.see_sea_enabled
  ) return
  try {
    const result = await getApi().interactions.heartbeat(journeyId.value)
    if (!result.accepted) {
      journey.value.see_sea_enabled = false
      stopHeartbeat()
      return
    }
    const attempt = result.attempt
    if (
      attempt
      && ["pending", "preparing_context", "running"].includes(attempt.status)
      && attempt.id !== currentAttempt.value?.id
    ) {
      void followAttempt(attempt)
    }
  } catch {
    // The server-side heartbeat expiry is the authoritative spend boundary.
  }
}

function syncHeartbeat() {
  stopHeartbeat()
  if (
    disposed
    || document.visibilityState === "hidden"
    || !journey.value?.see_sea_enabled
  ) return
  // Keep a short story-beat boundary so a prepared manual action can win
  // before the foreground loop asks the server for its next automatic step.
  heartbeatTimer = setTimeout(() => {
    heartbeatTimer = setInterval(() => {
      void sendHeartbeat()
    }, 20_000)
    void sendHeartbeat()
  }, 1_000)
}

async function refreshJourney() {
  const requestVersion = ++journeyRefreshVersion
  const requestJourneyId = journeyId.value
  const previousEpoch = journey.value?.selection_epoch
  const wasSea = Boolean(journey.value?.see_sea_enabled)
  const next = await getApi().interactions.getJourney(journeyId.value)
  if (
    requestVersion !== journeyRefreshVersion
    || requestJourneyId !== journeyId.value
    || previousEpoch !== journey.value?.selection_epoch
    || Number(next.selection_epoch) < Number(previousEpoch)
  ) return journey.value
  const follow = isNearBottom()
  const preserveMessages = !follow && next.selection_epoch === previousEpoch
  if (preserveMessages) {
    for (const message of next.messages || []) {
      if (
        message.role === "assistant"
        && message.message_kind === "story"
        && !knownStoryNodeIds.has(message.id)
        && !unseenStoryNodeIds.has(message.id)
      ) {
        unseenStoryNodeIds.add(message.id)
        newContentCount.value += 1
      }
      if (message.role === "assistant" && message.message_kind === "story") {
        knownStoryNodeIds.add(message.id)
      }
    }
  }
  applyJourney(next, { preserveMessages })
  hasNewerMessages.value = preserveMessages
  if (!next.see_sea_enabled && ![
    "pending",
    "preparing_context",
    "running",
  ].includes(next.active_attempt?.status)) {
    stopAfterCurrentNotice.value = false
  }
  syncHeartbeat()
  void refreshPathIndex(next.selection_epoch)
  if (wasSea && !next.see_sea_enabled && storyEnded.value) {
    getToast()("故事在这里告一段落", "info")
  }
  if (follow) await scrollToBottom()
  else newContent.value = true
  return next
}

function abortStream() {
  streamController?.abort()
  streamController = null
}

async function disableSeaAfterConnectionLoss() {
  if (!journey.value?.see_sea_enabled) return
  const expectedEpoch = journey.value.selection_epoch
  try {
    const result = await getApi().interactions.updateModes(journeyId.value, {
      see_sea_enabled: false,
      expected_selection_epoch: expectedEpoch,
    })
    applyModeJourney(result.journey, expectedEpoch)
    syncHeartbeat()
  } catch {}
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function followAttempt(attempt) {
  if (!attempt?.id || disposed) return
  abortStream()
  currentAttempt.value = attempt
  streamText.value = attempt.visible_text || ""
  streamOffset.value = Number(
    attempt.visible_offset ?? streamText.value.length,
  )
  streamError.value = ""
  const controller = new AbortController()
  streamController = controller
  const retryStartedAt = Date.now()
  while (!controller.signal.aborted && !disposed) {
    try {
      for await (const event of getApi().interactions.streamAttempt(
        journeyId.value,
        attempt.id,
        streamOffset.value,
        { signal: controller.signal },
      )) {
        if (controller.signal.aborted || disposed) return
        if (event.event === "reset") {
          streamText.value = ""
          streamOffset.value = 0
        } else if (event.event === "chunk") {
          const follow = isNearBottom()
          streamText.value += event.data?.text || ""
          streamOffset.value = Number(event.data?.offset || streamText.value.length)
          if (follow) await scrollToBottom()
          else newContent.value = true
        } else if (event.event === "status") {
          currentAttempt.value = {
            ...currentAttempt.value,
            ...event.data,
            id: attempt.id,
          }
        }
      }
      break
    } catch {
      if (controller.signal.aborted || disposed) return
      if (Date.now() - retryStartedAt >= 60_000) {
        streamError.value = "连接暂时中断；已保存的故事内容仍会保留。"
        await disableSeaAfterConnectionLoss()
        return
      }
      streamError.value = "连接中断，正在从已保存位置恢复…"
      await wait(1000)
    }
  }
  if (controller.signal.aborted || disposed) return
  streamError.value = ""
  try {
    const next = await refreshJourney()
    streamText.value = next.active_attempt?.visible_text || ""
    const successor = next.active_attempt
    if (
      successor
      && ["pending", "preparing_context", "running"].includes(successor.status)
    ) {
      void followAttempt(successor)
    } else {
      currentAttempt.value = successor || currentAttempt.value
    }
  } catch {
    streamError.value = "故事已保存，但最新状态暂时无法载入；已显示内容仍保留，请刷新页面重试。"
  }
}

async function startMutation(
  run,
  { preserveComposer = false, usesComposer = false } = {},
) {
  if (sending.value) return null
  if (!requireModelConnection()) return null
  if (usesComposer && composerTooLong.value) {
    getToast()("这次输入过长，请分几次发送", "warning")
    return null
  }
  const requestJourneyId = journeyId.value
  const requestSelectionEpoch = journey.value?.selection_epoch
  const requestComposer = composer.value
  const ownsRequest = () => (
    !disposed
    && journeyId.value === requestJourneyId
    && journey.value?.selection_epoch === requestSelectionEpoch
  )
  sending.value = true
  conflict.value = null
  try {
    const result = await run()
    if (!ownsRequest()) {
      if (usesComposer && !preserveComposer && readJourneyDraft(requestJourneyId) === requestComposer) {
        writeJourneyDraft(requestJourneyId, "")
      }
      return null
    }
    applyJourney(result.journey)
    if (usesComposer && !preserveComposer && composer.value === requestComposer) {
      composer.value = ""
      writeJourneyDraft(requestJourneyId, "")
      editingNodeId.value = null
    }
    connectionProblem.value = false
    void refreshPathIndex(result.journey.selection_epoch)
    if (result.attempt) void followAttempt(result.attempt)
    await scrollToBottom()
    return result
  } catch (error) {
    if (!ownsRequest()) return null
    if (error?.status === 409 && error?.body?.error === "interaction_selection_conflict") {
      conflict.value = {
        nodeId: journey.value?.selected_leaf_node_id,
        content: composer.value,
        currentEpoch: error.body?.context?.current_selection_epoch,
      }
    } else {
      const safeError = safeInteractionError(error)
      if (safeError.action === "connection") {
        connectionProblem.value = true
      }
      getToast()(safeError.message, "error")
    }
    return null
  } finally {
    if (!disposed && journeyId.value === requestJourneyId) {
      sending.value = false
    }
  }
}

async function send() {
  const content = composer.value.trim()
  if (!content || isGenerating.value || composerTooLong.value) return
  if (awaitingContinue.value) {
    getToast()("请先继续写完、保留这段，或重新生成", "info")
    return
  }
  const epoch = journey.value.selection_epoch
  if (editingNodeId.value) {
    await startMutation(() => getApi().interactions.editUserMessage(
      journeyId.value,
      editingNodeId.value,
      {
        content,
        expected_selection_epoch: epoch,
        idempotency_key: interactionOperationKey("edit"),
      },
    ), { usesComposer: true })
    return
  }
  await startMutation(() => getApi().interactions.sendMessage(
    journeyId.value,
    {
      content,
      expected_selection_epoch: epoch,
      idempotency_key: interactionOperationKey("message"),
    },
  ), { usesComposer: true })
}

function onComposerKeydown(event) {
  if (event.isComposing || composing.value) return
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault()
    send()
  }
}

async function stop() {
  if (!currentAttempt.value?.id || stopping.value) return
  stopping.value = true
  try {
    const result = await getApi().interactions.stopAttempt(
      journeyId.value,
      currentAttempt.value.id,
      { expected_selection_epoch: journey.value.selection_epoch },
    )
    abortStream()
    currentAttempt.value = result.attempt
    stopAfterCurrentNotice.value = false
    await refreshJourney()
    streamText.value = ""
  } catch {
    getToast()("停止请求暂时失败；故事仍在生成，请重试。", "error")
  } finally {
    stopping.value = false
  }
}

async function retryAttempt() {
  if (!currentAttempt.value?.id) return
  await startMutation(() => getApi().interactions.retryAttempt(
    journeyId.value,
    currentAttempt.value.id,
    {
      expected_selection_epoch: journey.value.selection_epoch,
      idempotency_key: interactionOperationKey("retry"),
    },
  ))
}

async function continueAttempt() {
  if (!currentAttempt.value?.id) return
  await startMutation(() => getApi().interactions.continueAttempt(
    journeyId.value,
    currentAttempt.value.id,
    {
      expected_selection_epoch: journey.value.selection_epoch,
      idempotency_key: interactionOperationKey("continue"),
    },
  ), { preserveComposer: true })
}

async function keepPartial() {
  if (!currentAttempt.value?.id) return
  try {
    await getApi().interactions.keepAttempt(
      journeyId.value,
      currentAttempt.value.id,
      { expected_selection_epoch: journey.value.selection_epoch },
    )
    await refreshJourney()
    streamText.value = ""
  } catch {
    getToast()("暂时无法保留这段；已生成的内容仍在，请重试。", "error")
  }
}

async function regenerate(message) {
  await startMutation(() => getApi().interactions.regenerate(
    journeyId.value,
    message.id,
    {
      expected_selection_epoch: journey.value.selection_epoch,
      idempotency_key: interactionOperationKey("regenerate"),
    },
  ), { preserveComposer: true })
}

function editUser(message) {
  composer.value = message.content
  editingNodeId.value = message.id
  nextTick(() => composerInput.value?.focus())
}

function cancelEdit() {
  editingNodeId.value = null
  composer.value = ""
}

async function copyMessage(message) {
  try {
    await navigator.clipboard.writeText(message.content)
    getToast()("已复制", "success")
  } catch {
    getToast()("复制失败，请长按或选中文字复制", "error")
  }
}

function fillAction(text) {
  const input = composerInput.value
  const current = composer.value
  const start = Number.isInteger(input?.selectionStart)
    ? input.selectionStart
    : current.length
  const end = Number.isInteger(input?.selectionEnd)
    ? input.selectionEnd
    : start
  const before = current.slice(0, start)
  const after = current.slice(end)
  const leading = before && !/\s$/.test(before) ? "\n" : ""
  const trailing = after && !/^\s/.test(after) ? "\n" : ""
  composer.value = `${before}${leading}${text}${trailing}${after}`
  const caret = before.length + leading.length + text.length
  editingNodeId.value = null
  nextTick(() => {
    composerInput.value?.focus()
    composerInput.value?.setSelectionRange(caret, caret)
  })
}

function branchesForNode(nodeId) {
  const cached = branchesByNode.value[nodeId]
  return cached?.generation === branchCacheGeneration
    ? cached.variants
    : []
}

async function loadBranches(nodeId) {
  if (!nodeId) return []
  const cached = branchesByNode.value[nodeId]
  if (cached?.generation === branchCacheGeneration) {
    return cached.variants
  }
  const requestGeneration = branchCacheGeneration
  const requestEpoch = journey.value?.selection_epoch
  const loadKey = `${requestGeneration}:${nodeId}`
  if (branchLoads.has(loadKey)) return branchLoads.get(loadKey)
  const requestJourneyId = journeyId.value
  const request = (async () => {
    try {
      const data = await getApi().interactions.listBranches(
        requestJourneyId,
        nodeId,
      )
      if (
        requestJourneyId !== journeyId.value
        || requestGeneration !== branchCacheGeneration
        || requestEpoch !== journey.value?.selection_epoch
      ) return []
      const variants = data.variants || []
      branchesByNode.value = {
        ...branchesByNode.value,
        [nodeId]: {
          generation: requestGeneration,
          variants,
        },
      }
      return variants
    } catch {
      return []
    } finally {
      branchLoads.delete(loadKey)
    }
  })()
  branchLoads.set(loadKey, request)
  return request
}

async function refreshLatestBranches() {
  const latest = [...messages.value]
    .reverse()
    .find((message) => (
      message.role === "assistant" && message.message_kind === "story"
    ))
  if (latest) await loadBranches(latest.id)
}

function branchPosition(nodeId) {
  const variants = branchesForNode(nodeId)
  if (variants.length < 2) return ""
  const selected = variants.find((variant) => variant.selected)
  return `${selected?.ordinal || 1}/${selected?.total || variants.length}`
}

async function toggleBranches(message) {
  if (branchOpenNode.value === message.id) {
    branchOpenNode.value = null
    return
  }
  const variants = await loadBranches(message.id)
  if (variants.length < 2) return
  branchOpenNode.value = message.id
}

function recentVariants(nodeId) {
  const variants = branchesForNode(nodeId)
  const current = variants.find((variant) => variant.selected)
  const others = variants.filter((variant) => !variant.selected).slice(-2).reverse()
  return current ? [current, ...others] : others
}

async function selectBranch(nodeId) {
  if (isGenerating.value || awaitingContinue.value) {
    getToast()(
      awaitingContinue.value
        ? "请先处理尚未写完的上一段故事"
        : "请等待当前故事写完或先停止生成",
      "info",
    )
    return
  }
  const draft = composer.value
  try {
    const next = await getApi().interactions.selectBranch(
      journeyId.value,
      nodeId,
      { expected_selection_epoch: journey.value.selection_epoch },
    )
    applyJourney(next)
    composer.value = draft
    branchDraftNotice.value = Boolean(draft.trim())
    branchOpenNode.value = null
    await refreshPathIndex(next.selection_epoch)
    await locateMessage(nodeId)
  } catch {
    getToast()("暂时无法切换发展；你的草稿仍保留，请重试。", "error")
  }
}

function closeMoreMenu() {
  if (moreMenu.value) moreMenu.value.open = false
}

function closeMoreMenuAndFocus() {
  closeMoreMenu()
  void nextTick(() => moreMenu.value?.querySelector?.("summary")?.focus?.())
}

function onThemeMenuKeydown(event) {
  const items = [...event.currentTarget.querySelectorAll('[role="menuitemradio"]')]
  if (event.key === "Escape") {
    event.preventDefault()
    closeMoreMenuAndFocus()
    return
  }
  const current = items.indexOf(document.activeElement)
  const next = event.key === "Home"
    ? items[0]
    : event.key === "End"
      ? items.at(-1)
      : ["ArrowRight", "ArrowDown"].includes(event.key)
        ? items[(current + 1 + items.length) % items.length]
        : ["ArrowLeft", "ArrowUp"].includes(event.key)
          ? items[(current - 1 + items.length) % items.length]
          : null
  if (!next) return
  event.preventDefault()
  next.focus()
}

async function openSourceInfo() {
  if (!journey.value?.source) return
  closeMoreMenu()
  sourceInfoOpen.value = true
  sourceLoading.value = true
  sourceError.value = ""
  sourceCurrentAnchorKey.value = ""
  sourceUpgradeAnchorKey.value = ""
  try {
    sourceRevision.value = await getApi().interactions.getSource(
      journey.value.source.revision_id,
    )
    const [referencesResult, objectsResult, sourcesResult] = await Promise.allSettled([
      getApi().interactions.getJourneyReferences(journeyId.value),
      getApi().interactions.listSourceObjects(sourceRevision.value.id, {
        chapter_index: journey.value.source.progress_chapter_index,
        end_offset: journey.value.source.progress_end_offset,
      }),
      getApi().interactions.listSources(),
    ])
    if (referencesResult.status === "rejected") throw referencesResult.reason
    sourceInfo.value = referencesResult.value
    sourceObjects.value = objectsResult.status === "fulfilled"
      ? (objectsResult.value.items || []).filter((item) => item.entity_type !== "relation")
      : []
    const project = sourcesResult.status === "fulfilled"
      ? (sourcesResult.value.projects || []).find(
        (item) => item.project_id === sourceRevision.value.project_id,
      )
      : null
    sourceUpgrade.value = project?.latest_revision?.version_number
      > sourceRevision.value.version_number
      && project.latest_revision.status === "ready"
      ? await getApi().interactions.getSource(project.latest_revision.id)
      : null
    await nextTick()
    sourceDrawer.value?.focus?.()
  } catch (requestError) {
    sourceError.value = requestError?.message || "作品资料暂时无法载入。"
  } finally {
    sourceLoading.value = false
  }
}

function closeSourceInfo() {
  sourceInfoOpen.value = false
  sourceError.value = ""
  void nextTick(() => moreMenu.value?.querySelector?.("summary")?.focus?.())
}

async function updateSourceReference(action, referenceKey = null) {
  if (!sourceInfo.value || isGenerating.value || awaitingContinue.value) return
  sourceLoading.value = true
  sourceError.value = ""
  try {
    sourceInfo.value = await getApi().interactions.updateJourneyReferences(
      journeyId.value,
      {
        action,
        reference_key: referenceKey,
        expected_source_context_epoch: sourceInfo.value.source.source_context_epoch,
      },
    )
    journey.value = { ...journey.value, source: sourceInfo.value.source }
  } catch (requestError) {
    sourceError.value = requestError?.message || "作品资料设置未能保存。"
  } finally {
    sourceLoading.value = false
  }
}

async function updateJourneySource(targetRevision, anchorKey) {
  if (!anchorKey || isGenerating.value || awaitingContinue.value) return
  sourceLoading.value = true
  sourceError.value = ""
  try {
    const next = await getApi().interactions.updateJourneySource(
      journeyId.value,
      {
        source_revision_id: targetRevision.id,
        progress_anchor_key: anchorKey,
        expected_selection_epoch: journey.value.selection_epoch,
        expected_source_context_epoch: journey.value.source.source_context_epoch,
      },
    )
    applyJourney(next, { preserveMessages: true })
    await openSourceInfo()
  } catch (requestError) {
    sourceError.value = requestError?.message || "剧情进度或资料版本未能更新。"
  } finally {
    sourceLoading.value = false
  }
}

function isPinned(referenceKey) {
  return (sourceInfo.value?.pinned || []).some(
    (item) => item.reference_key === referenceKey,
  )
}

function isExcluded(referenceKey) {
  return (sourceInfo.value?.excluded || []).some(
    (item) => item.reference_key === referenceKey,
  )
}

function selectTheme(value, event) {
  const theme = normalizeTheme(value)
  currentTheme.value = theme
  event.currentTarget.dispatchEvent(new CustomEvent(
    "shell-theme-request",
    { bubbles: true, detail: theme },
  ))
  closeMoreMenuAndFocus()
}

async function openTree() {
  treeOpen.value = true
  if (treeLoading.value) return
  treeLoading.value = true
  treeLoadError.value = ""
  try {
    const data = await getApi().interactions.getTree(journeyId.value)
    treeBranchPoints.value = [...(data.branch_points || [])].reverse()
    treeOlderExpanded.value = false
  } catch {
    treeLoadError.value = "分支历史暂时无法载入，请稍后重试。"
    getToast()(treeLoadError.value, "error")
  } finally {
    treeLoading.value = false
  }
}

async function openOverview(trigger = null) {
  const triggerElement = trigger?.currentTarget || trigger
  if (
    triggerElement?.focus
    && !overviewDrawer.value?.contains(triggerElement)
  ) overviewReturnFocus.value = triggerElement
  const generation = ++overviewGeneration
  const requestJourneyId = journeyId.value
  const requestSelectionEpoch = journey.value?.selection_epoch
  const requestBranchId = journey.value?.selected_leaf_node_id
  const ownsRequest = () => (
    !disposed
    && overviewOpen.value
    && generation === overviewGeneration
    && journeyId.value === requestJourneyId
    && journey.value?.selection_epoch === requestSelectionEpoch
  )
  overviewOpen.value = true
  overviewLoading.value = true
  overviewLoadError.value = ""
  try {
    const nextOverview = await getApi().interactions.getOverview(requestJourneyId)
    if (!ownsRequest()) return
    overview.value = nextOverview
    overviewDraft.value = cloneOverviewSections(overview.value.sections)
    overviewBaseline.value = JSON.stringify(overviewDraft.value)
    overviewEditing.value = false
    overviewConflict.value = null
    overviewEditContext.value = null
    overviewDraftNotice.value = false
    const saved = readOverviewDraft(
      requestJourneyId,
      requestBranchId,
    )
    if (saved?.sections) {
      overviewDraft.value = cloneOverviewSections(saved.sections)
      overviewEditContext.value = {
        nodeId: requestBranchId,
        selectionEpoch:
          saved.selectionEpoch ?? requestSelectionEpoch,
        overviewEpoch:
          saved.overviewEpoch ?? overview.value?.overview_epoch,
        baseRevisionId:
          saved.baseRevisionId ?? overview.value?.base_revision_id,
        baseSelectedLeafNodeId:
          saved.baseSelectedLeafNodeId
          ?? overview.value?.base_selected_leaf_node_id,
        baseSelectedPathHash:
          saved.baseSelectedPathHash
          ?? overview.value?.base_selected_path_hash,
      }
      overviewDraftNotice.value = (
        saved.overviewEpoch !== overview.value.overview_epoch
        || saved.selectionEpoch !== requestSelectionEpoch
      )
      overviewEditing.value = true
    }
  } catch {
    if (!ownsRequest()) return
    overviewLoadError.value = "回顾暂时无法载入，请稍后重试。"
    getToast()(overviewLoadError.value, "error")
  } finally {
    if (!disposed && generation === overviewGeneration) {
      overviewLoading.value = false
    }
  }
}

function beginOverviewEdit() {
  overviewDraft.value = cloneOverviewSections(overview.value?.sections)
  overviewBaseline.value = JSON.stringify(overviewDraft.value)
  overviewEditContext.value = {
    nodeId: journey.value?.selected_leaf_node_id,
    selectionEpoch: journey.value?.selection_epoch,
    overviewEpoch: overview.value?.overview_epoch,
    baseRevisionId: overview.value?.base_revision_id,
    baseSelectedLeafNodeId: overview.value?.base_selected_leaf_node_id,
    baseSelectedPathHash: overview.value?.base_selected_path_hash,
  }
  overviewConflict.value = null
  overviewDraftNotice.value = false
  overviewEditing.value = true
}

function editOverview() {
  if (!overviewHasContent.value) return
  beginOverviewEdit()
}

function syncStorySelection() {
  const selection = globalThis.getSelection?.()
  if (!selection || selection.isCollapsed || !selection.rangeCount) return
  const container = selection.getRangeAt(0).commonAncestorContainer
  const element = container.nodeType === 3 ? container.parentElement : container
  selectedStoryText.value = storyPane.value?.contains(element)
    ? selection.toString().trim()
    : ""
}

async function rememberComposerNote() {
  const additions = [...new Set([
    selectedStoryText.value,
    composer.value.trim(),
  ].filter(Boolean))]
  if (!additions.length || overviewLoading.value || overviewSaving.value) return
  overviewReturnFocus.value = rememberButton.value
  if (!overviewOpen.value || !overview.value) {
    await openOverview(rememberButton.value)
  }
  if (overviewLoadError.value || !overview.value) return
  if (!overviewEditing.value) beginOverviewEdit()
  const existing = overviewDraft.value.must_remember.trim()
  const existingLines = new Set(existing.split("\n").map((line) => line.trim()))
  const novelAdditions = additions.filter((item) => !existingLines.has(item))
  const nextValue = [existing, ...novelAdditions].filter(Boolean).join("\n")
  if (nextValue.length > 50_000) {
    getToast()("要记住的内容过长，请先缩短选中内容或输入。", "warning")
    return
  }
  overviewDraft.value.must_remember = nextValue
  selectedStoryText.value = ""
  globalThis.getSelection?.()?.removeAllRanges?.()
  await nextTick()
  overviewDrawer.value
    ?.querySelector('textarea[data-overview-section="must_remember"]')
    ?.focus()
  getToast()("已填入“必须继续记住”；确认内容后再保存。", "info")
}

function cancelOverviewEdit() {
  const draftBranchId = (
    overviewEditContext.value?.nodeId || journey.value?.selected_leaf_node_id
  )
  overviewDraft.value = cloneOverviewSections(overview.value?.sections)
  overviewBaseline.value = JSON.stringify(overviewDraft.value)
  overviewEditing.value = false
  overviewConflict.value = null
  overviewEditContext.value = null
  overviewDraftNotice.value = false
  writeOverviewDraft(
    journeyId.value,
    draftBranchId,
    null,
  )
}

function closeOverview() {
  if (
    overviewDirty.value
    && !getConfirm()("回顾有未保存修改，确定放弃并关闭吗？")
  ) return
  if (overviewDirty.value) {
    writeOverviewDraft(
      journeyId.value,
      overviewEditContext.value?.nodeId || journey.value?.selected_leaf_node_id,
      null,
    )
  }
  overviewEditing.value = false
  overviewConflict.value = null
  overviewEditContext.value = null
  overviewDraftNotice.value = false
  overviewGeneration += 1
  overviewLoading.value = false
  overviewOpen.value = false
  const returnFocus = overviewReturnFocus.value
  overviewReturnFocus.value = null
  if (returnFocus?.focus) void nextTick(() => returnFocus.focus())
}

async function saveOverview() {
  if (!overviewDraftHasContent.value || overviewSaving.value) return false
  overviewSaving.value = true
  const draftBranchId = (
    overviewEditContext.value?.nodeId || journey.value?.selected_leaf_node_id
  )
  try {
    overview.value = await getApi().interactions.updateOverview(journeyId.value, {
      sections: cloneOverviewSections(overviewDraft.value),
      expected_overview_epoch: overviewEditContext.value.overviewEpoch,
      expected_selection_epoch: overviewEditContext.value.selectionEpoch,
      base_revision_id: overviewEditContext.value.baseRevisionId,
      base_selected_leaf_node_id:
        overviewEditContext.value.baseSelectedLeafNodeId,
      base_selected_path_hash:
        overviewEditContext.value.baseSelectedPathHash,
    })
    journey.value.overview_epoch = overview.value.overview_epoch
    overviewBaseline.value = JSON.stringify(
      cloneOverviewSections(overview.value.sections),
    )
    overviewEditing.value = false
    overviewConflict.value = null
    overviewEditContext.value = null
    overviewDraftNotice.value = false
    writeOverviewDraft(
      journeyId.value,
      draftBranchId,
      null,
    )
    getToast()(
      overview.value.status === "refreshing"
        ? "回顾已保存；正在整理最近剧情"
        : "回顾已保存",
      "success",
    )
    return true
  } catch (error) {
    if (error?.status === 409) {
      overviewConflict.value = {
        nodeId: overviewEditContext.value?.nodeId,
      }
      getToast()("旅程在别处发生了变化；你的回顾草稿仍保留。", "error")
      return false
    }
    getToast()("回顾保存失败；你的草稿仍保留，请稍后重试。", "error")
    return false
  } finally {
    overviewSaving.value = false
  }
}

async function loadLatestOverviewConflict() {
  try {
    const [nextJourney, nextOverview] = await Promise.all([
      getApi().interactions.getJourney(journeyId.value),
      getApi().interactions.getOverview(journeyId.value),
    ])
    applyJourney(nextJourney)
    overview.value = nextOverview
    overviewBaseline.value = JSON.stringify(
      cloneOverviewSections(nextOverview.sections),
    )
    overviewEditContext.value = {
      nodeId: nextJourney.selected_leaf_node_id,
      selectionEpoch: nextJourney.selection_epoch,
      overviewEpoch: nextOverview.overview_epoch,
      baseRevisionId: nextOverview.base_revision_id,
      baseSelectedLeafNodeId: nextOverview.base_selected_leaf_node_id,
      baseSelectedPathHash: nextOverview.base_selected_path_hash,
    }
    overviewConflict.value = null
    overviewDraftNotice.value = false
    getToast()("已载入最新发展；你的草稿仍在输入框，请核对后保存。", "info")
  } catch {
    getToast()("暂时无法载入最新发展，请稍后重试。", "error")
  }
}

async function returnToOriginalOverviewAndSave() {
  const originalNodeId = overviewConflict.value?.nodeId
  if (!originalNodeId) return
  try {
    let nextJourney = await getApi().interactions.getJourney(journeyId.value)
    if (nextJourney.selected_leaf_node_id !== originalNodeId) {
      nextJourney = await getApi().interactions.selectBranch(
        journeyId.value,
        originalNodeId,
        { expected_selection_epoch: nextJourney.selection_epoch },
      )
    }
    applyJourney(nextJourney)
    overview.value = await getApi().interactions.getOverview(journeyId.value)
    overviewEditContext.value = {
      nodeId: nextJourney.selected_leaf_node_id,
      selectionEpoch: nextJourney.selection_epoch,
      overviewEpoch: overview.value.overview_epoch,
      baseRevisionId: overview.value.base_revision_id,
      baseSelectedLeafNodeId: overview.value.base_selected_leaf_node_id,
      baseSelectedPathHash: overview.value.base_selected_path_hash,
    }
    overviewConflict.value = null
    await saveOverview()
  } catch {
    getToast()("暂时无法回到原发展；回顾草稿仍保留。", "error")
  }
}

async function retryOverview() {
  if (overviewRetrying.value) return
  overviewRetrying.value = true
  try {
    overview.value = await getApi().interactions.retryOverview(journeyId.value)
    journey.value.overview_epoch = overview.value.overview_epoch
    getToast()("正在重新整理最近剧情", "info")
  } catch (error) {
    getToast()(safeInteractionError(error).message, "error")
  } finally {
    overviewRetrying.value = false
  }
}

async function openGenerationRecords() {
  generationRecordsOpen.value = true
  generationRecordsLoading.value = true
  try {
    const data = await getApi().interactions.listGenerationRecords(
      journeyId.value,
    )
    generationRecords.value = data.items || []
  } catch {
    getToast()("生成记录暂时无法载入，请稍后重试。", "error")
  } finally {
    generationRecordsLoading.value = false
  }
}

function generationRecordError(record) {
  return safeInteractionError(record?.error_kind || "generation_failed")
}

async function keepGenerationRecord(record) {
  try {
    await getApi().interactions.keepAttempt(journeyId.value, record.id, {
      expected_selection_epoch: journey.value.selection_epoch,
    })
    const next = await getApi().interactions.getJourney(journeyId.value)
    applyJourney(next)
    await Promise.all([
      refreshPathIndex(next.selection_epoch),
      refreshLatestBranches(),
      openGenerationRecords(),
    ])
    getToast()("这段内容已保留，并切回它所在的发展。", "success")
  } catch (error) {
    getToast()(safeInteractionError(error).message, "error")
  }
}

async function toggleMode(field) {
  if (
    field === "see_sea_enabled"
    && !journey.value.see_sea_enabled
    && !requireModelConnection()
  ) return
  const requestJourneyId = journeyId.value
  const payload = {
    expected_selection_epoch: journey.value.selection_epoch,
    [field]: !journey.value[field],
  }
  const turningSeaOff = (
    field === "see_sea_enabled" && journey.value.see_sea_enabled
  )
  try {
    const result = await getApi().interactions.updateModes(requestJourneyId, payload)
    if (disposed || journeyId.value !== requestJourneyId) {
      if (field === "see_sea_enabled" && payload[field]) {
        await getApi().interactions.leaveJourney(requestJourneyId).catch(() => {})
      }
      return
    }
    const responseOnCurrentBranch = applyModeJourney(
      result.journey,
      payload.expected_selection_epoch,
    )
    stopAfterCurrentNotice.value = Boolean(
      turningSeaOff
      && ["pending", "preparing_context", "running"].includes(
        currentAttempt.value?.status,
      )
    )
    syncHeartbeat()
    if (
      responseOnCurrentBranch
      && result.attempt
      && ["pending", "preparing_context", "running"].includes(
        result.attempt.status,
      )
    ) {
      void followAttempt(result.attempt)
    }
  } catch (error) {
    if (!disposed && journeyId.value === requestJourneyId) {
      getToast()(safeInteractionError(error).message, "error")
    }
  }
}

function requestModeToggle(field) {
  if (
    field === "see_sea_enabled"
    && !journey.value.see_sea_enabled
    && !hasActiveConnection.value
  ) {
    goConnect()
    return
  }
  if (
    field === "see_sea_enabled"
    && !journey.value.see_sea_enabled
    && !seeSeaNoticeAcknowledged.value
  ) {
    seeSeaNoticeOpen.value = true
    return
  }
  void toggleMode(field)
}

async function confirmSeeSea() {
  if (seeSeaConfirming.value) return
  const requestJourneyId = journeyId.value
  seeSeaConfirming.value = true
  try {
    await getApi().interactions.acknowledgeSeeSeaNotice()
    if (disposed || journeyId.value !== requestJourneyId) return
    seeSeaNoticeAcknowledged.value = true
    seeSeaNoticeOpen.value = false
    await toggleMode("see_sea_enabled")
  } catch {
    if (!disposed && journeyId.value === requestJourneyId) {
      getToast()("暂时无法保存提示状态，请重试。", "error")
    }
  } finally {
    seeSeaConfirming.value = false
  }
}

async function renameJourney() {
  const title = getPrompt()("修改旅程标题", journey.value.title)
  if (!title?.trim()) return
  try {
    const next = await getApi().interactions.updateTitle(journeyId.value, {
      title: title.trim(),
    })
    mergeJourneyMetadata(next, ["title", "title_source"])
    getToast()("旅程标题已更新", "success")
  } catch {
    getToast()("旅程标题暂时无法保存，请重试。", "error")
  }
}

async function archiveJourney() {
  const suffix = isGenerating.value || awaitingContinue.value
    ? " 当前生成会停止，已显示正文会作为未完整片段保留。"
    : ""
  if (!getConfirm()(`归档「${journey.value.title}」？${suffix}`)) return
  const requestJourneyId = journeyId.value
  try {
    await getApi().interactions.archiveJourney(requestJourneyId)
    if (disposed || journeyId.value !== requestJourneyId) return
    abortStream()
    await getRouter().navigate("journeys")
  } catch {
    if (!disposed && journeyId.value === requestJourneyId) {
      getToast()("归档失败；旅程和正在生成的内容仍保留，请重试。", "error")
    }
  }
}

async function exportJourney(format, storyOnly, includeOverview = true) {
  const requestJourneyId = journeyId.value
  try {
    const data = await getApi().interactions.exportJourney(requestJourneyId, {
      format,
      story_only: storyOnly,
      include_overview: includeOverview,
    })
    if (disposed || journeyId.value !== requestJourneyId) return
    const blob = new Blob([data.content], { type: data.media_type })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = data.filename
    link.click()
    URL.revokeObjectURL(url)
    getToast()(storyOnly ? "故事正文已导出" : "完整记录已导出", "success")
  } catch {
    if (!disposed && journeyId.value === requestJourneyId) {
      getToast()("导出暂时失败；旅程内容没有受到影响，请重试。", "error")
    }
  }
}

async function loadOlder() {
  if (loadingOlder.value) return
  const first = messages.value[0]
  if (!first) return
  const requestJourneyId = journeyId.value
  const requestEpoch = journey.value?.selection_epoch
  const requestFirstId = first.id
  loadingOlder.value = true
  const pane = storyPane.value
  const oldHeight = pane?.scrollHeight || 0
  try {
    const page = await getApi().interactions.getMessages(journeyId.value, {
      before_node_id: first.id,
      limit: 20,
    })
    if (
      requestJourneyId !== journeyId.value
      || requestEpoch !== journey.value?.selection_epoch
      || page.selection_epoch !== requestEpoch
      || messages.value[0]?.id !== requestFirstId
    ) return
    messages.value = [...(page.items || []), ...messages.value]
    journey.value.has_older_messages = page.has_older ?? page.has_more
    await nextTick()
    if (pane) pane.scrollTop += pane.scrollHeight - oldHeight
  } catch {
    getToast()("更早内容暂时无法加载，请稍后重试。", "error")
  } finally {
    loadingOlder.value = false
  }
}

async function loadLatestAfterConflict() {
  const pendingConflict = conflict.value
  try {
    await refreshJourney()
    conflict.value = null
  } catch {
    conflict.value = pendingConflict
    getToast()("最新发展暂时无法载入；你的输入仍保留，请重试。", "error")
  }
}

async function continueFromVisible() {
  const value = conflict.value
  const content = composer.value.trim()
  if (!value?.nodeId || !content) return
  const result = await startMutation(() => getApi().interactions.continueFromNode(
    journeyId.value,
    value.nodeId,
    {
      content,
      expected_selection_epoch: value.currentEpoch,
      idempotency_key: interactionOperationKey("from-here"),
    },
  ), { usesComposer: true })
  if (result) conflict.value = null
}

function findMessageElement(id) {
  return [...(storyPane.value?.querySelectorAll?.("[data-rp-message-id]") || [])]
    .find((element) => element.dataset.rpMessageId === id)
}

function scrollMessageElement(target, behavior = "smooth") {
  target?.scrollIntoView({ behavior, block: "start" })
}

async function locateMessage(id) {
  if (!id || locatorBusy.value) return
  const requestedEpoch = pathIndexEpoch.value
  let target = findMessageElement(id)
  if (!target) {
    locatorBusy.value = true
    try {
      const page = await getApi().interactions.getMessages(journeyId.value, {
        around_node_id: id,
        limit: 20,
      })
      if (
        page.selection_epoch !== requestedEpoch
        || journey.value.selection_epoch !== requestedEpoch
      ) return
      messages.value = page.items || []
      journey.value.has_older_messages = page.has_older ?? page.has_more
      hasNewerMessages.value = page.has_newer === true
      await nextTick()
      target = findMessageElement(id)
    } catch {
      getToast()("暂时无法定位这一段，请稍后重试。", "error")
      return
    } finally {
      locatorBusy.value = false
    }
  }
  const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches
  scrollMessageElement(target, reduced ? "auto" : "smooth")
}

function onLocatorInput(event) {
  if (!locatorGesture) {
    locatorGesture = {
      epoch: pathIndexEpoch.value,
      items: pathIndex.value.map((item) => ({ ...item })),
    }
  }
  const position = Number(event.target.value)
  locatorPosition.value = position
  locatorPreviewItem.value = locatorGesture.items[Math.max(0, position - 1)] || null
}

async function onLocatorChange() {
  const gesture = locatorGesture
  const target = locatorPreviewItem.value
  locatorGesture = null
  locatorPreviewItem.value = null
  if (
    !gesture
    || gesture.epoch !== pathIndexEpoch.value
    || gesture.epoch !== journey.value?.selection_epoch
  ) {
    locatorExpanded.value = false
    globalThis.document?.activeElement?.blur?.()
    updateLocatorFromScroll()
    getToast()("当前发展在拖动期间已更新，请重新定位", "info")
    return
  }
  await locateMessage(target?.id)
  locatorExpanded.value = false
  globalThis.document?.activeElement?.blur?.()
}

async function onLocatorTick(item, index) {
  try {
    const requestedEpoch = pathIndexEpoch.value
    if (requestedEpoch !== journey.value?.selection_epoch) {
      getToast()("当前发展已更新，请重新定位", "info")
      return
    }
    locatorPosition.value = index + 1
    await locateMessage(item.id)
  } finally {
    locatorExpanded.value = false
    globalThis.document?.activeElement?.blur?.()
  }
}

function updateLocatorFromScroll() {
  if (!storyPane.value || !pathIndex.value.length) return
  const line = storyPane.value.getBoundingClientRect().top + 72
  let currentId = null
  for (const element of storyPane.value.querySelectorAll(
    ".rp-message--assistant[data-rp-message-id]",
  )) {
    if (element.getBoundingClientRect().top <= line) {
      currentId = element.dataset.rpMessageId
    } else {
      break
    }
  }
  const index = pathIndex.value.findIndex((item) => item.id === currentId)
  if (index >= 0) locatorPosition.value = index + 1
}

function persistScrollPosition() {
  const pane = storyPane.value
  if (!pane) return
  writeJourneyScroll(journeyId.value, {
    anchorId: locatorItem.value?.id || null,
    scrollTop: pane.scrollTop,
    atBottom: isNearBottom(),
  })
}

function onStoryScroll() {
  if (
    storyPane.value?.scrollTop <= 80
    && journey.value?.has_older_messages
    && !loadingOlder.value
  ) {
    void loadOlder()
  }
  if (isNearBottom()) {
    newContent.value = false
    newContentCount.value = 0
    unseenStoryNodeIds.clear()
  }
  if (scrollFrame != null) return
  const schedule = globalThis.requestAnimationFrame || ((run) => setTimeout(run, 16))
  scrollFrame = schedule(() => {
    scrollFrame = null
    updateLocatorFromScroll()
    persistScrollPosition()
  })
}

async function restoreScrollPosition() {
  const saved = readJourneyScroll(journeyId.value)
  if (!saved || saved.atBottom) {
    await scrollToBottom()
    return
  }
  await nextTick()
  let target = saved.anchorId ? findMessageElement(saved.anchorId) : null
  if (!target && saved.anchorId) {
    try {
      const page = await getApi().interactions.getMessages(journeyId.value, {
        around_node_id: saved.anchorId,
        limit: 20,
      })
      if (page.selection_epoch === journey.value.selection_epoch) {
        messages.value = page.items || []
        journey.value.has_older_messages = page.has_older ?? page.has_more
        hasNewerMessages.value = page.has_newer === true
        await nextTick()
        target = findMessageElement(saved.anchorId)
      }
    } catch {
      // Keep the numeric fallback below when the saved window is unavailable.
    }
  }
  if (target) scrollMessageElement(target, "auto")
  else if (storyPane.value) storyPane.value.scrollTop = saved.scrollTop
  updateLocatorFromScroll()
}

function onVisibilityChange() {
  cancelSeeSeaGrace(journeyId.value)
  if (document.visibilityState === "hidden" && journey.value?.see_sea_enabled) {
    stopHeartbeat()
    scheduleSeeSeaGrace(journeyId.value, disableSeaAfterConnectionLoss)
  } else {
    syncHeartbeat()
  }
}

useLeaveGuard(() => (
  !overviewDirty.value
  || getConfirm()("回顾有未保存修改，确定放弃并离开吗？")
))

function beforeUnload(event) {
  if (!overviewDirty.value) return
  event.preventDefault()
  event.returnValue = ""
}

onMounted(() => {
  if (!journey.value) return
  cancelSeeSeaGrace(journeyId.value)
  document.addEventListener("selectionchange", syncStorySelection)
  document.addEventListener("visibilitychange", onVisibilityChange)
  window.addEventListener("beforeunload", beforeUnload)
  syncHeartbeat()
  void nextTick(resizeComposer)
  void refreshPathIndex(journey.value.selection_epoch)
  void refreshLatestBranches()
  void (async () => {
    await restoreScrollPosition()
    if (
      currentAttempt.value
      && ["pending", "preparing_context", "running"].includes(
        currentAttempt.value.status,
      )
    ) {
      void followAttempt(currentAttempt.value)
    }
  })()
})

onBeforeUnmount(() => {
  disposed = true
  overviewGeneration += 1
  persistScrollPosition()
  abortStream()
  stopHeartbeat()
  document.removeEventListener("selectionchange", syncStorySelection)
  document.removeEventListener("visibilitychange", onVisibilityChange)
  window.removeEventListener("beforeunload", beforeUnload)
  if (scrollFrame != null) {
    const cancel = globalThis.cancelAnimationFrame || clearTimeout
    cancel(scrollFrame)
    scrollFrame = null
  }
  cancelSeeSeaGrace(journeyId.value)
  if (journey.value?.see_sea_enabled) {
    void getApi().interactions.leaveJourney(journeyId.value).catch(() => {})
  }
})
</script>

<template>
  <main v-if="journey" class="rp-story-page">
    <header class="rp-story-topbar">
      <button class="rp-icon-button" type="button" aria-label="返回旅程列表" @click="getRouter().navigate('journeys')">‹</button>
      <div class="rp-story-title">
        <strong>{{ journey.title }}</strong>
        <span>互动故事</span>
      </div>
      <details ref="moreMenu" class="rp-more-menu" @keydown.esc.stop.prevent="closeMoreMenuAndFocus">
        <summary aria-label="更多操作">•••</summary>
        <button
          class="rp-sheet-backdrop"
          type="button"
          aria-label="关闭更多操作"
          @click="closeMoreMenuAndFocus"
        ></button>
        <div>
          <header class="rp-more-menu__header">
            <strong>更多操作</strong>
            <button type="button" aria-label="关闭更多操作" @click="closeMoreMenuAndFocus">×</button>
          </header>
          <button type="button" @click="closeMoreMenu(); renameJourney()">重命名旅程</button>
          <button type="button" @click="closeMoreMenu(); openTree()">查看所有分支</button>
          <button type="button" @click="closeMoreMenu(); openGenerationRecords()">生成记录</button>
          <button v-if="journey.source" type="button" @click="openSourceInfo">作品资料</button>
          <button type="button" @click="closeMoreMenu(); exportJourney('md', false)">导出完整记录</button>
          <button type="button" @click="closeMoreMenu(); exportJourney('txt', true, false)">导出故事正文</button>
          <button type="button" @click="closeMoreMenu(); goConnect()">
            更改模型<template v-if="activeProvider">（{{ activeProvider.label }}）</template>
          </button>
          <section class="rp-more-menu__themes" aria-label="主题">
            <span>主题</span>
            <div role="menu" aria-label="选择阅读主题" @keydown="onThemeMenuKeydown">
              <button
                v-for="theme in SHELL_THEMES"
                :key="theme.value"
                type="button"
                role="menuitemradio"
                :data-theme-value="theme.value"
                :class="{ active: currentTheme === theme.value }"
                :aria-checked="currentTheme === theme.value"
                @click="selectTheme(theme.value, $event)"
              >{{ theme.icon }} {{ theme.label }}</button>
            </div>
          </section>
          <button type="button" @click="closeMoreMenu(); dataInfoOpen = true">内容与数据</button>
          <button type="button" @click="closeMoreMenu(); getRouter().navigate('home')">切换使用方式</button>
          <button class="danger" type="button" @click="closeMoreMenu(); archiveJourney()">归档旅程</button>
        </div>
      </details>
    </header>

    <section ref="storyPane" class="rp-story-scroll" @scroll="onStoryScroll">
      <details
        v-if="setupMessages.length"
        class="rp-setup-history"
        :open="messages.length === 0"
      >
        <summary>开场说明</summary>
        <article
          v-for="message in setupMessages"
          :key="message.id"
          class="rp-message"
          :class="`rp-message--${message.role}`"
          :data-rp-message-id="message.id"
        >
          <div class="rp-message__label">
            {{ message.role === "user" ? "你" : "开场说明" }}
          </div>
          <RpMarkdownContent
            v-if="message.role === 'assistant'"
            class="rp-message__text"
            :source="message.content"
          />
          <div v-else class="rp-message__text">{{ message.content }}</div>
          <div v-if="message.role === 'user'" class="rp-message__actions">
            <button type="button" @click="editUser(message)">修改开场</button>
          </div>
        </article>
        <div v-if="awaitingSetupAnswer" class="rp-setup-actions">
          <button type="button" @click="composerInput?.focus()">补充几个关键设定</button>
          <button
            type="button"
            @click="fillAction('请按你目前的理解直接开始故事；不确定处采用低承诺处理。')"
          >按当前理解开始</button>
        </div>
      </details>
      <button v-if="journey.has_older_messages" class="rp-load-older" type="button" @click="loadOlder">加载更早内容</button>
      <article
        v-for="message in messages"
        :key="message.id"
        class="rp-message"
        :class="`rp-message--${message.role}`"
        :data-rp-message-id="message.id"
      >
        <div class="rp-message__label">{{ message.role === "user" ? "你" : "故事" }}</div>
        <RpMarkdownContent
          v-if="message.role === 'assistant'"
          class="rp-message__text"
          :source="message.content"
        />
        <div v-else class="rp-message__text">{{ message.content }}</div>
        <p v-if="message.completion_state === 'partial'" class="rp-partial-note">保留的未完整片段</p>
        <div class="rp-message__actions">
          <template v-if="message.role === 'user'">
            <button type="button" @click="editUser(message)">修改这一步</button>
            <button class="rp-message-action-button" type="button" @click="copyMessage(message)">复制</button>
          </template>
          <template v-else>
            <button class="rp-message-action-button" type="button" @click="copyMessage(message)">复制</button>
            <button
              v-if="message.id === lastStoryMessageId"
              class="rp-message-action-button"
              type="button"
              @click="regenerate(message)"
            >重新生成</button>
            <button
              v-if="message.id === lastStoryMessageId && branchPosition(message.id)"
              type="button"
              @click="toggleBranches(message)"
            >其他分支 {{ branchPosition(message.id) }}</button>
          </template>
        </div>
        <div v-if="branchOpenNode === message.id" class="rp-branch-popover" role="group" aria-label="选择故事分支">
          <button
            v-for="variant in recentVariants(message.id)"
            :key="variant.node_id"
            type="button"
            :class="{ active: variant.selected }"
            :aria-pressed="variant.selected"
            :disabled="isGenerating || awaitingContinue"
            @click="selectBranch(variant.node_id)"
          >
            <span>{{ variant.ordinal }}/{{ variant.total }}</span>
            {{ variant.excerpt }}
          </button>
          <button
            v-if="branchesForNode(message.id).length > 3"
            type="button"
            @click="branchOpenNode = null; openTree()"
          >查看所有分支</button>
        </div>
        <div
          v-if="
            message.role === 'assistant'
            && message.id === lastStoryMessageId
            && message.action_suggestions?.length
            && journey.action_options_enabled
            && !journey.see_sea_enabled
          "
          class="rp-action-options"
          aria-label="行动建议"
        >
          <button
            v-for="(option, optionIndex) in message.action_suggestions"
            :key="`${message.id}-${option.label}-${optionIndex}`"
            class="rp-action-card"
            type="button"
            @click="fillAction(option.text)"
          >
            <span class="rp-action-card__label">{{ option.label || `行动建议 ${optionIndex + 1}` }}</span>
            <span class="rp-action-card__text">{{ option.text }}</span>
          </button>
        </div>
      </article>

      <article v-if="isGenerating || streamText" class="rp-message rp-message--assistant rp-message--streaming" :aria-busy="isGenerating">
        <div class="rp-message__label">故事 · {{ isGenerating ? "正在生成" : "未完成" }}</div>
        <p v-if="currentAttempt?.status === 'preparing_context'" class="rp-stream-status" role="status">
          正在整理最近剧情…
        </p>
        <RpMarkdownContent
          v-if="streamText"
          class="rp-message__text"
          :source="streamText"
        />
        <div v-else class="rp-stream-wait"><i></i><i></i><i></i></div>
        <p v-if="streamError" class="rp-stream-status" :role="streamErrorRole">{{ streamError }}</p>
      </article>

      <div v-if="awaitingContinue" class="rp-attempt-actions">
        <p>这一段到达了模型的单次输出上限。</p>
        <button type="button" @click="continueAttempt">继续写完</button>
        <button type="button" @click="keepPartial">保留这段</button>
        <button type="button" @click="retryAttempt">重新生成</button>
      </div>
      <div v-else-if="failedAttempt" class="rp-attempt-actions rp-attempt-actions--error" role="alert">
        <p>{{ failedMessage }}</p>
        <button
          v-if="failedError.action === 'connection'"
          type="button"
          @click="goConnect"
        >检查模型连接</button>
        <button
          v-else-if="failedError.action === 'overview'"
          type="button"
          @click="openOverview"
        >查看回顾</button>
        <button
          v-else-if="failedError.action === 'source'"
          type="button"
          @click="openSourceInfo"
        >查看作品资料</button>
        <button
          v-if="failedError.action !== 'connection'"
          type="button"
          @click="retryAttempt"
        >重新生成</button>
        <button v-if="streamText" type="button" @click="keepPartial">保留残段</button>
      </div>
      <p v-if="storyEnded" class="rp-story-ended">故事在这里告一段落。你仍可以重新生成，或输入新的延续方式。</p>
    </section>

    <button
      v-if="newContent || hasNewerMessages"
      class="rp-new-content"
      type="button"
      @click="scrollToBottom"
    >{{ newContentCount ? `有 ${newContentCount} 段新内容 · 回到最新 ↓` : "继续查看生成 ↓" }}</button>

    <nav
      v-if="pathIndex.length >= 2"
      class="rp-locator-rail"
      :class="{ 'is-expanded': locatorExpanded }"
      aria-label="快速定位生成段落"
      @pointerdown="locatorExpanded = true"
    >
      <output class="rp-locator-preview">
        {{ locatorBusy ? "正在定位…" : locatorDisplayItem?.excerpt }}
      </output>
      <div
        v-if="pathIndex.length <= 12"
        class="rp-locator-ticks"
        aria-hidden="true"
      >
        <button
          v-for="(item, index) in pathIndex"
          :key="item.id"
          type="button"
          tabindex="-1"
          :class="{ active: index + 1 === locatorPosition }"
          @click="onLocatorTick(item, index)"
        ></button>
      </div>
      <input
        v-model.number="locatorPosition"
        type="range"
        min="1"
        :max="pathIndex.length"
        step="1"
        :aria-label="`第 ${locatorPosition} 段，共 ${pathIndex.length} 段：${locatorDisplayItem?.excerpt || ''}`"
        @focus="locatorExpanded = true"
        @input="onLocatorInput"
        @change="onLocatorChange"
      />
      <span aria-hidden="true">{{ locatorPosition }}/{{ pathIndex.length }}</span>
    </nav>

    <div v-if="conflict" class="rp-conflict-banner" role="alert">
      <span>旅程已在另一处更新，你的输入仍保留在这里。</span>
      <button type="button" @click="loadLatestAfterConflict">载入最新发展</button>
      <button type="button" @click="continueFromVisible">仍从我看到的位置继续</button>
    </div>

    <footer class="rp-composer-dock">
      <div v-if="editingNodeId" class="rp-editing-note">
        正在修改旧输入；保存后会形成一个新分支。
        <button type="button" @click="cancelEdit">取消</button>
      </div>
      <p v-if="branchDraftNotice" class="rp-stream-status">
        已切换发展；草稿仍保留，请确认内容还适用。
      </p>
      <div class="rp-composer">
        <textarea
          ref="composerInput"
          v-model="composer"
          rows="2"
          placeholder="说出你的行动、对话，或直接纠正故事……"
          aria-label="继续旅程"
          @keydown="onComposerKeydown"
          @compositionstart="composing = true"
          @compositionend="composing = false"
        ></textarea>
        <button
          v-if="isGenerating"
          class="rp-stop-button"
          type="button"
          aria-label="停止生成"
          :disabled="stopping"
          @click="stop"
        ><span></span></button>
        <button
          v-else
          class="rp-send-button"
          type="button"
          :disabled="
            sending
            || awaitingContinue
            || !composer.trim()
            || composerTooLong
            || !hasActiveConnection
          "
          aria-label="发送消息"
          title="发送消息"
          @click="send"
        >↑</button>
      </div>
      <p v-if="stopping" class="rp-stream-status" role="status">正在停止…</p>
      <p v-if="showComposerCount" class="rp-input-count" :class="{ error: composerTooLong }">
        {{ composer.length.toLocaleString() }} / 100,000
        <span v-if="composerTooLong">· 这次输入过长，请分几次发送</span>
      </p>
      <div v-if="connectionStateKnown && !hasActiveConnection" class="rp-composer-connection">
        <span>当前模型尚未连接。故事和草稿仍保留在这里。</span>
        <button type="button" @click="goConnect">去连接模型</button>
      </div>
      <div class="rp-composer-tools">
        <button
          v-if="storyStarted"
          type="button"
          class="rp-mode-toggle"
          @click="openOverview"
        >回顾</button>
        <button
          v-if="storyStarted"
          ref="rememberButton"
          type="button"
          class="rp-mode-toggle rp-remember-button"
          :disabled="(!composer.trim() && !selectedStoryText) || overviewLoading || overviewSaving"
          title="把选中的故事片段和输入框内容填入回顾，保存前仍可修改"
          @click="rememberComposerNote"
        >记住这一点</button>
        <button
          ref="seeSeaButton"
          type="button"
          class="rp-mode-toggle"
          :class="{ active: journey.see_sea_enabled }"
          :aria-pressed="journey.see_sea_enabled"
          aria-haspopup="dialog"
          :aria-expanded="seeSeaNoticeOpen"
          aria-controls="rp-story-see-sea-confirm"
          @click="requestModeToggle('see_sea_enabled')"
        >故事自主发展</button>
        <button
          v-if="storyStarted"
          type="button"
          class="rp-mode-toggle"
          :class="{ active: journey.action_options_enabled }"
          :aria-pressed="journey.action_options_enabled"
          @click="requestModeToggle('action_options_enabled')"
        >行动选项</button>
        <span>{{
          stopAfterCurrentNotice
            ? "将在本段结束后停止"
            : (
              journey.see_sea_enabled
                ? "将持续生成，当前步骤优先完成"
                : "⌘/Ctrl + Enter 发送"
            )
        }}</span>
      </div>
      <RpAdaptiveConfirmPopover
        id="rp-story-see-sea-confirm"
        :anchor="seeSeaButton"
        :busy="seeSeaConfirming"
        confirm-text="开始自主发展"
        message="故事会持续自主发展并使用你的模型额度；离开页面或关闭开关后会停止。"
        :open="seeSeaNoticeOpen"
        @close="seeSeaNoticeOpen = false"
        @confirm="confirmSeeSea"
      />
    </footer>

    <aside
      v-if="overviewOpen"
      ref="overviewDrawer"
      class="rp-drawer"
      aria-label="当前回顾"
      :aria-busy="overviewLoading || overviewRetrying"
    >
      <header>
        <div>
          <strong>回顾</strong>
          <span v-if="overviewLoading">正在载入…</span>
          <span v-else-if="overview?.status === 'refreshing'" role="status">正在整理最近剧情…</span>
          <span v-else-if="overview?.status === 'failed'" role="alert">最近剧情尚未整理</span>
          <span v-else-if="overview?.status === 'forming'" role="status">正在形成旅程回顾</span>
          <span v-else>自动整理，可随时手动纠正</span>
        </div>
        <button type="button" aria-label="关闭当前回顾" @click="closeOverview">×</button>
      </header>
      <p v-if="overviewLoading" class="rp-overview-empty" role="status">正在载入回顾…</p>
      <p v-else-if="overviewLoadError" class="rp-overview-empty" role="alert">
        {{ overviewLoadError }}
        <button type="button" @click="openOverview">重新载入</button>
      </p>
      <div v-else-if="overviewEditing" class="rp-overview-sections rp-overview-sections--editing">
        <p v-if="overviewDraftNotice" class="rp-overview-draft-note">
          已恢复这个发展中未保存的回顾草稿；请结合最新内容核对后保存。
        </p>
        <div v-if="overviewConflict" class="rp-overview-conflict" role="alert">
          <span>旅程在别处发生了变化；你的草稿仍保留。</span>
          <div>
            <button type="button" @click="loadLatestOverviewConflict">载入最新</button>
            <button type="button" @click="returnToOriginalOverviewAndSave">
              回到原发展继续保存
            </button>
          </div>
        </div>
        <label v-for="section in overviewSections" :key="section.key">
          <strong>{{ section.label }}</strong>
          <textarea
            v-model="overviewDraft[section.key]"
            :data-overview-section="section.key"
            rows="4"
            maxlength="50000"
          ></textarea>
        </label>
      </div>
      <div v-else class="rp-overview-sections">
        <template v-for="section in overviewSections" :key="section.key">
          <section v-if="overview?.sections?.[section.key]">
            <h3>{{ section.label }}</h3>
            <p>{{ overview.sections[section.key] }}</p>
          </section>
        </template>
        <p v-if="!overviewHasContent" class="rp-overview-empty">
          {{ overview?.is_refreshing ? "正在形成旅程回顾…" : "第一段故事完成后会自动整理回顾。" }}
        </p>
      </div>
      <footer v-if="!overviewLoading && !overviewLoadError">
        <template v-if="overviewEditing">
          <button type="button" @click="cancelOverviewEdit">取消</button>
          <button
            class="primary"
            type="button"
            :disabled="!overviewDraftHasContent || overviewSaving"
            :aria-busy="overviewSaving"
            @click="saveOverview"
          >{{ overviewSaving ? "正在保存…" : "保存修改" }}</button>
        </template>
        <button v-else-if="overviewHasContent" type="button" @click="editOverview">手动纠正</button>
        <button
          v-if="overview?.status === 'failed'"
          type="button"
          :disabled="overviewRetrying"
          @click="retryOverview"
        >{{ overviewRetrying ? "正在整理…" : "重新整理" }}</button>
      </footer>
    </aside>

    <aside v-if="generationRecordsOpen" class="rp-drawer" aria-label="生成记录" :aria-busy="generationRecordsLoading">
      <header>
        <div>
          <strong>生成记录</strong>
          <span>技术中断后尚未采用的内容</span>
        </div>
        <button type="button" aria-label="关闭生成记录" @click="generationRecordsOpen = false">×</button>
      </header>
      <div class="rp-generation-records">
        <p v-if="generationRecordsLoading" class="rp-overview-empty" role="status">正在载入…</p>
        <article v-for="record in generationRecords" :key="record.id">
          <small>未完整 · {{ new Date(record.created_at).toLocaleString() }}</small>
          <p>{{ record.visible_text }}</p>
          <span>{{ generationRecordError(record).message }}</span>
          <button type="button" @click="keepGenerationRecord(record)">保留这段</button>
        </article>
        <p
          v-if="!generationRecordsLoading && !generationRecords.length"
          class="rp-overview-empty"
        >没有待处理的生成记录。</p>
      </div>
    </aside>

    <aside v-if="treeOpen" class="rp-drawer" aria-label="分支历史" :aria-busy="treeLoading">
      <header>
        <div><strong>分支历史</strong><span>蓝色是当前正在发生的发展</span></div>
        <button type="button" aria-label="关闭分支历史" @click="treeOpen = false">×</button>
      </header>
      <p v-if="treeLoading" class="rp-overview-empty" role="status">正在载入分支历史…</p>
      <p v-else-if="treeLoadError" class="rp-overview-empty" role="alert">
        {{ treeLoadError }}
        <button type="button" @click="openTree">重新载入</button>
      </p>
      <div v-else-if="treeBranchPoints.length" class="rp-tree">
        <section
          v-for="point in visibleTreeBranchPoints"
          :key="point.parent_node_id || point.label"
          class="rp-tree-branch"
        >
          <h3>{{ point.label }}</h3>
          <button
            v-for="variant in point.variants"
            :key="variant.node_id"
            type="button"
            :class="{ active: variant.selected }"
            :aria-pressed="variant.selected"
            :disabled="isGenerating || awaitingContinue"
            @click="selectBranch(variant.node_id); treeOpen = false"
          >
            <span>{{ variant.selected ? "当前" : "发展" }}</span>
            {{ variant.excerpt }}
            <small v-if="variant.continuation_count">
              继续了 {{ variant.continuation_count }} 段
            </small>
          </button>
        </section>
        <button
          v-if="treeBranchPoints.length > 1"
          class="rp-tree-expand"
          type="button"
          @click="treeOlderExpanded = !treeOlderExpanded"
        >
          {{ treeOlderExpanded
            ? "收起更早分岔"
            : `展开更早分岔（${treeBranchPoints.length - 1}）` }}
        </button>
      </div>
      <p v-else class="rp-overview-empty">这段旅程还没有产生不同分支。</p>
    </aside>

    <aside
      v-if="sourceInfoOpen"
      ref="sourceDrawer"
      class="rp-drawer"
      aria-label="作品资料"
      :aria-busy="sourceLoading"
      tabindex="-1"
      @keydown.esc="closeSourceInfo"
    >
      <header>
        <div>
          <strong>作品资料</strong>
          <span v-if="journey.source">
            {{ journey.source.source_title }} · 资料版本 {{ journey.source.version_number }}
          </span>
        </div>
        <button type="button" aria-label="关闭作品资料" @click="closeSourceInfo">×</button>
      </header>
      <p v-if="sourceError" class="rp-overview-empty" role="alert">
        {{ sourceError }} <button type="button" @click="openSourceInfo">重新载入</button>
      </p>
      <p v-else-if="sourceLoading && !sourceInfo" class="rp-overview-empty" role="status">
        正在载入作品资料…
      </p>
      <div v-else-if="sourceInfo" class="rp-source-drawer-content">
        <section class="rp-source-current">
          <h3>当前进度</h3>
          <p>{{ sourceInfo.source.progress_label }}</p>
          <small v-if="sourceInfo.source.player_label">玩家身份：{{ sourceInfo.source.player_label }}</small>
        </section>
        <section v-if="sourceInfo.last_used.length">
          <h3>本轮引用了什么</h3>
          <ul>
            <li v-for="(item, index) in sourceInfo.last_used" :key="`${item.label}-${index}`">
              <strong>{{ item.label }}</strong><span>{{ item.reason }}</span>
            </li>
          </ul>
        </section>
        <section v-if="sourceRevision?.anchors?.length" class="rp-source-progress-update">
          <h3>推进剧情进度</h3>
          <p>已开始的旅程只能保持或向后推进；回到更早剧情需要新建旅程。</p>
          <select v-model="sourceCurrentAnchorKey" aria-label="新的剧情进度">
            <option value="" disabled>选择章节内的剧情点</option>
            <option v-for="anchor in sourceRevision.anchors" :key="anchor.anchor_key" :value="anchor.anchor_key">
              {{ anchor.chapter_title }} · {{ anchor.label }}
            </option>
          </select>
          <button
            type="button"
            :disabled="sourceLoading || isGenerating || awaitingContinue || !sourceCurrentAnchorKey"
            @click="updateJourneySource(sourceRevision, sourceCurrentAnchorKey)"
          >保存剧情进度</button>
        </section>
        <section v-if="sourceUpgrade" class="rp-source-upgrade">
          <h3>可用新资料版本 {{ sourceUpgrade.version_number }}</h3>
          <p>旧版本和当前旅程不受影响。选择新版本中的剧情点后才会升级。</p>
          <select v-model="sourceUpgradeAnchorKey" aria-label="新版本剧情进度">
            <option value="" disabled>选择新版本剧情点</option>
            <option v-for="anchor in sourceUpgrade.anchors" :key="anchor.anchor_key" :value="anchor.anchor_key">
              {{ anchor.chapter_title }} · {{ anchor.label }}
            </option>
          </select>
          <button
            type="button"
            :disabled="sourceLoading || isGenerating || awaitingContinue || !sourceUpgradeAnchorKey"
            @click="updateJourneySource(sourceUpgrade, sourceUpgradeAnchorKey)"
          >升级并确认进度</button>
        </section>
        <section>
          <h3>固定或忽略对象</h3>
          <p>固定项会优先进入每轮资料；忽略项不会被关系扩展重新带回。</p>
          <div class="rp-source-object-list">
            <article v-for="item in sourceObjects" :key="item.reference_key">
              <div><strong>{{ item.label }}</strong><small>{{ sourceEntityTypeLabel(item.entity_type) }}</small></div>
              <p v-if="item.summary">{{ item.summary }}</p>
              <div>
                <button
                  type="button"
                  :class="{ active: isPinned(item.reference_key) }"
                  :disabled="sourceLoading || isGenerating || awaitingContinue"
                  @click="updateSourceReference('pin', item.reference_key)"
                >{{ isPinned(item.reference_key) ? "已固定" : "固定" }}</button>
                <button
                  type="button"
                  :class="{ active: isExcluded(item.reference_key) }"
                  :disabled="sourceLoading || isGenerating || awaitingContinue"
                  @click="updateSourceReference('exclude', item.reference_key)"
                >{{ isExcluded(item.reference_key) ? "已忽略" : "忽略" }}</button>
              </div>
            </article>
          </div>
          <button
            v-if="sourceInfo.pinned.length || sourceInfo.excluded.length"
            type="button"
            :disabled="sourceLoading || isGenerating || awaitingContinue"
            @click="updateSourceReference('reset')"
          >恢复自动引用</button>
        </section>
        <p v-if="isGenerating || awaitingContinue" class="rp-source-lock-note">
          请先等当前回应完成或处理未写完的内容，再修改作品资料。
        </p>
      </div>
    </aside>

    <aside v-if="dataInfoOpen" class="rp-drawer" aria-label="内容与数据">
      <header>
        <div><strong>内容与数据</strong><span>关于这段私人旅程</span></div>
        <button type="button" aria-label="关闭内容与数据" @click="dataInfoOpen = false">×</button>
      </header>
      <div class="rp-data-info">
        <p>你的开场、输入、当前旅程上下文和自动回顾会发送给你在账户设置中选择的模型服务，用来生成和维持故事连续性。</p>
        <p>旅程内容、当前分支和回顾会保存在你的账户下，不会进入作者项目，也不会写回作品的世界对象、大纲或正文。</p>
        <p>未选中的重新生成结果仍作为私人分支保存；模型只会读取当前选中的发展。导出和永久删除由你主动操作。</p>
      </div>
    </aside>
  </main>
  <main v-else class="rp-load-failure">
    <h1>旅程暂时无法打开</h1>
    <p role="alert">{{ props.loadError || "旅程不存在，或当前账号无法访问。" }}</p>
    <button type="button" @click="getRouter().navigate('journeys')">返回旅程列表</button>
  </main>
</template>
