export const IMPORT_ADOPTION_POLICY = "user_authorized_pipeline"

export function importAuthorizationPayload() {
  return {
    adoption_policy: IMPORT_ADOPTION_POLICY,
    authorization_confirmed: true,
  }
}

export function importAuthorizationNotice() {
  return "启动后，系统会在所选章节范围内自动采用可信的场景、合并结果与故事结构；存在冲突、把握不足或需要你判断的内容会进入待处理，未采用内容会保留摘要。"
}
