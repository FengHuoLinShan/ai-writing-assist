import { test } from "@playwright/test"

const CASES = [
  "M4-REC-001 stale recent map should fall back to overview with visible warning",
  "M5-REC-001 scene filter clear should keep map state and query context synchronized",
  "M6-STA-001 focus toggle after territory edits should preserve non-territory fields",
]

test.describe("地图路径 chaos baseline", () => {
  for (const title of CASES) {
    test.skip(title, async () => {})
  }
})
