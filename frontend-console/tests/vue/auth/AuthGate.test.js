import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
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

beforeEach(() => {
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
  it("requires policy consent and completes email verification", async () => {
    const wrapper = mount(AuthGate, { props: { config: config() } })
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

  it("prevents another code request during the server-provided resend interval", async () => {
    vi.useFakeTimers()
    const wrapper = mount(AuthGate, { props: { config: config() } })
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
