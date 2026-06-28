import { test } from "@playwright/test"

const CASES = [
  "S2-REC-001 import success then immediate refresh should recover imported chapter tree",
  "S3-REC-001 async deep import should recover after browser close and reopen",
  "S3-DEG-001 partial deep import result should render warning path instead of full success only",
]

test.describe("导入与深度导入 chaos baseline", () => {
  for (const title of CASES) {
    test.skip(title, async () => {})
  }
})
