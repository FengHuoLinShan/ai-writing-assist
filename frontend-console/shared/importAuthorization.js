export const IMPORT_ADOPTION_POLICY = "user_authorized_pipeline"

export function importAuthorizationPayload() {
  return {
    adoption_policy: IMPORT_ADOPTION_POLICY,
    authorization_confirmed: true,
  }
}

export function importAuthorizationNotice(stage = "deep") {
  const target = { scenes: "场景及场景合并结果", world_objects: "人物、世界资料、名称归属与关系", plot_structure: "篇章、剧情线与信息推进" }[stage]
  if (target) return `本次仅整理所选章节中的${target}；可信结果按本次授权采用，冲突、证据不足或需要你判断的内容保留待处理。查漏补全需另行确认。`
  return "启动后，系统会在所选章节范围内自动采用可信的场景、合并结果与故事结构；完整整理还会查证人物、关系和别名，通过质量与证据校验的资料可自动采用；关键问题成组决定，其他建议可稍后查看。可停止、恢复与撤销，作者已有修改会保留。"
}
