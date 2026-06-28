import { test } from "@playwright/test"

const CASES = [
  "S5-DNG-001 cancelling merge or rollback should keep entity list unchanged",
  "S6-STA-002 deleting or reordering scene should refresh writing keepalive side state",
  "S6-IDM-001 duplicate outline generate range should surface confirmation instead of silent overwrite",
]

test.describe("世界与大纲 chaos baseline", () => {
  for (const title of CASES) {
    test.skip(title, async () => {})
  }
})
