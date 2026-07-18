/**
 * 项目页会话级 UI 状态 — 对应 vanilla projectView 单例的可变字段：
 * 路由往返保留（导入抽屉开合/搜索词/回收站分页/批量选择），整页刷新重置。
 * reactive：模板/计算属性直接追踪（island 重挂载后仍指向同一对象）。
 */
import { reactive } from "vue"

export const PROJECT_CARDS_SCOPE = "project-cards"

export const projectSession = reactive({
  importSectionOpen: false,
  searchQuery: "",
  recycleBinSkip: 0,
  _bulkSelections: {},
})

// reactive Set：shared/bulkSelection.js 的状态函数照常操作，模板可追踪
projectSession._bulkSelections[PROJECT_CARDS_SCOPE] = reactive(new Set())
