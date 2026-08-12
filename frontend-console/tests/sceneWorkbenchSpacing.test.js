import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("Scene workbench spacing", () => {
  it("keeps outline tabs inset from their frame", () => {
    expect(styles).toMatch(
      /\.outline-scene-layout > \.subnav\s*\{[^}]*gap:\s*var\(--space-2\);[^}]*padding:\s*var\(--space-2\) var\(--space-3\);/s,
    )
  })

  it("uses the shared panel inset for dense outline controls and rows", () => {
    for (const selector of [
      "scene-management-filters",
      "scene-fusion-toolbar",
      "scene-health-filter",
      "scene-workbench-row",
    ]) {
      expect(styles).toMatch(
        new RegExp(`\\.${selector}\\s*\\{[^}]*padding:\\s*var\\(--space-3\\) var\\(--space-4\\);`, "s"),
      )
    }
  })

  it("moves the health breakdown below its title on narrow screens", () => {
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.scene-health-filter\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;/s,
    )
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.scene-health-filter small\s*\{[^}]*grid-column:\s*1 \/ -1;[^}]*margin-left:\s*0;/s,
    )
  })

  it("aligns the health explanation with card content", () => {
    expect(styles).toMatch(
      /\.scene-health-count-note\s*\{[^}]*margin:\s*0;[^}]*padding-inline:\s*var\(--space-4\);/s,
    )
  })
})
