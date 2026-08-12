import { describe, expect, it } from "vitest"
import { safeInteractionError } from "../../../vue/views/interaction/interactionErrors.js"

describe("RP 安全错误文案", () => {
  it("只返回受控用户文案，不透传 provider 或服务端详情", () => {
    const raw = "upstream request failed: secret-provider-debug-payload"
    const result = safeInteractionError({
      status: 500,
      message: raw,
      detail: raw,
    })

    expect(result.kind).toBe("generation_failed")
    expect(result.message).toBe("这次生成未完成，请重新生成。")
    expect(result.message).not.toContain("provider")
    expect(result.message).not.toContain("debug")
  })

  it.each([
    [{ body: { error: "project_llm_configuration_error" } }, "configuration"],
    [{ status: 402 }, "quota"],
    [{ status: 429 }, "rate_limit"],
    [{ status: 503 }, "connection"],
    [{ error_kind: "content_filter" }, "content_filter"],
    [{ error_kind: "context_budget" }, "context_budget"],
    [{ message: "当前浏览器无法安全生成操作标识，请更换浏览器后重试" }, "client_security"],
  ])("把稳定错误形状映射到本地文案", (error, expectedKind) => {
    const result = safeInteractionError(error)

    expect(result.kind).toBe(expectedKind)
    expect(result.message).toBeTruthy()
  })
})
