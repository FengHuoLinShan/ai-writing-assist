import { test, expect } from "@playwright/test"

const PLACEHOLDER_SCENARIOS = [
  "S7-DEG-001 degraded rag retrieval should remain visible in UI warning state",
  "S8-STA-001 context render should not leak hidden truth across reveal mode changes",
  "S8-DEG-001 aggressive budget trimming should remain observable and non-crashing",
]

test.describe("RAG 与上下文 chaos placeholders", () => {
  test("placeholder metadata is documented and does not count as product coverage", () => {
    expect(PLACEHOLDER_SCENARIOS).toHaveLength(3)
  })
})
