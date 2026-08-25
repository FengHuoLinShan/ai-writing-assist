import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import RagEvidenceDrawer from "../../../vue/views/rag/components/RagEvidenceDrawer.vue"

enableAutoUnmount(afterEach)
beforeEach(() => { document.body.innerHTML = "" })

function mountDrawer(props) {
  const opener = document.createElement("button")
  opener.textContent = "阅读原文"
  const host = document.createElement("div")
  document.body.append(opener, host)
  opener.focus()
  return {
    opener,
    wrapper: mount(RagEvidenceDrawer, { attachTo: host, props: { open: true, ...props } }),
  }
}

describe("RagEvidenceDrawer", () => {
  it("提供模态语义、键盘关闭并把焦点还给原入口", async () => {
    const { opener, wrapper } = mountDrawer({
      content: {
        type: "chapter",
        title: "第一章",
        chapterIndex: 1,
        versionNumber: 2,
        before: "旧塔的",
        mark: "铜铃",
        after: "响起。",
        warnings: [],
      },
    })
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    const close = document.querySelector('[data-action="close-drawer"]')
    expect(dialog?.getAttribute("aria-modal")).toBe("true")
    expect(dialog?.getAttribute("aria-labelledby")).toBe("rag-evidence-drawer-title")
    expect(document.activeElement).toBe(close)
    document.querySelector(".rag-evidence-overlay")?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    )
    expect(wrapper.emitted("close")).toHaveLength(1)

    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.activeElement).toBe(opener)
  })

  it("失败态仍可关闭，对象详情不再暴露原始 JSON", async () => {
    const { wrapper } = mountDrawer({
      content: {
        type: "object",
        title: "旧塔",
        item: { summary: "临海的废弃瞭望塔", entity_id: "internal-id" },
        evidenceCount: 3,
        isWorldObject: true,
        warnings: [],
      },
    })
    await nextTick()
    expect(document.getElementById("rag-evidence-drawer")?.textContent).toContain("摘要")
    expect(document.getElementById("rag-evidence-drawer")?.textContent).toContain("临海的废弃瞭望塔")
    expect(document.getElementById("rag-evidence-drawer")?.textContent).not.toContain("entity_id")
    expect(document.getElementById("rag-evidence-drawer")?.textContent).not.toContain("internal-id")

    await wrapper.setProps({ content: { type: "error", message: "读取失败，请稍后重试" } })
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("读取失败")
    expect(document.querySelector('[data-action="close-drawer"]')).not.toBeNull()
  })
})
