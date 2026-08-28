import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const files = [
  "vue/views/outline/components/OutlineHeader.vue",
  "vue/views/world/WorldView.vue",
  "vue/views/world/components/WorldReviewTab.vue",
]
const expectedClickableCounts = new Map([
  ["vue/views/outline/components/OutlineHeader.vue", 4],
  ["vue/views/world/WorldView.vue", 3],
  ["vue/views/world/components/WorldReviewTab.vue", 4],
])
const root = dirname(dirname(fileURLToPath(import.meta.url)))

function openingTags(source) {
  return source.match(/<(?:button|span)\b[^>]*>/g) || []
}

function hasStaticClass(tag, className) {
  const value = tag.match(/(?:^|\s)class="([^"]*)"/)?.[1] || ""
  return value.split(/\s+/).includes(className)
}

describe("scoped subnav accessibility source contract", () => {
  it("clickable subnav items are native current-aware buttons", () => {
    for (const file of files) {
      const tags = openingTags(readFileSync(join(root, file), "utf8"))
      const subnav = tags.filter((tag) => hasStaticClass(tag, "subnav-item"))
      expect(subnav.filter((tag) => tag.startsWith("<span") && tag.includes("@click"))).toEqual([])
      const clickable = subnav.filter((tag) => tag.includes("@click"))
      expect(clickable).toHaveLength(expectedClickableCounts.get(file))
      for (const tag of clickable) {
        expect(tag.startsWith("<button")).toBe(true)
        expect(tag).toContain('type="button"')
        expect(tag).toContain("aria-current")
      }
    }
  })

  it("keeps outline navigation in one shared header", () => {
    const header = readFileSync(join(root, "vue/views/outline/components/OutlineHeader.vue"), "utf8")
    const scene = readFileSync(join(root, "vue/views/scene/SceneWorkbenchView.vue"), "utf8")
    expect(header).toContain('data-action="nav-scenes"')
    expect(scene).toContain('<OutlineHeader sub-view="scenes"')
    expect(scene).not.toContain('class="subnav"')
  })
})
