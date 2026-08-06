export const SHELL_NAV_ITEMS = Object.freeze([
  { view: "today", label: "首页", title: "今日工作", icon: "home" },
  { view: "writing", label: "写作", title: "写作", icon: "writing" },
  { view: "world", label: "人物与世界", title: "人物与世界", icon: "world" },
  { view: "outline", label: "故事结构", title: "故事结构", icon: "outline" },
  { view: "map", label: "地图", title: "地图", icon: "map" },
  { view: "rag", label: "查找", title: "查找正文与资料", icon: "search" },
])

export const SHELL_MOBILE_NAV_ITEMS = Object.freeze([
  SHELL_NAV_ITEMS[0],
  SHELL_NAV_ITEMS[1],
  { ...SHELL_NAV_ITEMS[2], label: "世界" },
  { ...SHELL_NAV_ITEMS[3], label: "结构" },
])

export const SHELL_MORE_ITEMS = Object.freeze([
  { view: "project", label: "导入与整理", title: "导入正文并整理作品", icon: "project" },
  { view: "generate", label: "高级工具", title: "高级生成与上下文工具", icon: "generate" },
  { view: "project-settings", label: "项目偏好", title: "项目偏好", icon: "project-settings" },
])

const INTERACTION_RETURN_TARGET = (
  /^interaction:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
)

export function normalizeRpReturnTarget(value) {
  const target = String(value || "")
  if (target === "journeys" || target === "journeys:new") return target
  return INTERACTION_RETURN_TARGET.test(target) ? target : ""
}

export function navDestination(services, view) {
  const route = services.router.getRoute(view)
  return services.router.getLastSubView(view)
    || route?.defaultSubView
    || route?.subViews?.[0]
    || null
}
