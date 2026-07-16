import { test } from "./fixtures.js"

const CASES = [
  "S4-REC-001 localStorage restore flow should preserve unsaved content after refresh",
  "S4-STA-001 switching scene should not leak stale scene card state",
  "S4-VAL-001 empty publish should remain blocked after recovery path",
]

test.describe("写作路径 chaos baseline", () => {
  for (const title of CASES) {
    test.skip(title, async () => {})
  }
})
