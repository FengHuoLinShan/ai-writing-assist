import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import AccountDialog from "../../../vue/shell/components/AccountDialog.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)
let authApi

beforeEach(() => {
  authApi = {
    requestReauthEmailCode: vi.fn(async () => ({ challenge_id: "challenge-1" })),
    verifyReauthEmail: vi.fn(async () => ({ reauthenticated: true })),
    requestDeletion: vi.fn(async () => ({ status: "pending_deletion" })),
    wechatStartUrl: vi.fn(() => "/api/auth/reauth/wechat/start"),
  }
  setBridgeOverrides({ api: { auth: authApi } })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("AccountDialog", () => {
  it("delegates successful deletion invalidation instead of reloading with private caches intact", async () => {
    const wrapper = mount(AccountDialog, {
      props: {
        open: true,
        account: { id: "account-1", identity_type: "email", support_code: "U-ACCOUNT1" },
        config: { auth_mode: "public", wechat_enabled: false },
      },
    })
    const inputs = wrapper.findAll("input")
    await inputs[0].setValue("writer@example.com")
    await wrapper.findAll("button")
      .find((button) => button.text().includes("发送验证码"))
      .trigger("click")
    await flushPromises()
    await inputs[1].setValue("123456")
    await wrapper.findAll("button")
      .find((button) => button.text().includes("验证并申请删除"))
      .trigger("click")
    await flushPromises()

    expect(authApi.requestDeletion).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted("account-invalidated")).toHaveLength(1)
  })
})
