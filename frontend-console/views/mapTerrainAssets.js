/**
 * 第一版内置地形素材 manifest。
 *
 * Kenney 基础素材使用 CC0；小说语义地形先使用项目内置补充描述，不支持上传。
 */

const asset = (packKey, assetKey, label, color, pattern, brush = 2, opacity = 0.44) => ({
  pack_key: packKey,
  asset_key: assetKey,
  label,
  color,
  pattern,
  source_type: "project_builtin",
  license: "project",
  default_opacity: opacity,
  default_brush_size: brush,
})

export const TERRAIN_PACKS = [
  { pack_key: "nature", label: "自然环境" },
  { pack_key: "city_transport", label: "城市交通" },
  { pack_key: "fantasy_crisis", label: "奇幻危机" },
]

export const TERRAIN_ASSETS = [
  asset("nature", "mountain", "山地", "#64748b", "ridge"),
  asset("nature", "forest", "森林", "#26845b", "dots"),
  asset("nature", "water", "水域", "#3182bd", "waves", 3),
  asset("nature", "desert", "沙漠", "#d6a85f", "dots"),
  asset("nature", "swamp", "沼泽", "#59734b", "waves"),
  asset("nature", "snow", "雪地", "#dce8f3", "cross"),
  asset("nature", "cliff", "悬崖", "#765f4b", "ridge"),
  asset("nature", "volcano", "火山", "#9f3a2f", "burst"),
  asset("city_transport", "city_area", "城区", "#8c7b6b", "grid"),
  asset("city_transport", "road", "道路", "#b28a58", "line", 1),
  asset("city_transport", "river", "河流", "#2d86c4", "waves", 1),
  asset("city_transport", "bridge", "桥梁", "#8b6d48", "cross", 1),
  asset("city_transport", "wall", "城墙", "#6f7480", "blocks", 1),
  asset("city_transport", "gate", "城门", "#9a6b3f", "arch", 1),
  asset("city_transport", "ruin", "废墟", "#776f64", "broken", 1),
  asset("fantasy_crisis", "abyss", "深渊", "#24152f", "burst", 3, 0.58),
  asset("fantasy_crisis", "barrier", "结界", "#4f91e8", "cross", 3, 0.36),
  asset("fantasy_crisis", "magic_field", "魔法场", "#7464ef", "rings", 3, 0.34),
  asset("fantasy_crisis", "leyline", "地脉", "#b861d1", "line", 2),
  asset("fantasy_crisis", "portal", "传送门", "#7c4dff", "rings", 1),
  asset("fantasy_crisis", "secret_realm", "秘境", "#3b9f8c", "rings", 2),
  asset("fantasy_crisis", "corruption", "腐化", "#7c315f", "veins", 2, 0.46),
  asset("fantasy_crisis", "danger_zone", "危险区", "#c23b3b", "cross", 2, 0.5),
  asset("fantasy_crisis", "fog", "迷雾", "#8994a6", "waves", 3),
  asset("fantasy_crisis", "storm", "风暴", "#56657e", "spiral", 3),
  asset("fantasy_crisis", "fire", "火焰", "#e35d2f", "burst", 2),
  asset("fantasy_crisis", "ice", "冰霜", "#66b7dd", "cross", 2),
  asset("fantasy_crisis", "poison", "毒域", "#6b9d3e", "dots", 2),
  asset("fantasy_crisis", "sacred_light", "圣光", "#e8c95d", "burst", 2),
]

export const TERRAIN_PRESETS = {
  standard: { key: "standard", label: "标准", opacity_scale: 1, saturation: 1, contrast: 1 },
  soft: { key: "soft", label: "柔和", opacity_scale: 0.72, saturation: 0.72, contrast: 0.9 },
  high_contrast: { key: "high_contrast", label: "高对比", opacity_scale: 1.18, saturation: 1.35, contrast: 1.25 },
}

const UNKNOWN_TERRAIN_ASSET = {
  pack_key: "unknown",
  asset_key: "unknown",
  label: "未知素材",
  color: "#64748b",
  pattern: "unknown",
  default_opacity: 0.4,
  default_brush_size: 1,
  unknown: true,
}

export function getTerrainAsset(assetKey) {
  const found = TERRAIN_ASSETS.find((item) => item.asset_key === assetKey)
  return found || { ...UNKNOWN_TERRAIN_ASSET, original_asset_key: assetKey }
}
