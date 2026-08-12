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
  async function doSearch(query, { routeSignature = "", formState } = {}) {
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

    const isCurrent = () => (
      controller === searchController
      && !searchController.signal.aborted
      && current === generation
      && projectId === getAppState()?.currentProjectId
    )

    try {
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
        searchError.value = { reason: "请完善可见性条件", validation: true }
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

  return { searching, searchError, doSearch, loadMore, cancelActiveSearch }
}
