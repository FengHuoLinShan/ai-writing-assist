export const IMPORT_ADOPTION_POLICY = "user_authorized_pipeline"

export function importAuthorizationPayload() {
  return {
    adoption_policy: IMPORT_ADOPTION_POLICY,
    authorization_confirmed: true,
  }
}

export function importAuthorizationNotice() {
  return "启动后，流水线会在所选章节范围内自动采用通过门禁的 Scene、高置信度合并与工作结构资产；存在冲突、低置信度或需人工判断的结果会进入待处理，未采用内容会保留结果摘要。"
}
