export const BIBLE_CATEGORY_PRESETS = [
  { key: "technology", name: "技术体系", description: "技术、工程、能源与制造", color: "#2563EB", icon: "技术" },
  { key: "power_system", name: "力量体系", description: "魔法、能力、等级、限制与代价", color: "#DC2626", icon: "力量" },
  { key: "governance", name: "政治制度", description: "权力结构、法律、治理与继承", color: "#7C3AED", icon: "制度" },
  { key: "economy", name: "经济贸易", description: "货币、资源、产业与交换", color: "#D97706", icon: "贸易" },
  { key: "religion", name: "宗教信仰", description: "神话、教派、仪式与禁忌", color: "#9333EA", icon: "信仰" },
  { key: "culture_language", name: "文化语言", description: "语言、命名、习俗与艺术", color: "#059669", icon: "文化" },
]

export const BIBLE_PAGE_TYPES = {
  background: { label: "背景", title: "世界基本背景", desc: "世界观、历史和基础设定", color: "#6366f1", symbol: "BG" },
  species: { label: "种族", title: "种族", desc: "种族、生物和特殊生命体", color: "#dc2626", symbol: "SP" },
  faction: { label: "势力", title: "势力", desc: "组织、阵营和权力结构", color: "#d97706", symbol: "FA" },
  location: { label: "地点", title: "地点", desc: "城市、地理和关键场景", color: "#16a34a", symbol: "LO" },
  rule: { label: "规则", title: "规则体系", desc: "法则、能力体系和限制", color: "#475569", symbol: "RU" },
  item: { label: "物品", title: "重要物品", desc: "装备、资源和关键道具", color: "#9333ea", symbol: "IT" },
  secret: { label: "秘密", title: "秘密", desc: "伏笔、真相和隐藏信息", color: "#7c3aed", symbol: "SE" },
  source_material: { label: "导入资料", title: "导入资料", desc: "尚未发布的外部世界书资料", color: "#475569", symbol: "IM" },
  custom: { label: "未分类", title: "未分类", desc: "尚未归入其他类别的设定", color: "#6b7280", symbol: "未分" },
}

/** Deterministic, intentionally non-physical layout for the optional SVG aid. */
export function knowledgeGraphLayout(nodes, edges, maxNodes = 40) {
  const visible = [...nodes].sort((a, b) => String(a.id).localeCompare(String(b.id))).slice(0, maxNodes)
  const ids = new Set(visible.map((node) => node.id))
  const lanes = { world_bible_page: [], core_entity: [] }
  for (const node of visible) (lanes[node.kind] || lanes.core_entity).push(node)
  const positions = Object.fromEntries(visible.map((node) => {
    const lane = node.kind === "world_bible_page" ? 0 : 1
    const index = lanes[node.kind]?.indexOf(node) ?? 0
    return [node.id, { x: 110 + lane * 300, y: 56 + index * 72 }]
  }))
  return { nodes: visible, edges: edges.filter((edge) => ids.has(edge.source_id) && ids.has(edge.target_id)).slice(0, 80), positions }
}
