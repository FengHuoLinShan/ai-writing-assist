import { describe, expect, it } from "vitest"
import { mergePersistedChunk } from "../../../vue/views/interaction/persistedStream.js"

describe("persisted Unicode stream", () => {
  it("deduplicates replay and appends only the overlapping tail", () => {
    const start = mergePersistedChunk("", 0, { text: "甲😀乙", offset: 3 })
    expect(start).toEqual({ text: "甲😀乙", offset: 3, needsSnapshot: false })
    expect(mergePersistedChunk(start.text, 3, { text: "甲😀乙", offset: 3 })).toEqual(start)
    expect(mergePersistedChunk(start.text, 3, { text: "😀乙丙", offset: 4 }))
      .toEqual({ text: "甲😀乙丙", offset: 4, needsSnapshot: false })
    expect(mergePersistedChunk("甲😀乙丙", 4, { text: "😀乙", offset: 3 }).text).toBe("甲😀乙丙")
  })
  it("requires the authoritative snapshot for gaps or conflicting replays", () => {
    expect(mergePersistedChunk("甲😀", 2, { text: "丁", offset: 4 }).needsSnapshot).toBe(true)
    expect(mergePersistedChunk("甲😀", 2, { text: "乙", offset: 2 }).needsSnapshot).toBe(true)
    expect(mergePersistedChunk("", 0, { text: "甲", offset: -1 }).needsSnapshot).toBe(true)
  })
  it("accepts reset followed by replay without splitting a surrogate pair", () => {
    expect(mergePersistedChunk("", 0, { text: "😀甲🪶", offset: 3 }).text).toBe("😀甲🪶")
  })
})
