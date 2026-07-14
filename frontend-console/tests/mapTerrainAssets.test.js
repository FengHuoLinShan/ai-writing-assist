import { describe, expect, it } from "vitest"

import {
  getTerrainAsset,
  TERRAIN_ASSETS,
  TERRAIN_PACKS,
  TERRAIN_PRESETS,
} from "../views/mapTerrainAssets.js"
import renderEditPanel from "../views/mapEditPanel.js"
import { mapState } from "../views/mapState.js"

describe("map terrain asset packs", () => {
  it("ships three built-in packs and three presets", () => {
    expect(TERRAIN_PACKS.map((pack) => pack.pack_key)).toEqual([
      "nature",
      "city_transport",
      "fantasy_crisis",
    ])
    expect(Object.keys(TERRAIN_PRESETS)).toEqual([
      "standard",
      "soft",
      "high_contrast",
    ])
    expect(TERRAIN_ASSETS.length).toBeGreaterThanOrEqual(29)
  })

  it("keeps unknown keys visible instead of silently mapping to mountain", () => {
    const unknown = getTerrainAsset("legacy-missing-key")
    expect(unknown.unknown).toBe(true)
    expect(unknown.label).toBe("未知素材")
    expect(unknown.original_asset_key).toBe("legacy-missing-key")
    expect(unknown.asset_key).toBe("unknown")
  })

  it("shows the original unknown key in the overlay asset selector", () => {
    mapState.selectedTerrainAssetKey = "legacy-missing-key"

    const html = renderEditPanel({ terrainLayers: [] })

    expect(html).toContain("未知素材（legacy-missing-key）")
    expect(html).toContain('value="legacy-missing-key" selected')
  })
})
