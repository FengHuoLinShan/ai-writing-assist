/**
 * 项目状态辅助 — vanilla projectView 的 state 操作流程。
 */
import { getApi, getAppState } from "../../../bridge/index.js"

/** currentProjectId 失效时清理选择（含 viewStates.writing 与 localStorage）。 */
export function clearCurrentProjectSelection() {
  const state = getAppState()
  if (!state) return
  state.currentProjectId = null
  state.currentProject = null
  if (state.viewStates) delete state.viewStates.writing
  try {
    localStorage.removeItem("novel_currentProjectId")
    localStorage.removeItem("novel_currentProject")
  } catch {
    // localStorage 不可用时仅清理内存状态
  }
}

/**
 * 拉取项目列表写入 state.projects；同步 currentProject（失效则清理）。
 * 对应 vanilla projectView.onEnter。
 * @returns {Promise<{error: string|null}>}
 */
export async function loadProjectsIntoState() {
  const state = getAppState()
  try {
    const data = await getApi().projects.list()
    if (state) {
      state.projects = data.items || data || []
      if (state.currentProjectId) {
        const match = state.projects.find((p) => p.id === state.currentProjectId)
        if (match) {
          state.currentProject = match
        } else {
          clearCurrentProjectSelection()
        }
      }
    }
    return { error: null }
  } catch (error) {
    return { error: error?.message || "请检查连接后重试；现有作品数据没有被修改。" }
  }
}
