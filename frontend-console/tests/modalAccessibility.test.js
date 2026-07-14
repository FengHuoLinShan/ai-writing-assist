import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

await import("../ui/modal.js")

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")

function renderModalShell() {
  document.body.innerHTML = `
    <button id="opener">打开</button>
    <div id="modal-overlay" class="hidden">
      <div id="modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div id="modal-header">
          <span id="modal-title"></span>
          <button id="modal-close" type="button" aria-label="关闭对话框">×</button>
        </div>
        <div id="modal-body"></div>
        <div id="modal-footer"></div>
      </div>
    </div>
  `
}

function stubConfirm(result) {
  const confirmMock = vi.fn(() => result)
  vi.stubGlobal("confirm", confirmMock)
  return confirmMock
}

beforeEach(() => {
  closeModal({ force: true })
  renderModalShell()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("shared modal accessibility", () => {
  it("declares the shared shell as a labelled modal dialog", () => {
    expect(indexHtml).toMatch(
      /id="modal-content"[^>]*role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="modal-title"/,
    )
    expect(indexHtml).toMatch(
      /id="modal-close"[^>]*type="button"[^>]*aria-label="关闭对话框"/,
    )
  })

  it("moves focus into form content and restores the opener after close", () => {
    const opener = document.getElementById("opener")
    const input = document.createElement("input")
    input.setAttribute("aria-label", "名称")
    opener.focus()

    showModal("新建项目", input, [{ text: "保存", handler: vi.fn() }])

    expect(document.getElementById("modal-title").textContent).toBe("新建项目")
    expect(document.activeElement).toBe(input)

    closeModal()

    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    expect(document.activeElement).toBe(opener)
  })

  it("keeps keyboard focus inside the dialog in both tab directions", () => {
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "保存", handler: vi.fn() }])

    const focusable = Array.from(document.querySelectorAll(
      "#modal-content button:not([disabled]), #modal-content input:not([disabled])",
    ))
    const first = focusable[0]
    const last = focusable.at(-1)

    last.focus()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(first)

    first.focus()
    document.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Tab",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    }))
    expect(document.activeElement).toBe(last)
  })

  it("skips disabled, hidden, inert, and CSS-hidden controls for initial focus and tab wrapping", () => {
    const body = document.createElement("div")
    body.innerHTML = `
      <input id="disabled-autofocus" autofocus disabled>
      <div style="display: none"><button id="css-hidden">隐藏</button></div>
      <div inert><button id="inert-control">不可交互</button></div>
      <button id="available">可用</button>
    `

    showModal("选择", body, [{ text: "确认", handler: vi.fn() }])

    const available = document.getElementById("available")
    const first = document.getElementById("modal-close")
    const last = document.querySelector("#modal-footer .btn-ghost")
    expect(document.activeElement).toBe(available)

    last.focus()
    document.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Tab",
      bubbles: true,
      cancelable: true,
    }))
    expect(document.activeElement).toBe(first)
  })

  it("closes with Escape from an input and restores the original opener across replacements", () => {
    const opener = document.getElementById("opener")
    const firstInput = document.createElement("input")
    opener.focus()
    showModal("第一步", firstInput)

    const secondInput = document.createElement("input")
    showModal("第二步", secondInput)
    expect(document.activeElement).toBe(secondInput)

    secondInput.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    }))

    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    expect(document.activeElement).toBe(opener)
  })

  it("consumes Escape before the application-level input shortcut can blur the field", () => {
    const input = document.createElement("input")
    const applicationKeydown = vi.fn()
    document.addEventListener("keydown", applicationKeydown)
    showModal("编辑", input)

    input.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    }))

    expect(applicationKeydown).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    document.removeEventListener("keydown", applicationKeydown)
  })

  it("does not focus a detached opener when the dialog closes", () => {
    const opener = document.getElementById("opener")
    const focusSpy = vi.spyOn(opener, "focus")
    opener.focus()
    showModal("提示", "正文")
    opener.remove()

    closeModal()

    expect(focusSpy).toHaveBeenCalledOnce()
  })

  it("keeps a changed form open when discarding is rejected", () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    input.value = "原值"
    showModal("编辑", input)
    input.value = "新值"

    const closed = closeModal()

    expect(closed).toBe(false)
    expect(confirmSpy).toHaveBeenCalledWith("有未保存的更改，确定放弃并关闭吗？")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    expect(document.activeElement).toBe(input)
  })

  it("does not ask twice when a close-button handler already rejected discarding", async () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "关闭", handler: closeModal }])
    input.value = "新值"

    const closeButton = Array.from(document.querySelectorAll("#modal-footer button"))
      .find((button) => button.textContent === "关闭")
    closeButton.click()
    await Promise.resolve()

    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("closes unchanged or reverted forms without a discard prompt", () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    input.value = "原值"
    showModal("编辑", input)

    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()

    showModal("再次编辑", input)
    input.value = "临时值"
    input.value = "原值"
    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it("discards changed checkbox and select values only after confirmation", () => {
    const confirmSpy = stubConfirm(true)
    const body = document.createElement("div")
    body.innerHTML = `
      <label><input id="enabled" type="checkbox" value="yes">启用</label>
      <select id="status"><option value="draft">草稿</option><option value="done">完成</option></select>
    `
    const opener = document.getElementById("opener")
    opener.focus()
    showModal("设置", body)
    document.getElementById("enabled").checked = true
    document.getElementById("status").value = "done"

    expect(closeModal()).toBe(true)
    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    expect(document.activeElement).toBe(opener)
  })

  it.each([
    ["textarea", () => {
      const element = document.createElement("textarea")
      element.value = "原值"
      return { element, change: () => { element.value = "新值" } }
    }],
    ["radio", () => {
      const element = document.createElement("input")
      element.type = "radio"
      return { element, change: () => { element.checked = true } }
    }],
    ["multi-select", () => {
      const element = document.createElement("select")
      element.multiple = true
      element.innerHTML = '<option value="a" selected>A</option><option value="b">B</option>'
      return { element, change: () => { element.options[1].selected = true } }
    }],
    ["contenteditable", () => {
      const element = document.createElement("div")
      element.contentEditable = "plaintext-only"
      element.innerHTML = "原值"
      return { element, change: () => { element.innerHTML = "<b>新值</b>" } }
    }],
  ])("protects changed %s values", (_label, createControl) => {
    const confirmSpy = stubConfirm(false)
    const { element, change } = createControl()
    showModal("编辑", element)
    change()

    expect(closeModal()).toBe(false)
    expect(confirmSpy).toHaveBeenCalledOnce()
  })

  it("recognizes restored values across all supported editable controls", () => {
    const confirmSpy = stubConfirm(false)
    const body = document.createElement("div")
    body.innerHTML = `
      <input id="text" value="原值">
      <textarea id="notes">原备注</textarea>
      <input id="check" type="checkbox" checked>
      <input id="radio-a" name="choice" type="radio" value="a" checked>
      <input id="radio-b" name="choice" type="radio" value="b">
      <select id="single"><option value="a" selected>A</option><option value="b">B</option></select>
      <select id="multiple" multiple><option value="a" selected>A</option><option value="b">B</option></select>
      <div id="editable" contenteditable="true">原正文</div>
    `
    showModal("编辑", body)

    const text = document.getElementById("text")
    const notes = document.getElementById("notes")
    const check = document.getElementById("check")
    const radioA = document.getElementById("radio-a")
    const radioB = document.getElementById("radio-b")
    const single = document.getElementById("single")
    const multiple = document.getElementById("multiple")
    const editable = document.getElementById("editable")
    text.value = "临时值"
    notes.value = "临时备注"
    check.checked = false
    radioB.checked = true
    single.value = "b"
    multiple.options[1].selected = true
    editable.innerHTML = "<b>临时正文</b>"

    text.value = "原值"
    notes.value = "原备注"
    check.checked = true
    radioA.checked = true
    single.value = "a"
    multiple.options[1].selected = false
    editable.innerHTML = "原正文"

    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it("treats controls added after opening and removed baseline controls as changes", () => {
    const confirmSpy = stubConfirm(false)
    const body = document.createElement("div")
    showModal("动态表单", body)

    const added = document.createElement("input")
    body.appendChild(added)
    expect(closeModal()).toBe(false)

    closeModal({ force: true })
    body.innerHTML = '<input id="original" value="原值">'
    showModal("动态表单", body)
    document.getElementById("original").remove()
    expect(closeModal()).toBe(false)
    expect(confirmSpy).toHaveBeenCalledTimes(2)
  })

  it("ignores newly added disabled controls and disabling an unchanged baseline control", () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    input.value = "原值"
    showModal("动态表单", input)
    input.disabled = true

    const disabledAddition = document.createElement("textarea")
    disabledAddition.disabled = true
    document.getElementById("modal-body").appendChild(disabledAddition)

    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it("ignores removal or addition of controls that users could not edit", () => {
    const confirmSpy = stubConfirm(false)
    const body = document.createElement("div")
    body.innerHTML = `
      <input id="disabled" disabled value="系统值">
      <textarea id="readonly" readonly>只读值</textarea>
      <div id="css-hidden" style="display: none"><input value="隐藏值"></div>
      <div id="visibility-hidden" style="visibility: hidden"><input value="隐藏值"></div>
    `
    showModal("只读信息", body)
    body.innerHTML = `
      <input disabled value="动态系统值">
      <input style="display: none" value="动态隐藏值">
    `

    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it("protects header, overlay, and Escape close paths", () => {
    const confirmSpy = stubConfirm(false)
    const downstreamClose = vi.fn()
    const downstreamOverlay = vi.fn()
    const downstreamEscape = vi.fn()
    const input = document.createElement("input")
    const headerClose = document.getElementById("modal-close")
    const overlay = document.getElementById("modal-overlay")
    headerClose.addEventListener("click", closeModal)
    headerClose.addEventListener("click", downstreamClose)
    overlay.addEventListener("click", (event) => {
      if (event.target === event.currentTarget && !closeModal(event)) {
        event.preventDefault()
        event.stopImmediatePropagation()
      }
    })
    overlay.addEventListener("click", downstreamOverlay)
    document.addEventListener("keydown", downstreamEscape, true)
    showModal("编辑", input)
    input.value = "新值"

    headerClose.click()
    overlay.click()
    input.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    }))

    expect(confirmSpy).toHaveBeenCalledTimes(3)
    expect(downstreamClose).not.toHaveBeenCalled()
    expect(downstreamOverlay).not.toHaveBeenCalled()
    expect(downstreamEscape).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    document.removeEventListener("keydown", downstreamEscape, true)
  })

  it("preserves close-button false-result behavior while prompting only once", async () => {
    const confirmSpy = stubConfirm(true)
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "关闭", handler: vi.fn().mockResolvedValue(false) }])
    input.value = "新值"

    document.querySelector("#modal-footer button").click()
    await vi.waitFor(() => {
      expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    })

    expect(confirmSpy).toHaveBeenCalledOnce()
  })

  it("keeps changed forms open when an action returns false or throws", async () => {
    const confirmSpy = stubConfirm(false)
    const falseHandler = vi.fn().mockResolvedValue(false)
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "保存", handler: falseHandler }])
    input.value = "新值"

    document.querySelector("#modal-footer button").click()
    await vi.waitFor(() => expect(falseHandler).toHaveBeenCalledOnce())
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)

    const throwingHandler = vi.fn().mockRejectedValue(new Error("保存失败"))
    showModal("编辑", input, [{ text: "保存", handler: throwingHandler }])
    input.value = "又一新值"
    document.querySelector("#modal-footer button").click()
    await vi.waitFor(() => expect(throwingHandler).toHaveBeenCalledOnce())

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("lets an action close synchronously without a discard prompt", async () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    const handler = vi.fn(() => closeModal())
    showModal("编辑", input, [{ text: "保存", handler }])
    input.value = "已保存"

    document.querySelector("#modal-footer button").click()
    await vi.waitFor(() => expect(handler).toHaveBeenCalledOnce())

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
  })

  it("lets an async action close after awaiting without a discard prompt", async () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    const handler = vi.fn(async () => {
      await Promise.resolve()
      closeModal()
    })
    showModal("编辑", input, [{ text: "保存", handler }])
    input.value = "已保存"

    document.querySelector("#modal-footer button").click()
    await vi.waitFor(() => expect(handler).toHaveBeenCalledOnce())

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
  })

  it("does not let an external close bypass protection while an async action is pending", async () => {
    const confirmSpy = stubConfirm(false)
    let resolveSave
    const save = new Promise((resolve) => { resolveSave = resolve })
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "保存", handler: () => save }])
    input.value = "新值"
    document.querySelector("#modal-footer button").click()

    input.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    }))

    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    resolveSave(false)
    await Promise.resolve()
  })

  it("does not let a cancel handler bypass protection while an async action is pending", async () => {
    const confirmSpy = stubConfirm(false)
    let resolveSave
    const save = new Promise((resolve) => { resolveSave = resolve })
    const input = document.createElement("input")
    showModal("编辑", input, [
      { text: "保存", handler: () => save },
      { text: "取消", handler: () => closeModal() },
    ])
    input.value = "新值"
    const buttons = Array.from(document.querySelectorAll("#modal-footer button"))
    buttons.find((button) => button.textContent === "保存").click()
    buttons.find((button) => button.textContent === "取消").click()
    await Promise.resolve()

    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    resolveSave(false)
    await Promise.resolve()
  })

  it("does not let a stale async action close a replacement dialog", async () => {
    let releaseSave
    const saveGate = new Promise((resolve) => { releaseSave = resolve })
    const firstInput = document.createElement("input")
    showModal("第一步", firstInput, [{
      text: "保存",
      handler: async () => {
        await saveGate
        closeModal()
      },
    }])
    document.querySelector("#modal-footer button").click()

    confirmAction("确认替换？", vi.fn())
    releaseSave()
    await Promise.resolve()
    await Promise.resolve()

    expect(document.getElementById("modal-title").textContent).toBe("确认操作")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("bypasses the discard prompt after a successful primary action", async () => {
    const confirmSpy = stubConfirm(false)
    const handler = vi.fn().mockResolvedValue(true)
    const input = document.createElement("input")
    showModal("编辑", input, [{ text: "保存", handler }])
    input.value = "已修改"

    const saveButton = Array.from(document.querySelectorAll("#modal-footer button"))
      .find((button) => button.textContent === "保存")
    saveButton.click()
    await vi.waitFor(() => expect(handler).toHaveBeenCalledOnce())

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
  })

  it("supports explicit opt-out for transient editable controls", () => {
    const confirmSpy = stubConfirm(false)
    const input = document.createElement("input")
    showModal("临时输入", input, [], { protectUnsaved: false })
    input.value = "不需要保护"

    expect(closeModal()).toBe(true)
    expect(confirmSpy).not.toHaveBeenCalled()
  })
})
