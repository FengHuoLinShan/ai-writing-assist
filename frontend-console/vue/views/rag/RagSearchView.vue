<script setup>
import { computed, onMounted, reactive, watch } from "vue"
import RagSearchPanel from "./components/RagSearchPanel.vue"
import RagResultList from "./components/RagResultList.vue"
import RagEvidenceDrawer from "./components/RagEvidenceDrawer.vue"
import { getAppState, getRouter, getToast } from "../../bridge/index.js"
import { buildRouteQuery, parseRouteQuery } from "./logic/routeState.js"
import { buildEvidencePayload, normalizeChapterRange } from "./logic/searchPayload.js"
import { useRagSearch } from "./useRagSearch.js"
import { useEvidenceDrawer } from "./useEvidenceDrawer.js"
import { ragSearchSession, resetRagSearchSession } from "./ragSearchSession.js"

/**
 * 检索子视图编排 — 表单状态、提交、路由恢复（对应 vanilla 的
 * _submitSearchFromForm / _restoreSearchFromRoute / _retrySearch）。
 */
const props = defineProps({
  projectId: { type: String, default: null },
  characters: { type: Array, default: () => [] },
  scenes: { type: Array, default: () => [] },
})

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
  const route = buildRouteQuery(query, payload)
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
    @submit="submit"
  />
  <RagResultList
    :searching="searching"
    :search-error="searchError"
    @load-more="loadMore"
    @open-hit="(index) => drawer.openHit(session.hits[index])"
    @open-scene="openScene"
    @retry="retry()"
    @retry-literal="retry({ literal: true })"
  >
    <template #drawer>
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
  </RagResultList>
</template>
