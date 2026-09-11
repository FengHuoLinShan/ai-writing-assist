import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { expect, it } from "vitest"

it("shows the same-budget resume only when the server marks it recoverable", () => {
  const source = readFileSync(resolve(import.meta.dirname, "../../../vue/components/ProjectAssistant.vue"), "utf8")

  expect(source).toContain('v-if="state.run.can_resume"')
  expect(source).not.toContain('v-if="state.run.status === \'failed\'"')
})
