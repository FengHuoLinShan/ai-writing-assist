import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const source = readFileSync(join(root, "vue/views/map/MapWorkspaceView.vue"), "utf8")
const titleButton = '<button type="button" class="map-dynamic-title map-open-dynamic-item" data-action="map-open-dynamic-item" @click.stop="modalController.showDynamicItem(item)">{{ dynamicTitle(item) }}</button>'

describe("map dynamic-card accessibility source contract", () => {
  it("keeps all four detail-card surfaces keyboard reachable without making the article interactive", () => {
    for (const section of ["动态队列", "历史记录", "map-live-current-facts", "map-lens-context"]) {
      const start = source.indexOf(section)
      expect(start, `missing ${section}`).toBeGreaterThanOrEqual(0)
      const card = source.slice(start, source.indexOf("</article>", start) + "</article>".length)
      expect(card).toContain(titleButton)
      expect(card).toContain('@click="modalController.showDynamicItem(item)"')
      expect(card).not.toMatch(/<article[^>]*(?:role=|tabindex=|@key)/)
    }
    expect(source.match(new RegExp(titleButton.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"))).toHaveLength(4)
  })
})
