import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

beforeAll(async () => {
  globalThis.routes = {
    project: { subViews: [] },
    writing: { subViews: [] },
    rag: { subViews: ["search", "status"] },
  }
  await import("../commands.js")
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe("commands navigation lifecycle", () => {
  it("does not expose removed placeholder commands or registration", () => {
    expect(window.commands.getHelpText()).not.toMatch(/:(?:export|save|rag|context|generate)\b/)
    expect([
      ...window.commands.getSuggestions("export"),
      ...window.commands.getSuggestions("save"),
      ...window.commands.getSuggestions("rag"),
      ...window.commands.getSuggestions("context"),
      ...window.commands.getSuggestions("generate"),
    ]).toEqual([])
    expect(window.commands.getHelpText()).toContain(":search")
    expect(window.commands.getHelpText()).toContain("查找作品资料")
    expect(window.commands.register).toBeUndefined()
  })

  it("does not resolve a navigation command before router.navigate settles", async () => {
    let resolveNavigation
    globalThis.router.navigate.mockReturnValueOnce(new Promise((resolve) => { resolveNavigation = resolve }))
    let commandSettled = false

    const execution = window.commands.execute(":writing").then(() => { commandSettled = true })
    await Promise.resolve()
    expect(commandSettled).toBe(false)
    expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")

    resolveNavigation(true)
    await execution
    expect(commandSettled).toBe(true)
  })

  it("awaits search navigation and forwards the query", async () => {
    globalThis.router.navigate.mockResolvedValueOnce(true)
    await window.commands.execute("/旧王都")

    expect(globalThis.router.navigate).toHaveBeenCalledWith(
      "rag",
      "search",
      true,
      expect.any(URLSearchParams),
    )
    expect(globalThis.router.navigate.mock.calls[0][3].get("q")).toBe("旧王都")
  })

  it("uses an author-facing search command without exposing RAG", async () => {
    await window.commands.execute(":search 旧王都 王印")

    expect(globalThis.router.navigate).toHaveBeenCalledWith(
      "rag",
      "search",
      true,
      expect.any(URLSearchParams),
    )
    expect(globalThis.router.navigate.mock.calls[0][3].get("q")).toBe("旧王都 王印")
  })
})
