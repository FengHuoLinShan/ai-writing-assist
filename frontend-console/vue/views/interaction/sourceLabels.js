// 作品资料对象类型的用户可读标签;词汇与 world 模块实体类型命名对齐。
const SOURCE_ENTITY_TYPE_LABELS = {
  character: "人物",
  location: "地点",
  relation: "关系",
  faction: "势力",
  organization: "组织",
  item: "物品",
  event: "事件",
  creature: "生物",
  concept: "概念",
  rule: "规则",
  object: "对象",
  entity: "对象",
}

export function sourceEntityTypeLabel(value) {
  return SOURCE_ENTITY_TYPE_LABELS[String(value || "").trim()] || "其他"
}
