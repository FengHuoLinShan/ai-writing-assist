/**
 * 证据抽屉 composable — 对应 vanilla ragView 的 _openHit / _traceDrawerRef /
 * _navigateObjectRef / _navigateChapterRef。
 * 门禁 = abort + generation + projectId（drawer 为稳定组件，不再需要
 * vanilla 的 isConnected 同节点检查）；scope 销毁时取消在途请求。
 */
import { getCurrentScope, onScopeDispose, ref } from "vue"
import { getApi, getAppState, getRouter } from "../../bridge/index.js"
import { ragSearchSession } from "./ragSearchSession.js"

export function useEvidenceDrawer() {
  const open = ref(false)
  /** @type {import("vue").Ref<"" | "读取中" | "追踪中">} */
  const loading = ref("")
  /** @type {import("vue").Ref<object|null>} 抽屉内容（按 type 区分渲染） */
  const content = ref(null)
  let controller = null
  let generation = 0

  function beginRequest() {
    if (controller) controller.abort()
    controller = new AbortController()
    generation += 1
    return { controller, generation, projectId: getAppState()?.currentProjectId }
  }

  function isCurrent(request) {
    return Boolean(
      controller === request.controller
      && !request.controller.signal.aborted
      && request.generation === generation
      && request.projectId === getAppState()?.currentProjectId
    )
  }

  function visibilityFromLastSearch() {
    return ragSearchSession.lastSearchPayload?.visibility || { mode: "author" }
  }

  function contentModeFromLastSearch() {
    return ragSearchSession.lastSearchPayload?.content_mode || "canonical"
  }

  function close() {
    if (controller) controller.abort()
    controller = null
    generation += 1
    open.value = false
    content.value = null
    loading.value = ""
  }

  /** 打开结果卡（source_ref → 原文；target_ref → 对象）。 */
  async function openHit(hit) {
    if (!hit) return
    const request = beginRequest()
    open.value = true
    loading.value = "读取中"
    content.value = null
    try {
      if (hit.source_ref) {
        const result = await getApi().context.readEvidence({
          novel_id: request.projectId,
          content_mode: hit.source_ref.content_mode,
          visibility: visibilityFromLastSearch(),
          source_ref: hit.source_ref,
          before: 3,
          after: 3,
        }, { signal: request.controller.signal })
        if (!isCurrent(request)) return
        ragSearchSession.drawerRefs = [...(result.scene_refs || []), ...(result.object_refs || [])]
        const text = String(result.text || "")
        const start = Math.max(0, Number(result.highlight_start) || 0)
        const end = Math.max(start, Number(result.highlight_end) || start)
        content.value = {
          type: "chapter",
          title: result.title || "原文",
          chapterIndex: result.source_ref?.chapter_index || "-",
          versionNumber: result.source_ref?.version_number || "-",
          before: text.slice(0, start),
          mark: text.slice(start, end),
          after: text.slice(end),
          warnings: result.warnings || [],
        }
      } else if (hit.target_ref) {
        const result = await getApi().context.inspectEvidence({
          novel_id: request.projectId,
          content_mode: contentModeFromLastSearch(),
          visibility: visibilityFromLastSearch(),
          target_ref: hit.target_ref,
        }, { signal: request.controller.signal })
        if (!isCurrent(request)) return
        ragSearchSession.drawerRefs = [{ ...hit.target_ref, target_name: hit.title || "" }]
        content.value = {
          type: "object",
          title: hit.title,
          item: result.item || {},
          evidenceCount: result.evidence_count || 0,
          isWorldObject: isWorldObjectRef(hit.target_ref),
          warnings: result.warnings || [],
        }
      }
    } catch (err) {
      if (!isCurrent(request) || err?.name === "AbortError") return
      content.value = { type: "error", message: "证据读取失败，请关闭后再次打开这条结果。" }
    } finally {
      if (controller === request.controller) {
        controller = null
        loading.value = ""
      }
    }
  }

  /** 追踪对象原文证据。 */
  async function traceRef(index) {
    const refItem = ragSearchSession.drawerRefs[Number(index)]
    if (!refItem) return
    const request = beginRequest()
    open.value = true
    loading.value = "追踪中"
    content.value = null
    try {
      const result = await getApi().context.traceEvidence({
        novel_id: request.projectId,
        content_mode: contentModeFromLastSearch(),
        visibility: visibilityFromLastSearch(),
        target_ref: refItem,
        claim_path: refItem.target_path || "",
      }, { signal: request.controller.signal })
      if (!isCurrent(request)) return
      const label = refItem.target_name || refItem.name || `关联对象 ${Number(index) + 1}`
      content.value = {
        type: "trace",
        title: `${label}的对象证据`,
        links: result.links || [],
        warnings: result.warnings || [],
      }
    } catch (err) {
      if (!isCurrent(request) || err?.name === "AbortError") return
      content.value = { type: "error", message: "原文证据追踪失败，请关闭后再试一次。" }
    } finally {
      if (controller === request.controller) {
        controller = null
        loading.value = ""
      }
    }
  }

  /** 跳转世界对象页（必要时先 inspect 取名称）。 */
  async function navigateObjectRef(index) {
    const refItem = ragSearchSession.drawerRefs[Number(index)]
    if (!refItem?.target_id) return
    const request = beginRequest()
    let label = refItem.target_name || refItem.name || ""
    if (!label && getApi().context?.inspectEvidence) {
      try {
        const result = await getApi().context.inspectEvidence({
          novel_id: request.projectId,
          content_mode: contentModeFromLastSearch(),
          visibility: visibilityFromLastSearch(),
          target_ref: refItem,
        }, { signal: request.controller.signal })
        if (!isCurrent(request)) return
        label = result.item?.name || ""
      } catch (err) {
        if (!isCurrent(request) || err?.name === "AbortError") return
        // 检查接口不可用时仍可凭 ID 跳转
      }
    }
    if (!isCurrent(request)) return
    const query = new URLSearchParams()
    query.set("q", label || refItem.target_id)
    getRouter().navigate("world", "objects", true, query)
    if (controller === request.controller) controller = null
  }

  /** 跳转 Scene（outline/scenes 兼容路由）。 */
  function navigateSceneRef(index) {
    const refItem = ragSearchSession.drawerRefs[Number(index)]
    if (refItem?.target_id) getRouter().navigate("scene", refItem.target_id)
  }

  /** 跳转写作台对应章节（写 viewStates.writing 后导航）。 */
  function navigateChapterRef(value) {
    const chapterIndex = Number(value)
    if (!Number.isInteger(chapterIndex) || chapterIndex < 1) return
    const state = getAppState()
    if (!state) return
    state.viewStates.writing = {
      ...(state.viewStates.writing || {}),
      projectId: state.currentProjectId,
      currentChapter: chapterIndex,
      currentDraftId: null,
      currentVersionNumber: null,
      isReadonly: false,
    }
    getRouter().navigate(
      "writing",
      null,
      true,
      new URLSearchParams({ chapter_index: String(chapterIndex) }),
    )
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      if (controller) controller.abort()
      controller = null
      generation += 1
    })
  }

  return {
    open,
    loading,
    content,
    close,
    openHit,
    traceRef,
    navigateObjectRef,
    navigateSceneRef,
    navigateChapterRef,
  }
}

export function isWorldObjectRef(ref) {
  return ["world_entity", "core_entity", "entity", "character"].includes(ref?.target_type)
}
