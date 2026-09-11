import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

const root = resolve(import.meta.dirname, "..")
const styles = readFileSync(resolve(root, "styles.css"), "utf8")
const assistant = readFileSync(resolve(root, "vue/components/ProjectAssistant.vue"), "utf8")

describe("UI size repair contracts", () => {
  it("keeps scrolling and narrow layouts with their owning components", () => {
    expect(styles).toMatch(/\.recycle-bin__list\s*\{[^}]*flex:\s*1;[^}]*overflow-y:\s*auto/s)
    expect(styles).toMatch(/@media \(min-width: 761px\) and \(max-width: 1099px\)[\s\S]*\.data-table\.table-card-list\s*\{[^}]*overflow-x:\s*auto/s)
    expect(styles).toMatch(/\.collapsible\.open \.collapsible-body\s*\{[^}]*max-height:\s*none/s)
    expect(styles).not.toContain("max-height: 2000px")
  })

  it("keeps version diff side markers connected to row-level styles", () => {
    expect(styles).toMatch(/\.writing-version-diff__cell\[data-side="右"\]\s*\{[^}]*border-left:/s)
    expect(styles).toMatch(/\.writing-version-diff__cell--delete\[data-side="左"\]\s*\{[^}]*background:/s)
    expect(styles).toMatch(/\.writing-version-diff__cell--insert\[data-side="右"\]\s*\{[^}]*background:/s)
  })

  it("uses dynamic viewport and safe-area sizing for fixed UI", () => {
    expect(styles).toMatch(/#sidebar\s*\{[\s\S]*?height:\s*calc\(64px \+ env\(safe-area-inset-bottom\)\)/)
    expect(styles).toMatch(/\.main-layout--immersive #workspace\s*\{[^}]*padding-bottom:\s*0/s)
    expect(styles).toMatch(/\.modal-content,[\s\S]*?max-height:\s*80dvh/s)
    expect(styles).toMatch(/\.owner-ai-drawer\s*\{[\s\S]*?bottom:calc\(64px \+ env\(safe-area-inset-bottom\)\)/)
  })

  it("switches the assistant to its existing overlay before it squeezes the workspace", () => {
    expect(assistant).toContain('matchMedia?.("(max-width: 1100px)")')
    expect(assistant).toContain("@media(max-width:1100px)")
  })
})
