/**
 * 项目设置页会话级 UI 状态 — 对应 vanilla renderer 单例的 _tab：
 * 路由往返（项目设置 → 全局设置 → 返回）期间保留所选 Tab，
 * 整页刷新后重置。不按项目隔离（与 vanilla 单例语义一致）。
 */
export const projectSettingsSession = {
  tab: "main",
}
