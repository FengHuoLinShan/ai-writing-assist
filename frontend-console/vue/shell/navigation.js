export const SHELL_NAV_ITEMS = Object.freeze([
  { view: "project", label: "项目", title: "项目", icon: "project" },
  { view: "writing", label: "写作", title: "手动工作台", icon: "writing" },
  { view: "world", label: "世界", title: "世界对象", icon: "world" },
  { view: "map", label: "地图", title: "地图", icon: "map" },
  { view: "rag", label: "检索", title: "小说检索", icon: "search" },
  { view: "outline", label: "大纲", title: "大纲", icon: "outline" },
  { view: "generate", label: "生成", title: "生成中心", icon: "generate" },
  { view: "settings", label: "设置", title: "全局设置", icon: "settings" },
  { view: "project-settings", label: "项目设置", title: "项目设置", icon: "project-settings" },
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
