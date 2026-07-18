/**
 * 任务进度轮询 composable — 包 shared/workflowProgress.js 的 pollTaskProgress：
 * apiClient 经 bridge 取（测试可 DI 替身）；scope 销毁时自动 stop 全部轮询，
 * 对应 vanilla 视图 onLeave 的手动清理（island unmount 时自动触发）。
 */
import { getCurrentScope, onScopeDispose } from "vue"
import { pollTaskProgress } from "../../shared/workflowProgress.js"
import { getApi } from "../bridge/index.js"

export function useWorkflowPolling() {
  const handles = new Set()

  function stopAll() {
    for (const handle of handles) handle.stop()
    handles.clear()
  }

  /**
   * 启动一次轮询。options 同 pollTaskProgress（taskId/workflowType/novelId/
   * intervalMs/onUpdate/onDone/onFailed），apiClient 由 bridge 提供。
   * @returns {{stop: function}}
   */
  function start(options) {
    const handle = pollTaskProgress({ apiClient: getApi(), ...options })
    handles.add(handle)
    return handle
  }

  if (getCurrentScope()) onScopeDispose(stopAll)

  return { start, stopAll }
}
