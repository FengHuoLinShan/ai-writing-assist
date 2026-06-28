import { test } from "@playwright/test"

const CASES = [
  "S1-STA-001 stale deleted project route should fall back safely",
  "S1-DNG-002 cancel permanent delete should keep project available",
]

test.describe("项目路径 chaos baseline", () => {
  for (const title of CASES) {
    test.skip(title, async () => {})
  }
})
