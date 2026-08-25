import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("Scene workbench spacing", () => {
  it("keeps outline tabs inset from their frame", () => {
    expect(styles).toMatch(
      /\.outline-scene-layout > \.outline-toolbar\s*\{[^}]*gap:\s*var\(--space-2\);[^}]*padding:\s*var\(--space-2\) var\(--space-3\);/s,
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

  it("keeps progress filters touchable and scene metadata readable", () => {
    expect(styles).toMatch(
      /\.scene-progress-filter,\s*\.world-hot-facet\s*\{[^}]*min-height:\s*44px;/s,
    )
    expect(styles).toMatch(
      /\.scene-workbench-row__meta\s*\{[^}]*font-size:\s*var\(--text-xs\);[^}]*line-height:\s*var\(--leading-normal\);/s,
    )
    expect(styles).toMatch(
      /\.scene-workbench-row__meta > span:not\(:last-child\)::after\s*\{[^}]*content:\s*"·";/s,
    )
    expect(styles).toMatch(
      /\.scene-workbench-row__summary\s*\{[^}]*font-size:\s*var\(--text-sm\);[^}]*line-height:\s*var\(--leading-normal\);/s,
    )
    for (const segment of ["current", "upcoming", "past", "unassigned"]) {
      expect(styles).toContain(`.scene-progress-filter--${segment}`)
      expect(styles).toContain(`.scene-progress-chip--${segment}`)
    }
  })

  it("keeps refresh feedback and empty-state actions readable without another card system", () => {
    expect(styles).toMatch(
      /\.scene-workbench-refresh\s*\{[^}]*min-height:\s*44px;[^}]*background:\s*var\(--accent-soft\);/s,
    )
    expect(styles).toMatch(
      /\.scene-workbench-empty\s*\{[^}]*min-height:\s*220px;[^}]*border:\s*1px dashed var\(--border\);/s,
    )
    expect(styles).toMatch(
      /\.scene-workbench-empty \.actions\s*\{[^}]*flex-wrap:\s*wrap;/s,
    )
  })

  it("uses one evenly spaced AI task stack with touchable mobile actions", () => {
    expect(styles).toMatch(
      /\.outline-task-status\s*\{[^}]*display:\s*grid;[^}]*gap:\s*var\(--space-2\);/s,
    )
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*\.outline-task-status \.workflow-progress__actions \.btn,[\s\S]*min-height:\s*44px;/s,
    )
  })
})
