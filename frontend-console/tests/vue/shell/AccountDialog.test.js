import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import AccountDialog from "../../../vue/shell/components/AccountDialog.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)
let authApi

beforeEach(() => {
  document.body.innerHTML = ""
  authApi = {
    requestReauthEmailCode: vi.fn(async () => ({ challenge_id: "challenge-1", resend_after: 60 })),
    verifyReauthEmail: vi.fn(async () => ({ reauthenticated: true })),
    requestDeletion: vi.fn(async () => ({ status: "pending_deletion" })),
    wechatStartUrl: vi.fn(() => "/api/auth/reauth/wechat/start"),
  }
  setBridgeOverrides({ api: { auth: authApi } })
})

afterEach(() => {
  vi.useRealTimers()
  resetBridgeOverrides()
})

describe("AccountDialog", () => {
  function mountInShell(props = {}, { preInert = false } = {}) {
    const shell = document.createElement("div")
    shell.className = "vue-shell-root"
    const topbar = document.createElement("header")
    topbar.id = "topbar"
    const trigger = document.createElement("button")
    trigger.textContent = "账户菜单"
    topbar.appendChild(trigger)
    const main = document.createElement("main")
    main.id = "main-layout"
    if (preInert) topbar.setAttribute("inert", "")
    shell.append(topbar, main)
    document.body.appendChild(shell)
    trigger.focus()
    return {
      shell,
      topbar,
      main,
      trigger,
      wrapper: mount(AccountDialog, {
        attachTo: shell,
        props: {
          open: true,
          account: { id: "account-1", identity_type: "email" },
          config: { auth_mode: "public", wechat_enabled: false },
          ...props,
        },
      }),
    }
  }

  async function settleDialog() {
    await nextTick()
    await nextTick()
  }

  it("enters the modal after rendering, isolates shell siblings, and returns focus on parent close", async () => {
    const { wrapper, topbar, main, trigger } = mountInShell()
    await settleDialog()

    expect(topbar.hasAttribute("inert")).toBe(true)
    expect(main.hasAttribute("inert")).toBe(true)
    expect(document.activeElement).toBe(wrapper.get(".account-close").element)

    await wrapper.setProps({ open: false })
    await settleDialog()
    expect(topbar.hasAttribute("inert")).toBe(false)
    expect(main.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).toBe(trigger)
  })

  it("traps Tab within visible controls and excludes closed details descendants", async () => {
    const { wrapper } = mountInShell()
    await settleDialog()
    const overlay = wrapper.get(".account-overlay").element
    const close = wrapper.get(".account-close").element
    const summary = wrapper.get("summary").element
    const email = wrapper.get('input[type="email"]').element

    expect(email.closest("details").open).toBe(false)
    expect(email).not.toBe(document.activeElement)
    close.focus()
    const shiftTab = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true })
    overlay.dispatchEvent(shiftTab)
    expect(shiftTab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(summary)

    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    overlay.dispatchEvent(tab)
    expect(tab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(close)
  })

  it("contains ordinary keys without preventing them, and lets Escape request close", async () => {
    const { wrapper } = mountInShell()
    await settleDialog()
    const documentKeys = vi.fn()
    document.addEventListener("keydown", documentKeys)
    const overlay = wrapper.get(".account-overlay").element
    const ordinary = new KeyboardEvent("keydown", { key: "g", bubbles: true, cancelable: true })
    overlay.dispatchEvent(ordinary)
    expect(documentKeys).not.toHaveBeenCalled()
    expect(ordinary.defaultPrevented).toBe(false)

    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    overlay.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(true)
    expect(wrapper.emitted("close")).toHaveLength(1)
    document.removeEventListener("keydown", documentKeys)
  })

  it("preserves a shell sibling that was inert before opening", async () => {
    const { wrapper, topbar, main } = mountInShell({}, { preInert: true })
    await settleDialog()
    expect(topbar.hasAttribute("inert")).toBe(true)
    expect(main.hasAttribute("inert")).toBe(true)

    await wrapper.setProps({ open: false })
    await settleDialog()
    expect(topbar.hasAttribute("inert")).toBe(true)
    expect(main.hasAttribute("inert")).toBe(false)
  })

  it("does not let a late open task add inert or reclaim focus after immediate close and unmount", async () => {
    const { wrapper, topbar, main } = mountInShell()
    const outside = document.createElement("button")
    document.body.appendChild(outside)
    const close = wrapper.setProps({ open: false })
    wrapper.unmount()
    outside.focus()
    await close
    await settleDialog()
    expect(topbar.hasAttribute("inert")).toBe(false)
    expect(main.hasAttribute("inert")).toBe(false)
    expect(document.activeElement).toBe(outside)
  })

  it("exposes the dialog, close action, deletion code input, and initial idle state", () => {
    const wrapper = mount(AccountDialog, {
      props: {
        open: true,
        account: { id: "account-1", identity_type: "email" },
        config: { auth_mode: "public", wechat_enabled: false },
      },
    })

    expect(wrapper.find('[role="dialog"]').attributes("aria-busy")).toBe("false")
    expect(wrapper.find('button[aria-label="关闭账号设置"]').exists()).toBe(true)
    expect(wrapper.find('input[aria-label="账号删除验证码"]').attributes("autocomplete")).toBe("one-time-code")
  })

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

  it("announces successful reauth resend status and restores idle state after a deferred request", async () => {
    let resolveRequest
    authApi.requestReauthEmailCode.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve }))
    const wrapper = mount(AccountDialog, {
      props: {
        open: true,
        account: { id: "account-1", identity_type: "email" },
        config: { auth_mode: "public", wechat_enabled: false },
      },
    })
    await wrapper.find('input[type="email"]').setValue("writer@example.com")
    await wrapper.findAll("button").find((button) => button.text() === "发送验证码").trigger("click")

    expect(wrapper.find('[role="dialog"]').attributes("aria-busy")).toBe("true")
    resolveRequest({ challenge_id: "challenge-deferred", resend_after: 60 })
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').attributes("aria-busy")).toBe("false")
    expect(wrapper.find(".account-message").attributes("role")).toBe("status")
  })

  it("announces failed reauth code requests as alerts after restoring idle state", async () => {
    authApi.requestReauthEmailCode.mockRejectedValueOnce(new Error("验证码发送失败"))
    const wrapper = mount(AccountDialog, {
      props: {
        open: true,
        account: { id: "account-1", identity_type: "email" },
        config: { auth_mode: "public", wechat_enabled: false },
      },
    })
    await wrapper.find('input[type="email"]').setValue("writer@example.com")
    await wrapper.findAll("button").find((button) => button.text() === "发送验证码").trigger("click")
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').attributes("aria-busy")).toBe("false")
    expect(wrapper.find(".account-message").attributes("role")).toBe("alert")
    expect(wrapper.find(".account-message").text()).toBe("验证码发送失败")
  })

  it("disables reauth code resend for 60 seconds", async () => {
    vi.useFakeTimers()
    const wrapper = mount(AccountDialog, {
      props: {
        open: true,
        account: { id: "account-1", identity_type: "email" },
        config: { auth_mode: "public", wechat_enabled: false },
      },
    })
    const sendButton = wrapper.findAll("button")
      .find((button) => button.text() === "发送验证码")

    await sendButton.trigger("click")
    await flushPromises()

    expect(sendButton.attributes("disabled")).toBeDefined()
    expect(sendButton.text()).toBe("重新发送（60秒）")

    await vi.advanceTimersByTimeAsync(60_000)
    expect(sendButton.text()).toBe("发送验证码")
    expect(sendButton.attributes("disabled")).toBeUndefined()
  })
})
