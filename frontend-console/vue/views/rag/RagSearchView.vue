<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import RagSearchPanel from "./components/RagSearchPanel.vue"
import RagResultList from "./components/RagResultList.vue"
import RagEvidenceDrawer from "./components/RagEvidenceDrawer.vue"
import { getApi, getAppState, getRouteQuery, getRouter, getToast } from "../../bridge/index.js"
import { buildRouteQuery, parseRouteQuery } from "./logic/routeState.js"
import { buildEvidencePayload, normalizeChapterRange } from "./logic/searchPayload.js"
import { useRagSearch } from "./useRagSearch.js"
import { useEvidenceDrawer } from "./useEvidenceDrawer.js"
import { ragSearchSession, resetRagSearchSession, scopeRagSessionToProject } from "./ragSearchSession.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"

/**
 * 检索子视图编排 — 表单状态、提交、路由恢复（对应 vanilla 的
 * _submitSearchFromForm / _restoreSearchFromRoute / _retrySearch）。
 */
const props = defineProps({
  projectId: { type: String, default: null },
  characters: { type: Array, default: () => [] },
  scenes: { type: Array, default: () => [] },
  embedded: { type: Boolean, default: false },
})

scopeRagSessionToProject(props.projectId)

// 表单初值来自路由状态（vanilla 以 routeState 渲染表单）
const initialRouteQuery = getRouter().getCurrentQuery?.()
const initialRoute = parseRouteQuery(initialRouteQuery)
const routeChapterValue = (query, name, fallback) => query?.get(name) ?? fallback ?? ""
const session = ragSearchSession
const routeFormState = {
  query: initialRoute.query,
  searchKind: initialRoute.searchKind,
  contentMode: initialRoute.contentMode,
  visibilityMode: initialRoute.visibilityMode,
  chapterFrom: routeChapterValue(initialRouteQuery, "chapter_from", initialRoute.chapterFrom),
  chapterTo: routeChapterValue(initialRouteQuery, "chapter_to", initialRoute.chapterTo),
  cutoffChapter: initialRoute.cutoffChapter ?? "",
  cutoffSceneId: initialRoute.cutoffSceneId,
  cutoffOffset: initialRoute.cutoffOffset ?? "",
  characterId: initialRoute.characterId,
  scopes: [...initialRoute.scopes],
  includePending: initialRoute.includePending,
}
const restoredFormState = session.formRouteSignature === initialRoute.signature
  ? session.formState
  : null
let currentFormRouteSignature = initialRoute.signature
const form = reactive({
  ...routeFormState,
  ...(restoredFormState || {}),
  scopes: [...(restoredFormState?.scopes || routeFormState.scopes)],
})

watch(form, (value) => {
  session.formState = { ...value, scopes: [...value.scopes] }
  session.formRouteSignature = currentFormRouteSignature
}, { deep: true, immediate: true })

const { searching, searchError, doSearch, loadMore } = useRagSearch()
const drawer = useEvidenceDrawer()
const chapterRangeError = computed(() => (
  normalizeChapterRange(form.chapterFrom, form.chapterTo).error || ""
))
const askingWorld = ref(false)
const savingWorldAnswer = ref(false)
const askWorldResult = ref(null)
const askWorldError = ref("")
const askWorldNotice = ref("")
const answerSaved = ref(false)
const openedCitation = ref(null)
const openingCitationKey = ref("")
let askController = null
let citationRequest = 0
let disposed = false

const canSaveWorldAnswer = computed(() => (
  askWorldResult.value
  && !askWorldResult.value.no_answer
  && askWorldResult.value.claims?.length
  && askWorldResult.value.citations?.length
))

function resetAskWorld() {
  askController?.abort()
  askController = null
  citationRequest += 1
  askingWorld.value = false
  savingWorldAnswer.value = false
  askWorldResult.value = null
  askWorldError.value = ""
  askWorldNotice.value = ""
  answerSaved.value = false
  openedCitation.value = null
  openingCitationKey.value = ""
}

watch(() => props.projectId, resetAskWorld)
onBeforeUnmount(() => {
  disposed = true
  citationRequest += 1
  askController?.abort()
  askController = null
})

async function askWorld() {
  if (askingWorld.value) return
  const question = form.query.trim()
  if (!question) {
    getToast()("请先输入想查证的问题", "warning")
    return
  }
  if (!props.projectId) {
    getToast()("请先选择项目", "warning")
    return
  }
  askController?.abort()
  const controller = new AbortController()
  const projectId = props.projectId
  askController = controller
  askingWorld.value = true
  askWorldResult.value = null
  askWorldError.value = ""
  askWorldNotice.value = ""
  answerSaved.value = false
  openedCitation.value = null
  try {
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "world.ask",
      task: question,
      scope: "full",
      user_note: question,
      include_pending_objects: false,
      budget_tokens: 8000,
    })
    const result = await getApi().generate.askWorld(
      { novel_id: projectId, question, context_confirmation_id: confirmation.id },
      { signal: controller.signal },
    )
    if (
      disposed
      || controller.signal.aborted
      || controller !== askController
      || projectId !== props.projectId
    ) return
    askWorldResult.value = result
  } catch (error) {
    if (disposed || controller !== askController || projectId !== props.projectId) return
    if (error?.message === "已取消 AI 参考资料确认") return
    if (controller.signal.aborted) {
      askWorldNotice.value = "已停止后续问答；远端请求可能仍在结束。"
    } else {
      askWorldError.value = error?.status === 409
        ? "回答期间来源发生了变化，请重新提问。"
        : "这次没能完成问答，请稍后重试。"
    }
  } finally {
    if (!disposed && controller === askController) {
      askController = null
      askingWorld.value = false
    }
  }
}

function stopAskWorld() {
  if (!askController) return
  askWorldNotice.value = "已停止后续问答；远端请求可能仍在结束。"
  const controller = askController
  askController = null
  askingWorld.value = false
  controller.abort()
}

function claimCitations(claim) {
  const keys = new Set(claim?.citation_keys || [])
  return (askWorldResult.value?.citations || []).filter((item) => (
    keys.has(item.citation_key)
  ))
}

async function openWorldCitation(citation) {
  const projectId = props.projectId
  if (!projectId || disposed) return
  const requestId = ++citationRequest
  openingCitationKey.value = citation.citation_key
  try {
    const result = await getApi().generate.openAskWorldCitation({
      novel_id: projectId,
      citation,
    })
    if (disposed || requestId !== citationRequest || projectId !== props.projectId) return
    openedCitation.value = result
    if (result.status !== "current") {
      getToast()(
        result.status === "stale"
          ? "来源已经变化；下面显示的是当前内容，请重新提问后再引用。"
          : "这个来源目前无法打开。",
        "warning",
      )
    }
  } catch {
    if (!disposed && requestId === citationRequest && projectId === props.projectId) {
      getToast()("来源打开失败，请稍后重试", "error")
    }
  } finally {
    if (!disposed && requestId === citationRequest) openingCitationKey.value = ""
  }
}

function closeOpenedCitation() {
  citationRequest += 1
  openingCitationKey.value = ""
  openedCitation.value = null
}

const openedCitationHref = computed(() => {
  if (
    !props.projectId
    || openedCitation.value?.status !== "current"
    || !openedCitation.value.page_id
  ) return ""
  const query = new URLSearchParams()
  query.set("page_id", openedCitation.value.page_id)
  return `#workbench/${encodeURIComponent(props.projectId)}/world/bible?${query.toString()}`
})

async function saveWorldAnswer() {
  const result = askWorldResult.value
  const projectId = props.projectId
  if (!canSaveWorldAnswer.value || !projectId || savingWorldAnswer.value || disposed) return
  savingWorldAnswer.value = true
  try {
    await getApi().generate.saveAskWorldSuggestion({
      novel_id: projectId,
      question: result.question,
      answer: result.answer,
      claims: result.claims,
      uncertainty: result.uncertainty,
      citations: result.citations,
      response_hash: result.response_hash,
    })
    if (disposed || projectId !== props.projectId) return
    answerSaved.value = true
    getToast()("已保存为待处理世界笔记建议，不会直接改写正式设定。", "success")
  } catch (error) {
    if (disposed || projectId !== props.projectId) return
    getToast()(
      error?.status === 409
        ? "来源已经变化，请重新提问后再保存。"
        : "保存失败，回答仍保留在当前页面。",
      error?.status === 409 ? "warning" : "error",
    )
  } finally {
    if (!disposed && projectId === props.projectId) savingWorldAnswer.value = false
  }
}

function openSavedSuggestions() {
  getRouter().navigate("world", "bible", true, new URLSearchParams("open=suggestions"))
}

function routeToFormState(routeState, query) {
  return {
    searchKind: routeState.searchKind,
    contentMode: routeState.contentMode,
    visibilityMode: routeState.visibilityMode,
    chapterFrom: routeChapterValue(query, "chapter_from", routeState.chapterFrom),
    chapterTo: routeChapterValue(query, "chapter_to", routeState.chapterTo),
    cutoffChapter: routeState.cutoffChapter,
    cutoffSceneId: routeState.cutoffSceneId,
    cutoffOffset: routeState.cutoffOffset,
    characterId: routeState.characterId,
    scopes: routeState.scopes,
    includePending: routeState.includePending,
  }
}

/** 对应 _submitSearchFromForm：提交时就地更新 URL 和检索结果，不重挂搜索页。 */
async function submit() {
  const query = form.query.trim()
  if (!query) return
  const { payload, error } = buildEvidencePayload({ ...form, query }, props.projectId)
  if (!payload) {
    getToast()(error, "warning")
    return
  }
  const searchRoute = buildRouteQuery(query, payload)
  const route = props.embedded
    ? getRouteQuery()
    : new URLSearchParams()
  const searchKeys = [
    "q", "kind", "content_mode", "visibility", "scope", "chapter_from", "chapter_to",
    "cutoff_chapter", "cutoff_scene_id", "cutoff_offset", "character_id", "include_pending",
  ]
  for (const key of searchKeys) route.delete(key)
  for (const [key, value] of searchRoute) route.append(key, value)
  const signature = route.toString()
  const state = getAppState()
  if (state) state.searchQuery = query
  const router = getRouter()
  if (router.getCurrentQuery?.().toString() !== signature) {
    if (router.commitCurrentQuery?.(route, "push") !== true) {
      await router.navigate("rag", "search", true, route)
      return
    }
  }
  currentFormRouteSignature = signature
  session.formRouteSignature = signature
  await doSearch(query, { routeSignature: signature, formState: form })
}

/** 对应 _retrySearch：保留表单重试；literal 变体切换为字面搜索。 */
async function retry({ literal = false } = {}) {
  if (literal) {
    form.searchKind = "literal"
    form.scopes = ["manuscript"]
  }
  if (!form.query.trim() && session.lastSearchPayload?.query) {
    form.query = session.lastSearchPayload.query
  }
  await submit()
}

function openScene(ref) {
  if (ref?.target_id) getRouter().navigate("scene", ref.target_id)
}

// 对应 vanilla onRendered 的 _restoreSearchFromRoute
onMounted(() => {
  const routeQuery = getRouter().getCurrentQuery?.()
  const routeState = parseRouteQuery(routeQuery)
  if (!routeState.query) {
    if (!restoredFormState) resetRagSearchSession()
    const state = getAppState()
    if (state) state.searchQuery = ""
    return
  }
  if (routeState.signature === session.lastExecutedRouteSignature) return
  if (normalizeChapterRange(
    routeChapterValue(routeQuery, "chapter_from", routeState.chapterFrom),
    routeChapterValue(routeQuery, "chapter_to", routeState.chapterTo),
  ).error) {
    getToast()(chapterRangeError.value, "warning")
    return
  }
  const state = getAppState()
  if (state) state.searchQuery = routeState.query
  void doSearch(routeState.query, {
    routeSignature: routeState.signature,
    formState: routeToFormState(routeState, routeQuery),
  })
})
</script>

<template>
  <RagSearchPanel
    :form="form"
    :characters="characters"
    :scenes="scenes"
    :chapter-range-error="chapterRangeError"
    :ask-world-pending="askingWorld"
    :search-pending="searching"
    @submit="submit"
    @ask-world="askWorld"
  />
  <section
    v-if="askingWorld || askWorldResult || askWorldError || askWorldNotice"
    class="card ask-world-card"
    aria-live="polite"
  >
    <div class="ask-world-card__header">
      <div>
        <div class="card-title">问世界</div>
        <p>只根据当前项目可回读的正式资料回答。</p>
      </div>
      <button v-if="askingWorld" class="btn btn-sm" data-action="stop-ask-world" @click="stopAskWorld">停止问答</button>
    </div>
    <p v-if="askingWorld" class="ask-world-card__status">正在查找并回读来源…</p>
    <p v-if="askWorldNotice" class="ask-world-card__notice">{{ askWorldNotice }}</p>
    <p v-if="askWorldError" class="rag-error-text" role="alert">{{ askWorldError }}</p>

    <template v-if="askWorldResult">
      <p class="ask-world-answer">{{ askWorldResult.answer }}</p>
      <div v-if="askWorldResult.claims?.length" class="ask-world-claims">
        <article v-for="(claim, index) in askWorldResult.claims" :key="index" class="ask-world-claim">
          <p>{{ claim.text }}</p>
          <div class="ask-world-citations">
            <button
              v-for="citation in claimCitations(claim)"
              :key="citation.citation_key"
              class="btn btn-sm"
              data-action="open-ask-world-citation"
              :disabled="openingCitationKey === citation.citation_key"
              @click="openWorldCitation(citation)"
            >{{ openingCitationKey === citation.citation_key ? "正在打开…" : `查看来源：${citation.title}` }}</button>
          </div>
        </article>
      </div>
      <p v-if="askWorldResult.uncertainty" class="ask-world-uncertainty"><strong>仍需留意：</strong>{{ askWorldResult.uncertainty }}</p>
      <details class="ask-world-trace">
        <summary>这次查了哪些资料</summary>
        <p v-if="askWorldResult.evidence_trace?.included_titles?.length">已回读：{{ askWorldResult.evidence_trace.included_titles.join("、") }}</p>
        <p v-if="askWorldResult.evidence_trace?.excluded_count">另有 {{ askWorldResult.evidence_trace.excluded_count }} 个候选因重复、版本或篇幅限制未纳入。</p>
        <p v-if="askWorldResult.evidence_trace?.truncated_titles?.length">篇幅内缩短：{{ askWorldResult.evidence_trace.truncated_titles.join("、") }}</p>
        <p v-for="warning in askWorldResult.evidence_trace?.warnings || []" :key="warning">{{ warning }}</p>
        <p v-if="askWorldResult.evidence_trace?.not_run?.length">本次未查：{{ askWorldResult.evidence_trace.not_run.join("、") }}</p>
      </details>
      <div v-if="canSaveWorldAnswer" class="ask-world-actions">
        <button
          v-if="!answerSaved"
          class="btn btn-primary"
          data-action="save-ask-world-answer"
          :disabled="savingWorldAnswer"
          @click="saveWorldAnswer"
        >{{ savingWorldAnswer ? "正在保存…" : "保存为待处理建议" }}</button>
        <template v-else>
          <span>已进入待处理，不会直接改写正式设定。</span>
          <button class="btn btn-sm" data-action="open-ask-world-suggestions" @click="openSavedSuggestions">去查看</button>
        </template>
      </div>
    </template>
  </section>

  <aside v-if="openedCitation" class="card ask-world-source" aria-live="polite">
    <div class="ask-world-source__header">
      <div>
        <strong>{{ openedCitation.title }}</strong>
        <span v-if="openedCitation.status !== 'current'">{{ openedCitation.status === "stale" ? "来源已变化" : "来源不可用" }}</span>
      </div>
      <button class="btn btn-sm" data-action="close-ask-world-citation" @click="closeOpenedCitation">关闭</button>
    </div>
    <p v-for="warning in openedCitation.warnings || []" :key="warning" class="ask-world-uncertainty">{{ warning }}</p>
    <div v-if="openedCitation.text" class="ask-world-source__text">{{ openedCitation.text }}</div>
    <a
      v-if="openedCitationHref"
      class="btn btn-sm"
      data-action="open-ask-world-page"
      :href="openedCitationHref"
      target="_blank"
      rel="noopener"
    >在新标签页打开世界笔记</a>
  </aside>
  <RagResultList
    :searching="searching"
    :search-error="searchError"
    @load-more="loadMore"
    @open-hit="(index) => drawer.openHit(session.hits[index])"
    @open-scene="openScene"
    @retry="retry()"
    @retry-literal="retry({ literal: true })"
  />
  <RagEvidenceDrawer
    :open="drawer.open.value"
    :loading="drawer.loading.value"
    :content="drawer.content.value"
    @close="drawer.close"
    @trace="drawer.traceRef"
    @navigate-object="drawer.navigateObjectRef"
    @navigate-scene="drawer.navigateSceneRef"
    @navigate-chapter="drawer.navigateChapterRef"
  />
</template>
