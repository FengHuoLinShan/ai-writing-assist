import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import ChapterOrderDialog from "../../../vue/views/writing/components/ChapterOrderDialog.vue"

const dialogPrototype = HTMLDialogElement.prototype
let originalShowModal
let originalClose
let wrapper

const preview = {
  receipt_id: "receipt-1",
  preview_hash: "a".repeat(64),
  source_order: [1, 2, 3],
  target_order: [2, 1, 3],
  moves: [
    { from_chapter_index: 1, to_chapter_index: 2, title: "旧港", version_count: 2 },
    { from_chapter_index: 2, to_chapter_index: 1, title: "来信", version_count: 1 },
  ],
  story_impact: {
    scene_binding_count: 1,
    scene_span_count: 1,
    fact_event_count: 1,
    plan_review_count: 1,
    snapshot_count: 0,
    scene_checkpoint_count: 0,
    scene_snapshot_count: 0,
    scene_summary_count: 0,
    plan_review_refs: [{
      target_type: "plot_thread",
      target_id: "internal-plan-id",
      label: "旧船线索",
      before: { start_chapter: 1 },
      after: { start_chapter: 2 },
    }],
    blockers: [],
  },
}

function mountDialog() {
  return mount(ChapterOrderDialog, {
    attachTo: document.body,
    props: {
      open: true,
      projectId: "project-1",
      chapterList: [1, 2, 3],
      chapters: {
        1: { title: "旧港", word_count: 1200 },
        2: { title: "来信", word_count: 900 },
        3: { title: "潮汐", word_count: 1400 },
      },
      selectedChapter: 2,
    },
  })
}

describe("ChapterOrderDialog", () => {
  let api

  beforeEach(() => {
    originalShowModal = dialogPrototype.showModal
    originalClose = dialogPrototype.close
    dialogPrototype.showModal = function showModal() { this.setAttribute("open", "") }
    dialogPrototype.close = function close() {
      this.removeAttribute("open")
      this.dispatchEvent(new Event("close"))
    }
    api = {
      writing: {
        previewChapterOrder: vi.fn(async () => preview),
        confirmChapterOrder: vi.fn().mockRejectedValue(new Error("预览已变化，请重新核对")),
        listChapterOrderHistory: vi.fn(async () => ({ items: [] })),
        previewChapterOrderRestore: vi.fn(),
        restoreChapterOrder: vi.fn(),
      },
    }
    setBridgeOverrides({ api })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    resetBridgeOverrides()
    dialogPrototype.showModal = originalShowModal
    dialogPrototype.close = originalClose
    document.body.replaceChildren()
    vi.restoreAllMocks()
  })

  it("预览并确认真实章节顺序，失败后保留作者选择且切换项目时禁用提交", async () => {
    wrapper = mountDialog()
    await flushPromises()

    await wrapper.get('[aria-label="第 2 章上移"]').trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "预览影响").trigger("click")
    await flushPromises()

    expect(api.writing.previewChapterOrder).toHaveBeenCalledWith("project-1", [2, 1, 3])
    expect(wrapper.text()).toContain("第 1 章 → 第 2 章")
    expect(wrapper.text()).toContain("这些剧情安排需要重新核对")
    expect(wrapper.text()).not.toContain("internal-plan-id")

    await wrapper.findAll("button").find((button) => button.text() === "确认并重排章节").trigger("click")
    await flushPromises()
    expect(api.writing.confirmChapterOrder).toHaveBeenCalledWith(
      "project-1",
      "receipt-1",
      "a".repeat(64),
    )
    expect(wrapper.get('[role="alert"]').text()).toContain("预览已变化")
    expect(wrapper.get(".chapter-order-list li").text()).toContain("第 2 章")

    await wrapper.setProps({ projectId: "project-2" })
    expect(wrapper.get('[role="alert"]').text()).toContain("当前项目已切换")
    expect(wrapper.findAll("button").find((button) => button.text() === "确认并重排章节").attributes("disabled")).toBeDefined()
  })

  it("恢复预览发现重排后的新来源时不提供覆盖确认", async () => {
    api.writing.listChapterOrderHistory.mockResolvedValue({
      items: [{
        receipt_id: "receipt-old",
        status: "executed",
        source_order: [1, 2],
        target_order: [2, 1],
        preview_hash: "b".repeat(64),
        story_impact: {},
        can_restore: true,
        created_at: "2026-10-16T00:00:00Z",
      }],
    })
    api.writing.previewChapterOrderRestore.mockResolvedValue({
      receipt_id: "receipt-old",
      status: "executed",
      can_restore: false,
      restore_preview_hash: "c".repeat(64),
      chapter_map: { 1: 2, 2: 1 },
      story_impact: {},
      blockers: [{ kind: "writing_source_changed", message: "重排后作者已有新编辑" }],
    })
    wrapper = mount(ChapterOrderDialog, {
      attachTo: document.body,
      props: {
        open: true,
        projectId: "project-1",
        chapterList: [1, 2],
        chapters: {},
      },
    })
    await flushPromises()

    await wrapper.findAll("button").find((button) => button.text() === "历史与恢复").trigger("click")
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "预览恢复").trigger("click")
    await flushPromises()

    expect(api.writing.previewChapterOrderRestore).toHaveBeenCalledWith("project-1", "receipt-old")
    expect(wrapper.text()).toContain("当前来源有变化")
    expect(wrapper.text()).toContain("重排后作者已有新编辑")
    expect(wrapper.findAll("button").some((button) => button.text() === "确认恢复章节顺序")).toBe(false)
    expect(api.writing.restoreChapterOrder).not.toHaveBeenCalled()
  })

  it("恢复成功后按原回执通知写作页重载当前章节", async () => {
    api.writing.listChapterOrderHistory.mockResolvedValue({
      items: [{
        receipt_id: "receipt-old",
        status: "executed",
        source_order: [1, 2],
        target_order: [2, 1],
        can_restore: true,
      }],
    })
    api.writing.previewChapterOrderRestore.mockResolvedValue({
      receipt_id: "receipt-old",
      can_restore: true,
      restore_preview_hash: "d".repeat(64),
      blockers: [],
    })
    api.writing.restoreChapterOrder.mockResolvedValue({
      receipt_id: "receipt-old",
      status: "restored",
      chapter_map: { 1: 2, 2: 1 },
    })
    wrapper = mountDialog()
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "历史与恢复").trigger("click")
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "预览恢复").trigger("click")
    await flushPromises()
    await wrapper.findAll("button").find((button) => button.text() === "确认恢复章节顺序").trigger("click")
    await flushPromises()

    expect(api.writing.restoreChapterOrder).toHaveBeenCalledWith(
      "project-1", "receipt-old", "d".repeat(64),
    )
    expect(wrapper.emitted("completed")[0][0]).toMatchObject({
      restored: true,
      projectId: "project-1",
      selectedChapter: 2,
      result: { status: "restored" },
    })
  })
})
