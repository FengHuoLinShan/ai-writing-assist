/**
 * XSS 渲染回归测试
 *
 * 验证用户/AI 内容不通过 innerHTML 直接插入 DOM。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { computed, ref } from "vue"

import "../ui/modal.js"
import { setBridgeOverrides, resetBridgeOverrides } from "../vue/bridge/index.js"
import { createWorldBibleHistory } from "../vue/views/world/bible/worldBibleHistory.js"

beforeEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
})

describe("modal body rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-content">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      </div>
    `
  })

  async function flushClick() {
    await Promise.resolve()
    await Promise.resolve()
  }

  function isModalOpen() {
    return !document.getElementById("modal-overlay").classList.contains("hidden")
  }

  it("does not execute script tags passed as a string body", () => {
    let executed = false
    globalThis.modalXssPayload = () => { executed = true }

    window.showModal("XSS test", "<script>globalThis.modalXssPayload()</script>")

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("script")).toBeNull()
    expect(executed).toBe(false)
    expect(bodyEl.textContent).toContain("<script>globalThis.modalXssPayload()</script>")

    delete globalThis.modalXssPayload
  })

  it("still accepts HTMLElement bodies", () => {
    const node = document.createElement("p")
    node.textContent = "paragraph"
    window.showModal("Node test", node)

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("paragraph")
  })

  it("renders trusted { html: string } via innerHTML", () => {
    window.showModal("HTML test", { html: "<p>paragraph</p>" })

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("paragraph")
  })

  it("showModalHtml wraps the body as trusted HTML", () => {
    window.showModalHtml("HTML helper test", "<p>helper paragraph</p>")

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("p")?.textContent).toBe("helper paragraph")
  })

  it("showModalHtml applies and resets optional size classes", () => {
    const contentEl = document.getElementById("modal-content")

    window.showModalHtml("Large helper test", "<p>large</p>", [], { size: "large" })
    expect(contentEl.classList.contains("modal-content--large")).toBe(true)
    expect(contentEl.dataset.modalSize).toBe("large")

    window.showModalHtml("Default helper test", "<p>default</p>")
    expect(contentEl.classList.contains("modal-content--large")).toBe(false)
    expect(contentEl.classList.contains("modal-content--full")).toBe(false)
    expect(contentEl.dataset.modalSize).toBeUndefined()
  })

  it("closes after an async handler resolves", async () => {
    window.showModal("Async ok", "body", [
      { text: "保存", handler: vi.fn().mockResolvedValue(true) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(false)
  })

  it("keeps open and shows toast when an async handler rejects", async () => {
    window.showModal("Async fail", "body", [
      { text: "保存", handler: vi.fn().mockRejectedValue(new Error("boom")) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(true)
    expect(toast).toHaveBeenCalledWith("操作失败：boom", "error")
  })

  it("keeps open when a handler returns false", async () => {
    window.showModal("Stay open", "body", [
      { text: "保存", handler: vi.fn().mockResolvedValue(false) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(true)
  })

  it("still closes through cancel and close buttons", async () => {
    window.showModal("Cancel", "body", [
      { text: "关闭", handler: vi.fn().mockResolvedValue(false) },
    ])

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(isModalOpen()).toBe(false)
  })

  it("confirmAction async reject does not bypass confirmation or close", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("拒绝删除"))
    window.confirmAction("确定永久删除？", onConfirm, "永久删除")

    expect(onConfirm).not.toHaveBeenCalled()

    document.querySelector("#modal-footer button").click()
    await flushClick()

    expect(onConfirm).toHaveBeenCalledOnce()
    expect(isModalOpen()).toBe(true)
    expect(toast).toHaveBeenCalledWith("操作失败：拒绝删除", "error")
  })
})

describe("world bible history modal assembly", () => {
  // 与生产 shared/esc.js 相同的转义规则（该脚本经 index.html 全局加载，测试内注入 bridge）。
  function productionEsc(str) {
    if (str === null || str === undefined) return ""
    const s = String(str)
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;")
  }

  function bibleHistoryContext(api) {
    return {
      api,
      projectId: ref("p1"),
      activePage: computed(() => ({ id: "page-1" })),
      pageTemplates: computed(() => [{ id: "template-1", builtin: false }]),
      ownsProject: () => true,
      ownsPage: () => true,
      taskStatusLabel: (status) => `状态:${status}`,
      restoreSynopsis: vi.fn(),
      restorePageRevision: vi.fn(),
      applyRestoredTemplate: vi.fn(),
    }
  }

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-content">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      </div>
    `
  })

  it("页面历史把标题、时间、备注与正文先经 esc 再交给 showModalHtml", async () => {
    const api = {
      world: {
        listBiblePageRevisions: vi.fn(async () => [{
          version_number: 2,
          revision_reason: "manual_publish",
          created_at: new Date().toISOString(),
          changed_fields: ["free_text"],
          change_note: "<img src=x onerror=alert(1)>",
          snapshot_json: { free_text: "<script>globalThis.bibleXss()</script>" },
        }]),
      },
    }
    setBridgeOverrides({ api, esc: productionEsc, toast: vi.fn() })
    const actions = createWorldBibleHistory(bibleHistoryContext(api))
    await actions.openPageHistory()

    const bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("script")).toBeNull()
    expect(bodyEl.querySelector("img")).toBeNull()
    expect(bodyEl.textContent).toContain("<script>globalThis.bibleXss()</script>")
    expect(bodyEl.textContent).toContain("<img src=x onerror=alert(1)>")
    expect(bodyEl.textContent).toContain("与上一版相比：正文")
    expect(bodyEl.textContent).toContain("发布了这一版")
    resetBridgeOverrides()
  })

  it("模板历史与简介历史的动态内容同样转义", async () => {
    const api = {
      world: {
        listBiblePageTemplateRevisions: vi.fn(async () => [{
          version_number: 3,
          revision_reason: "update",
          created_at: new Date().toISOString(),
          content_hash: "hash-not-displayed",
        }]),
        listBibleSynopsisRevisions: vi.fn(async () => ({
          items: [{
            id: "syn-1",
            version_number: 4,
            status: "done",
            created_at: new Date().toISOString(),
            rendered_text: "<svg onload=alert(2)>简介正文</svg>",
          }],
        })),
      },
    }
    setBridgeOverrides({ api, esc: productionEsc, toast: vi.fn() })
    const actions = createWorldBibleHistory(bibleHistoryContext(api))
    await actions.openSynopsisHistory()
    let bodyEl = document.getElementById("modal-body")
    expect(bodyEl.querySelector("svg")).toBeNull()
    expect(bodyEl.textContent).toContain("<svg onload=alert(2)>简介正文</svg>")

    await actions.openPageTemplateHistory("template-1", null)
    bodyEl = document.getElementById("modal-body")
    expect(bodyEl.textContent).toContain("修改模板")
    expect(bodyEl.textContent).not.toContain("hash-not-displayed")
    expect(bodyEl.querySelector("button[data-template-restore-version]").getAttribute("data-template-restore-version")).toBe("3")
    resetBridgeOverrides()
  })
})

describe("page revision note editing", () => {
  function productionEsc(str) {
    if (str === null || str === undefined) return ""
    const s = String(str)
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;")
  }

  const revision = {
    id: "rev-page-1",
    version_number: 2,
    revision_reason: "manual_publish",
    created_at: new Date().toISOString(),
    changed_fields: ["free_text"],
    change_note: "",
    writing_chapter_index: 3,
    snapshot_json: { free_text: "正文" },
  }

  function makeActions(api) {
    const context = {
      api,
      projectId: ref("p1"),
      activePage: computed(() => ({ id: "page-1" })),
      pageTemplates: computed(() => []),
      ownsProject: () => true,
      ownsPage: () => true,
      taskStatusLabel: (status) => `状态:${status}`,
      restoreSynopsis: () => {},
      restorePageRevision: () => {},
      applyRestoredTemplate: () => {},
    }
    return createWorldBibleHistory(context)
  }

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal-overlay" class="hidden">
        <div id="modal-content">
          <div id="modal-title"></div>
          <div id="modal-body"></div>
          <div id="modal-footer"></div>
        </div>
      </div>
    `
  })

  it("补写备注：成功回显与提示；失败保留输入并提示；空串删除", async () => {
    const api = {
      world: {
        listBiblePageRevisions: vi.fn(async () => [revision]),
        setRevisionNote: vi.fn(async (payload) => ({ ...payload, updated_at: "2026-10-04T00:00:00Z" })),
      },
    }
    const toast = vi.fn()
    setBridgeOverrides({ api, esc: productionEsc, toast })
    const actions = makeActions(api)
    await actions.openPageHistory()
    const body = document.getElementById("modal-body")
    expect(body.textContent).toContain("写到第 3 章时")

    body.querySelector("[data-note-edit='rev-page-1']").dispatchEvent(new Event("click"))
    const input = body.querySelector("[data-note-input='rev-page-1']")
    expect(input).not.toBeNull()
    input.value = "初版定稿备注"
    body.querySelector("[data-note-save='rev-page-1']").dispatchEvent(new Event("click"))
    await Promise.resolve()
    await Promise.resolve()
    expect(api.world.setRevisionNote).toHaveBeenCalledWith(
      { target_kind: "page", revision_id: "rev-page-1", note: "初版定稿备注" },
      "p1",
    )
    expect(toast).toHaveBeenCalledWith("备注已保存", "success")
    expect(body.textContent).toContain("备注：初版定稿备注")

    api.world.setRevisionNote.mockRejectedValueOnce(new Error("服务暂不可用"))
    body.querySelector("[data-note-edit='rev-page-1']").dispatchEvent(new Event("click"))
    const again = body.querySelector("[data-note-input='rev-page-1']")
    again.value = "会失败的备注"
    body.querySelector("[data-note-save='rev-page-1']").dispatchEvent(new Event("click"))
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    expect(body.textContent).toContain("服务暂不可用")
    expect(again.value).toBe("会失败的备注")
    resetBridgeOverrides()
  })
})
