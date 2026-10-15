const VALIDITY_GAP_LABELS = {
  author_interval_anchor_invalid: "作者有效期的场景或章节锚点暂不可核实。",
  chapter_identity_unavailable: "作者区间引用的章节身份暂不可核实。",
  project_override_setting_unavailable: "项目有效期规则暂不可读取。",
  scene_anchor_unavailable: "作者区间引用的场景暂不可核实。",
  spatial_anchor_order_reversed: "作者区间的起止顺序发生变化，请重新核对。",
  story_alignment_unverified: "Story 字段与对象类型没有精确对应。",
  story_field_alignment_not_declared: "尚未为这条档案指定对应的 Story 状态字段。",
  story_map_declaration_unavailable: "该地图声明目前没有可核对的 Story 状态来源。",
  story_observation_missing: "截止 Scene 前没有找到同一对象或关系的状态观察。",
  story_observation_not_before_cutoff: "这条观察来自当前 Scene 或更晚，不能用于此截止点。",
  story_observation_time_unverified: "Story 观察的场景时间暂不可核实。",
  story_observation_unconfirmed: "Story 观察尚未得到可信确认。",
  story_relation_identity_ambiguous: "多个 Story 关系事件无法确定先后，请核对来源。",
  story_source_unverified: "Story 观察的来源暂不可核实。",
  story_state_unavailable: "Story 截止状态暂不可读取。",
}

export function validityGapLabel(reason) {
  return VALIDITY_GAP_LABELS[String(reason || "")] || "有效期与 Story 状态的对应来源暂不可核实。"
}
