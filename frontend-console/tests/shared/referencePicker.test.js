import { beforeEach, describe, expect, it, vi } from "vitest"

import { createReferencePicker, normalizeReferenceItem } from "../../shared/referencePicker.js"

function mount(options = {}) {
  document.body.innerHTML = '<div id="picker"></div>'
  return createReferencePicker({
    root: document.getElementById("picker"),
    projectId: "project-1",
    sources: [{
      kind: "entity",
      label: "世界对象",
      search: vi.fn().mockResolvedValue([
        { id: "e1", label: "王都", description: "地点 · 已采用" },
        { id: "e2", label: "王都", description: "组织 · 已采用" },
      ]),
    }],
    debounceMs: 0,
    ...options,
  })
}

beforeEach(() => {
  document.body.innerHTML = ""
})

describe("referencePicker", () => {
  it("normalizes references without exposing ids as labels", () => {
    expect(normalizeReferenceItem({ entity_id: "e1", name: "克莱恩" }, "character")).toEqual({
      kind: "character",
      id: "e1",
      label: "克莱恩",
      description: "",
      status: "",
      unavailable: false,
    })
    expect(normalizeReferenceItem({ id: "missing-label" }, "entity")).toEqual(expect.objectContaining({
      id: "missing-label",
      label: "不可用引用",
      unavailable: true,
    }))
  })

  it("searches by name, disambiguates duplicate labels and keeps ids as values", async () => {
    const onChange = vi.fn()
    const picker = mount({ onChange })
    const input = document.querySelector("[data-reference-query]")
    input.value = "王都"
    input.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 5))

    const options = document.querySelectorAll("[data-reference-result]")
    expect(options).toHaveLength(2)
    expect(options[0].textContent).toContain("地点 · 已采用")
    options[0].click()

    expect(picker.getRefs()).toEqual([{ kind: "entity", id: "e1" }])
    expect(document.querySelector("[data-reference-selected]").textContent).toContain("王都")
    expect(onChange).toHaveBeenCalled()
  })

  it("supports keyboard selection and enforces multi-select limits", async () => {
    const picker = mount({ mode: "multiple", maxItems: 1 })
    const input = document.querySelector("[data-reference-query]")
    input.dispatchEvent(new Event("focus"))
    await new Promise((resolve) => setTimeout(resolve, 5))
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }))
    expect(picker.getRefs()).toEqual([{ kind: "entity", id: "e1" }])

    input.dispatchEvent(new Event("focus"))
    await new Promise((resolve) => setTimeout(resolve, 5))
    document.querySelector("[data-reference-result]")?.click()
    expect(picker.getRefs()).toHaveLength(1)
    expect(document.querySelector("[data-reference-status]").textContent).toContain("最多选择 1 项")
  })

  it("replaces an existing single selection without treating it as a full multi-select", async () => {
    const picker = mount({
      initialItems: [{ kind: "entity", id: "e1", label: "旧王都" }],
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockResolvedValue([{ id: "e2", label: "新王都" }]),
      }],
    })
    const input = document.querySelector("[data-reference-query]")
    input.dispatchEvent(new Event("focus"))
    await new Promise((resolve) => setTimeout(resolve, 5))
    document.querySelector("[data-reference-result]").click()

    expect(picker.getRefs()).toEqual([{ kind: "entity", id: "e2" }])
    expect(document.querySelector("[data-reference-selected]").textContent).toContain("新王都")
    expect(document.querySelector("[data-reference-status]").textContent).not.toContain("最多选择")
  })

  it("ignores late searches and clears selections when the project changes", async () => {
    let resolveFirst
    const first = new Promise((resolve) => { resolveFirst = resolve })
    const search = vi.fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce([{ id: "new", label: "新项目对象" }])
    const picker = mount({
      initialItems: [{ kind: "entity", id: "old", label: "旧项目对象" }],
      sources: [{ kind: "entity", label: "世界对象", search }],
    })
    const input = document.querySelector("[data-reference-query]")
    input.value = "旧"
    input.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 1))
    picker.setProjectId("project-2")
    input.value = "新"
    input.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 5))
    resolveFirst([{ id: "late", label: "晚到旧对象" }])
    await Promise.resolve()

    expect(picker.getRefs()).toEqual([])
    expect(document.querySelector("[data-reference-results]").textContent).toContain("新项目对象")
    expect(document.querySelector("[data-reference-results]").textContent).not.toContain("晚到旧对象")
  })

  it("aborts an in-flight search as soon as the query changes during debounce", async () => {
    let resolveFirst
    let firstSignal
    const first = new Promise((resolve) => { resolveFirst = resolve })
    const search = vi.fn()
      .mockImplementationOnce((_query, context) => {
        firstSignal = context.signal
        return first
      })
      .mockResolvedValueOnce([{ id: "fresh", label: "新结果" }])
    mount({ sources: [{ kind: "entity", label: "世界对象", search }] })
    const input = document.querySelector("[data-reference-query]")
    input.value = "旧查询"
    input.dispatchEvent(new Event("input"))
    await new Promise((resolve) => setTimeout(resolve, 1))

    input.value = "新查询"
    input.dispatchEvent(new Event("input"))
    expect(firstSignal.aborted).toBe(true)
    resolveFirst([{ id: "late", label: "旧结果" }])
    await new Promise((resolve) => setTimeout(resolve, 5))

    expect(document.querySelector("[data-reference-results]").textContent).toContain("新结果")
    expect(document.querySelector("[data-reference-results]").textContent).not.toContain("旧结果")
  })

  it("does not write a late resolve result after the project changes", async () => {
    let finishResolve
    let resolveSignal
    const pending = new Promise((resolve) => { finishResolve = resolve })
    const picker = mount({
      initialItems: [{ kind: "entity", id: "old", label: "旧选择" }],
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockResolvedValue([]),
        resolve: vi.fn().mockImplementation((_ids, context) => {
          resolveSignal = context.signal
          return pending
        }),
      }],
    })
    const resolving = picker.resolve([{ kind: "entity", id: "e1" }])
    await Promise.resolve()
    picker.setProjectId("project-2")
    finishResolve([{ id: "e1", label: "旧项目解析结果" }])

    await expect(resolving).resolves.toEqual([])
    expect(resolveSignal.aborted).toBe(true)
    expect(picker.getRefs()).toEqual([])
    expect(document.querySelector("[data-reference-selected]").textContent).not.toContain("旧项目解析结果")
  })

  it("keeps unresolved references visible until the author removes them", async () => {
    const picker = mount({
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockResolvedValue([]),
        resolve: vi.fn().mockResolvedValue([]),
      }],
    })
    await picker.resolve([{ kind: "entity", id: "missing" }])
    expect(picker.getRefs()).toEqual([{ kind: "entity", id: "missing" }])
    expect(document.querySelector("[data-reference-selected]").textContent).toContain("不可用引用")
  })

  it("opens available selected cards without treating unavailable refs as links", async () => {
    const onOpen = vi.fn()
    const picker = mount({
      mode: "multiple",
      onOpen,
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockResolvedValue([]),
        resolve: vi.fn().mockResolvedValue([
          { id: "e1", label: "北境商会" },
          { id: "e2", label: "不可用引用", unavailable: true },
        ]),
      }],
    })

    await picker.resolve([
      { kind: "entity", id: "e1" },
      { kind: "entity", id: "e2" },
    ])
    expect(document.querySelectorAll("[data-reference-open]")).toHaveLength(1)
    document.querySelector("[data-reference-open]").click()

    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "e1", label: "北境商会" }))
  })

  it("shows unavailable search results but skips them for keyboard selection", async () => {
    const picker = mount({
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockResolvedValue([
          { id: "archived", label: "旧王都", unavailable: true },
          { id: "active", label: "新王都" },
        ]),
      }],
    })
    const input = document.querySelector("[data-reference-query]")
    input.dispatchEvent(new Event("focus"))
    await new Promise((resolve) => setTimeout(resolve, 5))

    const options = document.querySelectorAll("[data-reference-result]")
    expect(options[0].disabled).toBe(true)
    expect(options[0].getAttribute("aria-disabled")).toBe("true")
    expect(input.getAttribute("aria-activedescendant")).toBe(options[1].id)
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }))
    expect(picker.getRefs()).toEqual([{ kind: "entity", id: "active" }])
  })

  it("aborts pending work and removes persistent listeners when destroyed", async () => {
    let finishSearch
    let searchSignal
    const pending = new Promise((resolve) => { finishSearch = resolve })
    const picker = mount({
      sources: [{
        kind: "entity",
        label: "世界对象",
        search: vi.fn().mockImplementation((_query, context) => {
          searchSignal = context.signal
          return pending
        }),
      }],
    })
    const input = document.querySelector("[data-reference-query]")
    input.dispatchEvent(new Event("focus"))
    await new Promise((resolve) => setTimeout(resolve, 1))
    picker.destroy()

    expect(searchSignal.aborted).toBe(true)
    expect(document.getElementById("picker").classList.contains("reference-picker")).toBe(false)
    input.dispatchEvent(new Event("focus"))
    finishSearch([{ id: "late", label: "晚到结果" }])
    await Promise.resolve()
    expect(document.getElementById("picker").innerHTML).toBe("")
  })
})
