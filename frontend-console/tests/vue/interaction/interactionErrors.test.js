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
    [{ error_kind: "source_context_stale" }, "source_context_stale"],
    [{ error_kind: "source_context_blocked" }, "source_context_blocked"],
    [{ error_kind: "empty_response" }, "empty_response"],
    [{ message: "当前浏览器无法安全生成操作标识，请更换浏览器后重试" }, "client_security"],
  ])("把稳定错误形状映射到本地文案", (error, expectedKind) => {
    const result = safeInteractionError(error)

    expect(result.kind).toBe(expectedKind)
    expect(result.message).toBeTruthy()
  })

  it.each([
    ["source_context_blocked", "source"],
    ["source_context_stale", "retry"],
  ])("来源资料错误给出可执行的补救动作", (kind, action) => {
    const result = safeInteractionError({ error_kind: kind })

    expect(result.action).toBe(action)
  })

  it("透传后端 DomainError 拒绝理由(建旅程、固定资料等)", () => {
    const result = safeInteractionError({
      status: 400,
      message: "请求参数错误：所选角色在当前剧情进度尚未登场",
      detail: "所选角色在当前剧情进度尚未登场",
      body: { error: "validation_error", detail: "所选角色在当前剧情进度尚未登场" },
    })

    expect(result.message).toBe("所选角色在当前剧情进度尚未登场")
  })

  it("422 请求校验错误可能携带英文诊断，不透传", () => {
    const raw = "Invalid draft_id: not-a-uuid"
    const result = safeInteractionError({
      status: 422,
      message: `请求参数错误：${raw}`,
      detail: raw,
      body: { error: "validation_error", detail: raw },
    })

    expect(result.message).not.toContain("Invalid draft_id")
  })

  it("非 DomainError 的服务端详情不透传", () => {
    const raw = "upstream conflict detail: secret-provider-debug-payload"
    const result = safeInteractionError({
      status: 500,
      message: raw,
      detail: raw,
      body: { error: "internal_error", detail: raw },
    })

    expect(result.message).toBe("这次生成未完成，请重新生成。")
    expect(result.message).not.toContain("secret-provider")
  })
})
