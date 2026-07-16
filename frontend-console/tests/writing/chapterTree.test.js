/**
 * chapterTree 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createChapterTree } from "../../views/writing/chapterTree.js"
import { resetState, clearDocument } from "../helpers.js"

function escHtml(value) {
  if (value === null || value === undefined) return ""
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

function createTestTree(overrides = {}) {
  return createChapterTree({
    state: globalThis.state,
    api: globalThis.api,
    onSelect: vi.fn(),
    onSceneSelect: vi.fn(),
    onBulkChange: vi.fn(),
    esc: escHtml,
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createChapterTree", () => {
  it("load 加载章节列表和 Scene 列表", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 1200, version_number: 1 },
        { chapter_index: 2, title: "转折", word_count: 800, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene 1", chapter_ids: ["1"] },
    ])

    const tree = createTestTree()
    await tree.load()

    expect(tree._getChapterList()).toEqual([1, 2])
    expect(tree._getChapterMap()[1].title).toBe("开篇")
    expect(tree._getChapterMap()[1].wordcount).toBe(1200)
    expect(tree._getScenes()).toEqual([{ id: "s1", title: "Scene 1", chapter_ids: ["1"] }])
  })

  it("无章节时渲染空状态", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({ chapters: [] })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const tree = createTestTree()
    await tree.load()
    const html = tree.render()

    expect(html).toContain("开始创作")
    expect(html).toContain('data-action="new-chapter"')
  })

  it("有章节时渲染章节树", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 1200, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const tree = createTestTree()
    await tree.load()
    const html = tree.render()

    expect(html).toContain('data-action="prev-chapter"')
    expect(html).toContain('data-action="next-chapter"')
    expect(html).toContain("chapter-row")
    expect(html).toContain('aria-label="打开第 1 章：开篇，1,200 字"')
    expect(html).toContain("1,200 字")
  })

  it("按 Scene 分组渲染", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
        { chapter_index: 2, title: "过渡", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene 1", chapter_ids: ["1"] },
    ])

    const tree = createTestTree()
    await tree.load()
    const html = tree.render()

    expect(html).toContain("未归类")
    expect(html).toContain('data-scene-id="s1"')
    expect(html).toContain("Scene 1")
  })

  it("同章多 Scene 保留各自入口并显示精确字符范围", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 200, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      {
        id: "s1",
        title: "前半段",
        chapter_ids: ["1"],
        scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 100 }],
      },
      {
        id: "s2",
        title: "后半段",
        chapter_ids: ["1"],
        scene_chunks: [{ chapter_index: 1, start_offset: 100, end_offset: 200 }],
      },
    ])

    const tree = createTestTree()
    await tree.load()
    document.body.innerHTML = tree.render()

    expect(document.querySelectorAll('[data-action="select-chapter"][data-chapter="1"]')).toHaveLength(2)
    expect(document.body.textContent).toContain("第 1 章字符 1–100")
    expect(document.body.textContent).toContain("第 1 章字符 101–200")
  })

  it("HTML 转义动态内容防止 XSS", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "<script>alert(1)</script>", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const tree = createTestTree()
    await tree.load()
    const html = tree.render()

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).not.toContain("<script>alert(1)</script>")
  })

  it("点击章节触发 onSelect 回调", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const onSelect = vi.fn()
    const tree = createTestTree({ onSelect })
    await tree.load()

    document.body.innerHTML = tree.render()
    tree.bindEvents(document.body)

    document.querySelector('[data-action="select-chapter"]').click()

    expect(onSelect).toHaveBeenCalledWith(1)
  })

  it("点击 Scene 触发 onSceneSelect 回调并跳转首章", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
        { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene 1", chapter_ids: ["2", "1"] },
    ])

    const onSelect = vi.fn()
    const onSceneSelect = vi.fn()
    const tree = createTestTree({ onSelect, onSceneSelect })
    await tree.load()

    document.body.innerHTML = tree.render()
    tree.bindEvents(document.body)

    document.querySelector('[data-action="select-scene"]').click()

    expect(onSelect).toHaveBeenCalledWith(1)
    expect(onSceneSelect).toHaveBeenCalledWith("s1")
  })

  it("Scene 分组按最早章节和片段起点展示，不受导入顺序影响", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [4, 14, 53, 60].map((chapter_index) => ({
        chapter_index,
        title: `第 ${chapter_index} 章`,
        word_count: 100,
        version_number: 1,
      })),
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s60", title: "第六十章 Scene", scene_index: 2, chapter_ids: ["60"], scene_chunks: [{ chapter_index: 60, start_offset: 0, end_offset: 80 }] },
      { id: "s53-late", title: "第五十三章后段", scene_index: 4, chapter_ids: ["53"], scene_chunks: [{ chapter_index: 53, start_offset: 1200, end_offset: 1800 }] },
      { id: "s14", title: "第十四章 Scene", scene_index: 1, chapter_ids: ["14"], scene_chunks: [{ chapter_index: 14, start_offset: 300, end_offset: 900 }] },
      { id: "s4", title: "第四章 Scene", scene_index: 0, chapter_ids: ["4"], scene_chunks: [{ chapter_index: 4, start_offset: 0, end_offset: 500 }] },
      { id: "s53-early", title: "第五十三章前段", scene_index: 3, chapter_ids: ["53"], scene_chunks: [{ chapter_index: 53, start_offset: 20, end_offset: 800 }] },
    ])

    const tree = createTestTree()
    await tree.load()
    document.body.innerHTML = tree.render()

    const labels = [...document.querySelectorAll('[data-action="select-scene"]')]
      .map((node) => node.textContent.trim())
    expect(labels.map((label) => label.split(" · ")[0])).toEqual([
      "第四章 Scene",
      "第十四章 Scene",
      "第五十三章前段",
      "第五十三章后段",
      "第六十章 Scene",
    ])
  })

  it("Scene 分组三角按钮与标题均可折叠/展开", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
        { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene 1", chapter_ids: ["1", "2"] },
    ])

    const onSelect = vi.fn()
    const onSceneSelect = vi.fn()
    const tree = createTestTree({ onSelect, onSceneSelect })
    await tree.load()

    document.body.innerHTML = tree.render()
    tree.bindEvents(document.body)

    const toggle = document.querySelector('[data-action="toggle-scene-group"]')
    const chapters = document.querySelector(".scene-tree-chapters")
    expect(toggle.getAttribute("aria-expanded")).toBe("true")
    expect(chapters.style.display).toBe("block")

    // 三角按钮只折叠，不触发跳转回调
    toggle.click()
    expect(toggle.getAttribute("aria-expanded")).toBe("false")
    expect(chapters.style.display).toBe("none")
    expect(onSceneSelect).not.toHaveBeenCalled()

    document.body.innerHTML = tree.render()
    const rerenderedChapters = document.querySelector(".scene-tree-chapters")
    expect(rerenderedChapters.style.display).toBe("none")

    // Scene 标题点击：跳转并展开（需重渲染才能看到状态变化）
    tree.bindEvents(document.body)
    document.querySelector('[data-action="select-scene"]').click()
    expect(onSelect).toHaveBeenCalledWith(1)
    expect(onSceneSelect).toHaveBeenCalledWith("s1")
    document.body.innerHTML = tree.render()
    expect(document.querySelector(".scene-tree-chapters").style.display).toBe("block")

    // Scene 标题再次点击：跳转并折叠
    tree.bindEvents(document.body)
    document.querySelector('[data-action="select-scene"]').click()
    expect(onSelect).toHaveBeenCalledTimes(2)
    expect(onSceneSelect).toHaveBeenCalledTimes(2)
    document.body.innerHTML = tree.render()
    expect(document.querySelector(".scene-tree-chapters").style.display).toBe("none")
  })

  it("未归类分组标题点击只切换折叠不跳转", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
        { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([
      { id: "s1", title: "Scene 1", chapter_ids: ["1"] },
    ])

    const onSceneSelect = vi.fn()
    const tree = createTestTree({ onSceneSelect })
    tree._setCurrentChapter(2)
    await tree.load()

    document.body.innerHTML = tree.render()
    tree.bindEvents(document.body)

    const unassignedLabel = document.querySelector('[data-group-id="unassigned"].scene-tree-label')
    expect(unassignedLabel).not.toBeNull()
    expect(unassignedLabel.textContent).toBe("未归类")

    const unassignedChapters = document.querySelectorAll(".scene-tree-chapters")[0]
    expect(unassignedChapters.style.display).toBe("block")

    unassignedLabel.click()
    expect(unassignedChapters.style.display).toBe("none")
    expect(onSceneSelect).not.toHaveBeenCalled()
  })

  it("上下章按钮切换选中章节", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
        { chapter_index: 2, title: "转折", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const onSelect = vi.fn()
    const tree = createTestTree({ onSelect })
    tree._setCurrentChapter(1)
    await tree.load()

    document.body.innerHTML = tree.render()
    tree.bindEvents(document.body)

    document.querySelector('[data-action="next-chapter"]').click()

    expect(onSelect).toHaveBeenCalledWith(2)
  })

  it("清空批量选择触发 onBulkChange", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const onBulkChange = vi.fn()
    const tree = createTestTree({ onBulkChange })
    await tree.load()

    tree.clearSelection()

    expect(onBulkChange).toHaveBeenCalledWith("writing-chapters")
  })

  it("dispose 清理内部状态", async () => {
    state.currentProjectId = "p1"
    api.writing.listChapters.mockResolvedValue({
      chapters: [
        { chapter_index: 1, title: "开篇", word_count: 100, version_number: 1 },
      ],
    })
    api.outline.listScenesOrdered.mockResolvedValue([])

    const tree = createTestTree()
    tree._setCurrentChapter(1)
    await tree.load()

    tree.dispose()

    expect(tree._getChapterList()).toEqual([])
    expect(tree._getChapterMap()).toEqual({})
    expect(tree._getScenes()).toEqual([])
  })
})
