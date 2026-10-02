/**
 * 表格迁移纯逻辑 — 标签、目标选项与决策 payload（ADR-0030）。
 * 组件只做渲染与交互，全部文案与数据形状在此处集中。
 */

export const SHEET_KIND_LABELS = {
  characters: "人物表",
  world_objects: "设定表",
  relations: "关系表",
  chapter_outline: "章节细纲",
  arcs: "卷纲",
  threads: "剧情线",
  foreshadowing: "伏笔",
  story_outline: "总纲",
  freeform_outline: "自由文本大纲",
  skip: "跳过（不导入）",
}

export const COLUMN_TARGET_LABELS = {
  name: "名称",
  aliases: "别名",
  entity_type: "类型",
  summary: "简介",
  public_info: "公开信息",
  hidden_truth: "秘密",
  author_note: "作者备注",
  ignore: "不导入",
  role: "身份",
  appearance: "外貌",
  personality: "性格",
  desire: "渴望",
  fear: "恐惧",
  weakness: "弱点",
  current_goal: "当前目标",
  current_state: "现状",
  stance: "立场",
  voice_style: "说话风格",
  relationship_summary: "人际关系",
  source_name: "关系方甲",
  target_name: "关系方乙",
  relation_type: "关系",
  relation_description: "关系说明",
  direction: "方向",
  chapter_ref: "章节",
  title: "标题",
  content: "内容",
  core_conflict: "核心冲突",
  emotional_beat: "情绪节拍",
  must_not_happen: "不能发生",
  pov_name: "视角人物",
  chapter_start: "起始章",
  chapter_end: "结束章",
  thread_type: "线型",
  seed_chapter: "埋设章",
  payoff_chapter: "兑现章",
  reinforce_chapters: "强化章",
  surface_meaning: "表面含义",
  hidden_meaning: "隐藏含义",
  related_names: "相关人物",
  arc_goal: "卷目标",
  climax: "高潮",
  result: "结果",
  next_hook: "下一卷钩子",
}

const WORLD_TARGETS = ["name", "aliases", "entity_type", "summary", "public_info", "hidden_truth", "author_note", "ignore"]
const CHARACTER_TARGETS = ["role", "appearance", "personality", "desire", "fear", "weakness", "current_goal", "current_state", "stance", "voice_style", "relationship_summary"]
const RELATION_TARGETS = ["source_name", "target_name", "relation_type", "relation_description", "direction", "ignore"]
const STORY_TARGETS = ["chapter_ref", "title", "content", "core_conflict", "emotional_beat", "must_not_happen", "pov_name", "chapter_start", "chapter_end", "thread_type", "seed_chapter", "payoff_chapter", "reinforce_chapters", "surface_meaning", "hidden_meaning", "related_names", "arc_goal", "climax", "result", "next_hook", "author_note", "ignore"]

/** 各表类型可用的列目标选项（对齐后端 constants 四组）。 */
export function columnTargetOptions(kind) {
  if (kind === "characters") return [...WORLD_TARGETS, ...CHARACTER_TARGETS]
  if (kind === "world_objects") return [...WORLD_TARGETS, ...CHARACTER_TARGETS]
  if (kind === "relations") return RELATION_TARGETS
  if (kind === "skip") return ["ignore"]
  return STORY_TARGETS
}

export function sheetKindLabel(kind) {
  return SHEET_KIND_LABELS[kind] || kind || ""
}

export function columnTargetLabel(target) {
  return COLUMN_TARGET_LABELS[target] || target || ""
}

/** 大纲类表默认交给 AI 整理。 */
export const AI_DEFAULT_KINDS = new Set(["chapter_outline", "arcs", "threads", "foreshadowing", "story_outline", "freeform_outline"])

export function sheetWantsAiByDefault(kind) {
  return AI_DEFAULT_KINDS.has(kind)
}

export const ACTION_LABELS = {
  create: "新建",
  fill_empty: "补全空字段",
  adopt_existing: "采用候选",
  existing_ref: "已存在",
  conflict: "冲突，未导入",
  needs_review: "需要确认",
  similar_name: "名称相似，需确认",
  alias_collision: "别名重名",
  skip: "跳过",
  planned_scene: "新建细纲",
  link_scene: "关联已写章节",
  reference_only: "仅参考",
}

export function actionLabel(action) {
  return ACTION_LABELS[action] || action || ""
}

export const SESSION_STATUS_LABELS = {
  draft: "进行中",
  applied: "已导入",
  rolled_back: "已撤销",
  partially_rolled_back: "部分撤销",
}

export function sessionStatusLabel(status) {
  return SESSION_STATUS_LABELS[status] || status || ""
}

/** 作者可采取的决策动作（预览分页签内逐条）。 */
export const DECISION_OPTIONS = [
  { action: "auto", label: "按建议" },
  { action: "different_object", label: "是不同对象，新建" },
  { action: "use_existing", label: "并入已有对象" },
  { action: "append_note", label: "追加到备注" },
  { action: "skip", label: "跳过这条" },
]

export function decisionLabel(action) {
  return DECISION_OPTIONS.find((option) => option.action === action)?.label || action || ""
}

/** PUT /decisions 的 payload 组装。 */
export function decisionsPayload(decisions, relationKindGroups) {
  return {
    decisions: Object.entries(decisions || {}).map(([itemKey, value]) => {
      const decision = typeof value === "string" ? { action: value } : (value || {})
      return {
        item_key: itemKey,
        action: decision.action || "auto",
        ...(decision.relation_kind ? { relation_kind: decision.relation_kind } : {}),
        ...(decision.accept_ai !== undefined ? { accept_ai: decision.accept_ai } : {}),
      }
    }),
    ...(relationKindGroups && Object.keys(relationKindGroups).length
      ? { relation_kind_groups: relationKindGroups }
      : {}),
  }
}

/** PUT /mapping 的 payload 组装。 */
export function mappingPayload(session, sheets, options) {
  return {
    novel_id: session?.novel_id || "",
    expected_revision: session?.revision || 1,
    sheets: (sheets || []).map((sheet) => ({
      sheet_key: sheet.sheet_key,
      kind: sheet.kind,
      header_row: sheet.header_row,
      ...(sheet.default_entity_type ? { default_entity_type: sheet.default_entity_type } : {}),
      columns: { ...(sheet.columns || {}) },
    })),
    options: {
      written_chapter_policy: options?.written_chapter_policy || "reference_only",
      outline_head_policy: options?.outline_head_policy || "create_if_missing",
    },
  }
}

/** 409 revision 冲突判定与文案。 */
export function isRevisionConflict(err) {
  return err?.code === "migration_revision_stale" || err?.status === 409 && err?.code === "migration_revision_stale"
}

export function revisionConflictCopy() {
  return "这份迁移的内容刚刚有更新，请刷新后重试。"
}

/** 409 preview 过期：附上新 hash，供刷新预览。 */
export function isPreviewStale(err) {
  return err?.code === "migration_preview_stale"
}

export function stalePreviewCopy() {
  return "预览已过期（内容或决策在预览后有变化），已为你取回最新预览，请核对后再次确认。"
}

/** 预览分页签定义。 */
export const PREVIEW_TABS = [
  { key: "world_items", label: "人物与设定" },
  { key: "relations", label: "关系" },
  { key: "structures", label: "大纲结构" },
  { key: "conflicts", label: "冲突" },
  { key: "reference_only", label: "仅参考" },
]

export function conflictItems(preview) {
  if (!preview) return []
  const worlds = (preview.world_items || []).filter((item) => item.action === "conflict")
  const relations = (preview.relations || []).filter((item) => item.action === "conflict")
  const structures = (preview.structures || []).filter((item) => item.action === "conflict")
  return [...worlds, ...relations, ...structures]
}

export function referenceOnlyItems(preview) {
  return (preview?.structures || []).filter((item) => item.action === "reference_only")
}

/** 向导步骤定义。 */
export const MIGRATION_STEPS = [
  { key: "upload", label: "上传表格" },
  { key: "mapping", label: "核对表格" },
  { key: "ai", label: "AI 整理" },
  { key: "preview", label: "预览与确认" },
  { key: "done", label: "完成" },
]
