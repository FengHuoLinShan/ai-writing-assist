export const IMPORT_ADOPTION_POLICY = "user_authorized_pipeline"

export function importAuthorizationPayload() {
  return {
    adoption_policy: IMPORT_ADOPTION_POLICY,
    authorization_confirmed: true,
  }
}

export function importAuthorizationNotice() {
  return "启动后，系统会在所选章节范围内自动采用可信的场景、合并结果与故事结构；完整整理还会查证人物、关系和别名，通过质量与证据校验的资料可自动采用；关键问题成组决定，其他建议可稍后查看。可停止、恢复与撤销，作者已有修改会保留。"
}
