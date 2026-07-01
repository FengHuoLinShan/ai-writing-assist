/**
 * 第一版内置地形素材 manifest。
 *
 * Kenney 基础素材使用 CC0；小说语义地形先使用项目内置补充描述，不支持上传。
 */

export const TERRAIN_ASSETS = [
  { asset_key: "mountain", label: "高山", category: "基础地貌", source_type: "kenney_builtin", license: "CC0", default_opacity: 0.42, default_brush_size: 2, tags: ["terrain", "height"] },
  { asset_key: "forest", label: "森林", category: "基础地貌", source_type: "kenney_builtin", license: "CC0", default_opacity: 0.38, default_brush_size: 2, tags: ["terrain", "wood"] },
  { asset_key: "water", label: "水域", category: "基础地貌", source_type: "kenney_builtin", license: "CC0", default_opacity: 0.44, default_brush_size: 3, tags: ["terrain", "river"] },
  { asset_key: "ruin", label: "遗迹", category: "基础地貌", source_type: "kenney_builtin", license: "CC0", default_opacity: 0.5, default_brush_size: 1, tags: ["structure"] },
  { asset_key: "abyss", label: "深渊", category: "奇幻地貌", source_type: "project_builtin", license: "project", default_opacity: 0.58, default_brush_size: 3, tags: ["fantasy", "danger"] },
  { asset_key: "barrier", label: "结界", category: "奇幻地貌", source_type: "project_builtin", license: "project", default_opacity: 0.36, default_brush_size: 3, tags: ["fantasy", "field"] },
  { asset_key: "magic_field", label: "灵气场", category: "奇幻地貌", source_type: "project_builtin", license: "project", default_opacity: 0.34, default_brush_size: 3, tags: ["fantasy", "magic"] },
  { asset_key: "corruption", label: "污染", category: "奇幻地貌", source_type: "project_builtin", license: "project", default_opacity: 0.46, default_brush_size: 2, tags: ["fantasy", "risk"] },
  { asset_key: "danger_zone", label: "禁区", category: "奇幻地貌", source_type: "project_builtin", license: "project", default_opacity: 0.5, default_brush_size: 2, tags: ["risk"] },
]

export function getTerrainAsset(assetKey) {
  return TERRAIN_ASSETS.find((asset) => asset.asset_key === assetKey) || TERRAIN_ASSETS[0]
}
