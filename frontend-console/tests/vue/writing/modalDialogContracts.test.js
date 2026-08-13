import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick, reactive } from "vue"
import AutoExtractionDialog from "../../../vue/views/writing/components/AutoExtractionDialog.vue"
import ConflictDetailDialog from "../../../vue/views/writing/components/ConflictDetailDialog.vue"
import ConflictOptionsDialog from "../../../vue/views/writing/components/ConflictOptionsDialog.vue"
import DeepImportAuditDialog from "../../../vue/views/writing/components/DeepImportAuditDialog.vue"
import VersionHistoryDialog from "../../../vue/views/writing/components/VersionHistoryDialog.vue"

enableAutoUnmount(afterEach)
beforeEach(() => { document.body.innerHTML = "" })

function mountInShell(Component, props) {
  const shell = document.createElement("div")
  shell.className = "vue-shell-root"
  const opener = document.createElement("button")
  opener.textContent = "打开"
  const host = document.createElement("div")
  shell.append(opener, host)
  document.body.appendChild(shell)
  opener.focus()
  return { wrapper: mount(Component, { attachTo: host, props }), opener }
}

const detailModel = () => reactive({
  open: true,
  busy: false,
  error: null,
  sourcePreview: null,
  check: {
    id: "check-1",
    chapter_index: 1,
    ai_review_status: "done",
    items: [{
      id: "item-1",
      kind: "forbidden_present",
      severity: "low",
      status: "open",
      source_module: "world",
      location_json: {},
    }],
  },
})

const dialogs = [
  ["AutoExtraction", AutoExtractionDialog, () => ({ model: reactive({ open: true, busy: false, stage: "deep", start: 1, end: 2, highQuality: false }) }), "自动提取"],
  ["DeepImportAudit", DeepImportAuditDialog, () => ({ open: true, progress: null }), "深度导入快照状态"],
  ["ConflictOptions", ConflictOptionsDialog, () => ({ model: reactive({ open: true, includeCandidates: false }) }), "剧情设定冲突检查选项"],
  ["ConflictDetail", ConflictDetailDialog, () => ({ model: detailModel() }), "剧情设定冲突检查"],
  ["VersionHistory", VersionHistoryDialog, () => ({
    model: reactive({ open: true, loading: false, diffOpen: false, leftId: null, rightId: null, error: null }),
    versions: [{ id: "v1", version_number: 1, status: "draft" }],
  }), "版本历史"],
]

describe("writing modal dialog contracts", () => {
  it.each(dialogs)("%s keeps its dialog, accessible-name, overlay, and button contracts", async (_name, Component, propsFactory, stableName) => {
    const { wrapper } = mountInShell(Component, propsFactory())
    await nextTick()
    const dialog = wrapper.get(".modal-content[role='dialog']")
    const label = document.getElementById(dialog.attributes("aria-labelledby"))
    expect(dialog.attributes("aria-modal")).toBe("true")
    expect(dialog.attributes("aria-label")).toBe(stableName)
    expect(label?.textContent).toBe(stableName)
    expect(wrapper.get(".modal-overlay").attributes("role")).toBeUndefined()
    expect(wrapper.get(".modal-overlay").attributes("aria-modal")).toBeUndefined()
    expect(wrapper.findAll("button").every((button) => button.attributes("type") === "button")).toBe(true)
  })

  it("moves AutoExtraction and ConflictOptions focus into their body controls", async () => {
    const auto = mountInShell(AutoExtractionDialog, {
      model: reactive({ open: true, busy: false, stage: "deep", start: 1, end: 2, highQuality: false }),
    })
    await nextTick()
    expect(document.activeElement).toBe(auto.wrapper.get(".modal-body input").element)
    auto.wrapper.unmount()

    const options = mountInShell(ConflictOptionsDialog, { model: reactive({ open: true, includeCandidates: false }) })
    await nextTick()
    expect(document.activeElement).toBe(options.wrapper.get(".modal-body input").element)
  })

  it("moves DeepImportAudit focus to its close control when the read-only body has no controls", async () => {
    const { wrapper } = mountInShell(DeepImportAuditDialog, { open: true, progress: null })
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('[aria-label="关闭"]').element)
  })

  it("lets authors leave a busy ConflictDetail while its task continues in the page card", async () => {
    const model = detailModel()
    model.busy = true
    const { wrapper } = mountInShell(ConflictDetailDialog, { model })
    await nextTick()
    const busyEscape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(busyEscape)
    expect(busyEscape.defaultPrevented).toBe(true)
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("closes VersionHistory with Escape using the same state reset as its close button", async () => {
    const model = reactive({ open: true, loading: false, diffOpen: true, leftId: null, rightId: null, error: null })
    const { wrapper } = mountInShell(VersionHistoryDialog, { model, versions: [] })
    await nextTick()
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })
    wrapper.get(".modal-overlay").element.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(true)
    expect(model.open).toBe(false)
    expect(model.diffOpen).toBe(false)
  })
})
