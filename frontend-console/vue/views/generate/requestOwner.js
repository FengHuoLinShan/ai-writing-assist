/**
 * 生成中心异步所有权：每个 island 实例拥有自己的代次和 AbortController 集合。
 * 即使旧 API 忽略 signal，isActive() 仍会拒绝项目/会话/生命周期不匹配的晚到响应。
 */
export function createGenerateRequestOwner({ projectId, sessionKey }) {
  let generation = 0
  let disposed = false
  const controllers = new Set()

  function begin() {
    const controller = new AbortController()
    controllers.add(controller)
    const scope = { projectId, sessionKey, generation, controller }
    return scope
  }

  function isActive(scope) {
    return Boolean(
      scope
      && !disposed
      && scope.projectId === projectId
      && scope.sessionKey === sessionKey
      && scope.generation === generation
      && !scope.controller.signal.aborted,
    )
  }

  function finish(scope) {
    if (scope?.controller) controllers.delete(scope.controller)
  }

  function invalidate() {
    generation += 1
    for (const controller of controllers) controller.abort()
    controllers.clear()
  }

  function dispose() {
    disposed = true
    invalidate()
  }

  return { begin, isActive, finish, invalidate, dispose, get pendingCount() { return controllers.size } }
}
