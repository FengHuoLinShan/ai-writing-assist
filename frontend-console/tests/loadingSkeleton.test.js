import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("workspace loading skeleton", () => {
  it("disables skeleton shimmer when reduced motion is requested", () => {
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.skeleton\s*\{\s*animation:\s*none;/s,
    )
  })
})
