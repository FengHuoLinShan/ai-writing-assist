import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("workspace loading skeleton", () => {
  it("keeps the initial application loader accessible and its bars decorative", () => {
    const workspaceMarkup = indexHtml.match(
      /<div id="workspace-content">[\s\S]*?<\/main>/,
    )?.[0] ?? ""
    const template = document.createElement("template")
    template.innerHTML = workspaceMarkup
    const status = template.content.querySelector("#workspace-content > .loading-skeleton")

    expect(status?.getAttribute("role")).toBe("status")
    expect(status?.getAttribute("aria-live")).toBe("polite")
    expect(status?.getAttribute("aria-busy")).toBe("true")
    expect(status?.querySelector(".sr-only")?.textContent).toBe("应用加载中...")
    expect(status?.querySelectorAll(".skeleton")).toHaveLength(4)
    expect([...status.querySelectorAll(".skeleton")].every((node) => (
      node.getAttribute("aria-hidden") === "true"
    ))).toBe(true)
  })

  it("disables skeleton shimmer when reduced motion is requested", () => {
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.skeleton\s*\{\s*animation:\s*none;/s,
    )
  })
})
