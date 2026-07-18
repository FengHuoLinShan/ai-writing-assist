/**
 * useLeaveGuard — 向当前 island 注册路由离开守卫（router canLeave 契约）。
 *
 * 守卫必须同步返回：false 阻断导航（如 worldBible 有未保存编辑时）；
 * 其他值/未注册放行。单槽位，后注册覆盖先注册；组件卸载时自动注销。
 * 在非 island 环境（纯组件单测）无注册器注入，静默跳过。
 */
import { inject, onBeforeUnmount } from "vue"
import { ISLAND_LEAVE_GUARD } from "../mountIsland.js"

export function useLeaveGuard(fn) {
  const register = inject(ISLAND_LEAVE_GUARD, null)
  if (typeof register !== "function") return
  register(fn)
  onBeforeUnmount(() => register(null))
}
