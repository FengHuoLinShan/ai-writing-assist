const ERROR_STATES = {
  configuration: {
    message: "模型连接不可用，请检查账户设置。",
    action: "connection",
  },
  quota: {
    message: "模型额度可能不足，请在模型服务账户中确认余额后再试。",
    action: "connection",
  },
  rate_limit: {
    message: "请求过快，模型服务需要稍等片刻。",
    action: "retry",
  },
  connection: {
    message: "模型服务或网络暂时不可用；已保存的故事和草稿不会丢失。",
    action: "retry",
  },
  content_filter: {
    message: "这次内容未能生成，请换一种说法后重试。",
    action: "rewrite",
  },
  context_budget: {
    message: "当前故事暂时无法在安全范围内继续，请先查看并精简回顾。",
    action: "overview",
  },
  source_context_blocked: {
    message: "作品资料暂时无法安全引用，请查看作品资料调整后重试。",
    action: "source",
  },
  source_context_stale: {
    message: "作品资料已变化，请重新生成。",
    action: "retry",
  },
  empty_response: {
    message: "这次没有生成内容，请重新生成。",
    action: "retry",
  },
  concurrency: {
    message: "已有 8 段故事正在生成，请先等待或停止一段。",
    action: "wait",
  },
  generation_failed: {
    message: "这次生成未完成，请重新生成。",
    action: "retry",
  },
  client_security: {
    message: "当前浏览器无法安全发起操作，请更换浏览器后重试。",
    action: "retry",
  },
}

function normalizedErrorKind(error) {
  if (typeof error === "string") return error
  const explicit = String(error?.error_kind || error?.body?.error || "")
  if (explicit === "project_llm_configuration_error") return "configuration"
  if (explicit === "interaction_concurrency_limit") return "concurrency"
  if (explicit) return explicit
  if (error?.status === 401) return "configuration"
  if (error?.status === 402) return "quota"
  if (error?.status === 429) return "rate_limit"
  if ([502, 503, 504].includes(error?.status)) return "connection"

  // Provider SDKs do not all expose a stable quota code. Use their text only
  // to select a bounded local message; never show it on the RP page.
  const diagnostic = String(error?.detail || error?.message || "").toLowerCase()
  if (/安全生成操作标识/.test(diagnostic)) return "client_security"
  if (/quota|credit|insufficient|balance|余额|额度/.test(diagnostic)) {
    return "quota"
  }
  if (/api key|鉴权|认证|模型连接/.test(diagnostic)) return "configuration"
  if (/rate.?limit|too many|请求过快|限流/.test(diagnostic)) return "rate_limit"
  if (/timeout|network|fetch|连接|网络|服务不可用/.test(diagnostic)) {
    return "connection"
  }
  return "generation_failed"
}

// 后端 DomainError 的 4xx 拒绝消息(建旅程、固定资料等)由服务层面向用户撰写,
// 与 provider 诊断文本不同,允许直接展示;其余错误仍只走本地固定文案。
const DOMAIN_DETAIL_KINDS = new Set(["validation_error", "conflict"])

export function safeInteractionError(error, { opening = false } = {}) {
  const kind = normalizedErrorKind(error)
  const fallback = ERROR_STATES.generation_failed
  const state = ERROR_STATES[kind] || fallback
  const domainDetail = DOMAIN_DETAIL_KINDS.has(String(error?.body?.error || ""))
    && typeof error?.detail === "string"
    && error.detail.trim()
    ? error.detail.trim()
    : ""
  return {
    kind,
    action: state.action,
    message: domainDetail
      || (opening && kind === "generation_failed"
        ? "旅程暂时无法开始，开场内容已保留，请稍后重试。"
        : state.message),
  }
}
