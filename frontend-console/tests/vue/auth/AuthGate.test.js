import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import AuthGate from "../../../vue/auth/AuthGate.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)
let authApi

function config(overrides = {}) {
  return {
    auth_mode: "public",
    wechat_enabled: false,
    terms_url: "/legal/terms",
    privacy_url: "/legal/privacy",
    ...overrides,
  }
}

async function mountLogin(entry = "author") {
  const wrapper = mount(AuthGate, { props: { config: config() } })
  await wrapper.get(`[data-entry="${entry}"]`).trigger("click")
  return wrapper
}

beforeEach(() => {
  sessionStorage.clear()
  authApi = {
    requestEmailCode: vi.fn().mockResolvedValue({ challenge_id: "challenge-1", resend_after: 60 }),
    verifyEmail: vi.fn().mockResolvedValue({
      id: "account-1",
      status: "active",
      identity_type: "email",
    }),
    wechatStartUrl: vi.fn(() => "/api/auth/wechat/start"),
  }
  setBridgeOverrides({
    api: { auth: authApi },
  })
})

afterEach(() => {
  vi.useRealTimers()
  resetBridgeOverrides()
})

describe("AuthGate", () => {
  it("先选择使用方式，登录页可键盘返回原选项", async () => {
    const wrapper = mount(AuthGate, {
      attachTo: document.body,
      props: { config: config() },
    })

    expect(wrapper.findAll(".entry-card")).toHaveLength(2)
    expect(wrapper.find(".auth-card").exists()).toBe(false)

    await wrapper.get('[data-entry="rp"]').trigger("click")
    expect(wrapper.text()).toContain("登录后将进入互动故事")
    expect(sessionStorage.getItem("nc-entry-mode-after-auth")).toBe("rp")
    expect(wrapper.get('input[type="email"]').element).toBe(document.activeElement)

    wrapper.unmount()
    const restored = mount(AuthGate, { props: { config: config() } })
    expect(restored.text()).toContain("登录后将进入互动故事")
    restored.unmount()

    const resumed = mount(AuthGate, {
      attachTo: document.body,
      props: { config: config() },
    })

    await resumed.get(".auth-back").trigger("click")
    expect(resumed.findAll(".entry-card")).toHaveLength(2)
    expect(sessionStorage.getItem("nc-entry-mode-after-auth")).toBeNull()
    expect(resumed.get('[data-entry="rp"]').element).toBe(document.activeElement)
  })

  it("exposes named one-time-code inputs and the initial idle state", async () => {
    const login = await mountLogin()
    const recovery = mount(AuthGate, {
      props: {
        config: config(),
        initialAccount: { id: "account-1", status: "pending_deletion", identity_type: "email" },
      },
    })

    expect(login.find(".auth-card").attributes("aria-busy")).toBe("false")
    expect(login.find('input[aria-label="邮箱验证码"]').attributes("autocomplete")).toBe("one-time-code")
    expect(recovery.find('input[aria-label="重新认证验证码"]').attributes("autocomplete")).toBe("one-time-code")
  })

  it("requires policy consent and completes email verification", async () => {
    const wrapper = await mountLogin()
    const inputs = wrapper.findAll("input")
    await inputs[0].setValue("writer@example.com")
    await inputs[1].setValue("123456")
    await wrapper.findAll("button").find((button) => button.text().includes("发送验证码")).trigger("click")
    await inputs[2].setValue(true)
    await wrapper.findAll("button").find((button) => button.text().includes("邮箱登录")).trigger("click")

    expect(authApi.requestEmailCode).toHaveBeenCalledWith("writer@example.com")
    expect(authApi.verifyEmail).toHaveBeenCalledWith({
      email: "writer@example.com",
      code: "123456",
      challenge_id: "challenge-1",
      accept_terms: true,
      accept_privacy: true,
    })
    expect(wrapper.emitted("authenticated")?.[0]?.[0]?.id).toBe("account-1")
  })

  it("announces successful resend status and restores idle state after deferred requests", async () => {
    let resolveRequest
    let resolveVerify
    authApi.requestEmailCode.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve }))
    authApi.verifyEmail.mockImplementationOnce(() => new Promise((resolve) => { resolveVerify = resolve }))
    const wrapper = await mountLogin()
    await wrapper.find('input[type="email"]').setValue("writer@example.com")

    const request = wrapper.findAll("button").find((button) => button.text() === "发送验证码")
    await request.trigger("click")
    expect(wrapper.find(".auth-card").attributes("aria-busy")).toBe("true")

    resolveRequest({ challenge_id: "challenge-deferred", resend_after: 60 })
    await flushPromises()
    expect(wrapper.find(".auth-card").attributes("aria-busy")).toBe("false")
    expect(wrapper.find(".message").attributes("role")).toBe("status")

    await wrapper.find('input[aria-label="邮箱验证码"]').setValue("123456")
    await wrapper.find('input[type="checkbox"]').setValue(true)
    const verify = wrapper.findAll("button").find((button) => button.text() === "邮箱登录")
    await verify.trigger("click")
    expect(wrapper.find(".auth-card").attributes("aria-busy")).toBe("true")

    resolveVerify({ id: "account-1", status: "active", identity_type: "email" })
    await flushPromises()
    expect(wrapper.find(".auth-card").attributes("aria-busy")).toBe("false")
  })

  it("announces rejected email code requests as alerts", async () => {
    authApi.requestEmailCode.mockRejectedValueOnce(new Error("验证码发送失败"))
    const wrapper = await mountLogin()
    await wrapper.find('input[type="email"]').setValue("writer@example.com")
    await wrapper.findAll("button").find((button) => button.text() === "发送验证码").trigger("click")
    await flushPromises()

    expect(wrapper.find(".auth-card").attributes("aria-busy")).toBe("false")
    expect(wrapper.find(".message").attributes("role")).toBe("alert")
    expect(wrapper.find(".message").text()).toBe("验证码发送失败")
  })

  it("prevents another code request during the server-provided resend interval", async () => {
    vi.useFakeTimers()
    const wrapper = await mountLogin()
    await wrapper.find('input[type="email"]').setValue("writer@example.com")
    const sendButton = wrapper.findAll("button")
      .find((button) => button.text() === "发送验证码")

    await sendButton.trigger("click")

    expect(sendButton.attributes("disabled")).toBeDefined()
    expect(sendButton.text()).toBe("重新发送（60秒）")

    await vi.advanceTimersByTimeAsync(59_000)
    expect(sendButton.text()).toBe("重新发送（1秒）")
    expect(sendButton.attributes("disabled")).toBeDefined()

    await vi.advanceTimersByTimeAsync(1_000)
    expect(sendButton.text()).toBe("发送验证码")
    expect(sendButton.attributes("disabled")).toBeUndefined()
  })

  it("shows the restricted recovery state for pending deletion", () => {
    const wrapper = mount(AuthGate, {
      props: {
        config: config(),
        initialAccount: {
          id: "account-1",
          status: "pending_deletion",
          identity_type: "email",
          support_code: "U-RECOVER1",
          purge_after: "2026-08-22T00:00:00Z",
        },
      },
    })

    expect(wrapper.text()).toContain("账号正在等待删除")
    expect(wrapper.text()).toContain("U-RECOVER1")
    expect(wrapper.text()).not.toContain("邮箱登录")
    expect(wrapper.findAll("button").some((button) => button.text() === "退出登录")).toBe(true)
  })

  it("exposes logout from the pending-deletion gate", async () => {
    const wrapper = mount(AuthGate, {
      props: {
        config: config(),
        initialAccount: {
          id: "account-1",
          status: "pending_deletion",
          identity_type: "email",
        },
      },
    })

    await wrapper.findAll("button").find((button) => button.text() === "退出登录").trigger("click")

    expect(wrapper.emitted("logout")).toHaveLength(1)
  })
})
