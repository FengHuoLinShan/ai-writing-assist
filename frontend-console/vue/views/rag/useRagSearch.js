/**
 * 检索执行 composable — 对应 vanilla ragView._doSearch。
 * abort + generation + projectId 三重门禁；结果写入 ragSearchSession
 * （跨 island 重挂载存活）；scope 销毁时取消在途请求。
 */
import { getCurrentScope, onScopeDispose, ref } from "vue"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import { buildEvidencePayload, normalizeEvidenceHit } from "./logic/searchPayload.js"
import { RAG_RESULT_PAGE_SIZE } from "./logic/routeState.js"
import { ragSearchSession } from "./ragSearchSession.js"

export function useRagSearch() {
  const searching = ref(false)
  const searchStage = ref("")
  /** @type {import("vue").Ref<{reason: string}|{reason: Error, searchKind: string}|null>} */
  const searchError = ref(null)
  let controller = null
  let generation = 0

  function cancelActiveSearch() {
    if (controller) controller.abort()
    controller = null
  }

  /**
   * @param {string} query 检索词
   * @param {{routeSignature?: string, formState: object}} options
   *   formState 为当前表单状态（buildEvidencePayload 的输入，query 字段会被覆盖）
   */
  async function doSearch(query, { routeSignature = "", formState, scenes = [] } = {}) {
    const state = getAppState()
    if (!query) return
    cancelActiveSearch()
    const searchController = new AbortController()
    controller = searchController
    const current = ++generation
    const projectId = state?.currentProjectId
    ragSearchSession.query = query
    searching.value = true
    searchError.value = null
    searchStage.value = formState?.searchKind === "literal" ? "正在查找正文词句…" : "正在查找小说资料…"

    const isCurrent = () => (
      controller === searchController
      && !searchController.signal.aborted
      && current === generation
      && projectId === getAppState()?.currentProjectId
    )

    if (formState?.searchKind !== 'literal') {
      void Promise.resolve().then(() => getApi().rag.metrics()).then(value => {
        if (!isCurrent() || !searching.value) return
        const runtime = value?.embedding_runtime
        if (value.embedding_provider === 'bge_onnx' && runtime && !runtime.healthy) searchStage.value = '正在准备检索服务，首次使用可能需要较长时间；可切换字面搜索。'
      }).catch(() => {})
    }
    try {
      const cutoffScene = scenes.find(scene => scene.id === formState?.cutoffSceneId)
      if (["reader", "character"].includes(formState?.visibilityMode) && cutoffScene && !(cutoffScene.chapter_ids || []).map(Number).includes(Number(formState.cutoffChapter))) {
        const message = "截止章节不属于所选场景，请调整截止章节或清除场景选择。"
        getToast()(message, "warning")
        searchError.value = { reason: message, validation: true }
        ragSearchSession.hits = []
        ragSearchSession.total = 0
        return
      }
      const writingLocation = state?.viewStates?.writing
      const currentSceneId = writingLocation?.projectId === projectId
        ? (writingLocation.currentSceneId || null)
        : null
      const { payload, error } = buildEvidencePayload({
        ...formState,
        query,
        currentSceneId,
      }, projectId)
      if (!payload) {
        getToast()(error, "warning")
        ragSearchSession.hits = []
        ragSearchSession.total = 0
        ragSearchSession.resultMeta = null
        searchError.value = { reason: error || "请完善查找条件", validation: true }
        return
      }
      ragSearchSession.lastSearchPayload = payload
      const options = { signal: searchController.signal }
      let data
      if (payload.search_kind === "literal" && getApi().context?.grepEvidence) {
        const {
          search_kind: _kind,
          query: pattern,
          scopes: _scopes,
          include_pending_objects: _pending,
          top_k: limit,
          ...rest
        } = payload
        data = await getApi().context.grepEvidence({
          ...rest,
          pattern,
          limit,
          group_by_chapter: true,
        }, options)
      } else if (getApi().context?.searchEvidence) {
        const { search_kind: _kind, ...request } = payload
        data = await getApi().context.searchEvidence(request, options)
      } else {
        throw new Error("证据检索接口不可用，已停止使用未校验的旧索引结果")
      }
      if (!isCurrent()) return
      const rawHits = Array.isArray(data?.hits)
        ? data.hits
        : (Array.isArray(data?.chunks) ? data.chunks : (Array.isArray(data) ? data : []))
      ragSearchSession.hits = rawHits.map((item) => normalizeEvidenceHit(item))
      ragSearchSession.visibleCount = Math.min(RAG_RESULT_PAGE_SIZE, ragSearchSession.hits.length)
      ragSearchSession.total = Number.isFinite(Number(data?.total))
        ? Math.max(ragSearchSession.hits.length, Number(data.total))
        : ragSearchSession.hits.length
      ragSearchSession.resultMeta = data || {}
      ragSearchSession.query = query
      if (routeSignature) ragSearchSession.lastExecutedRouteSignature = routeSignature
    } catch (err) {
      if (!isCurrent() || err?.name === "AbortError") return
      searchError.value = { reason: err, searchKind: ragSearchSession.lastSearchPayload?.search_kind || "smart" }
    } finally {
      if (controller === searchController && current === generation) {
        controller = null
        searching.value = false
      }
    }
  }

  /** 渐进加载：每页 +20（对应 _loadMoreSearchResults）。 */
  function loadMore() {
    ragSearchSession.visibleCount = Math.min(
      ragSearchSession.hits.length,
      ragSearchSession.visibleCount + RAG_RESULT_PAGE_SIZE,
    )
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      cancelActiveSearch()
      generation += 1
    })
  }

  return { searching, searchStage, searchError, doSearch, loadMore, cancelActiveSearch }
}
