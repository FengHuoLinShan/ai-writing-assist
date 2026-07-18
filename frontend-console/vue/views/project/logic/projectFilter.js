/**
 * 项目列表纯逻辑 — 从 views/projectView.js 移植的框架无关部分。
 * 排序/过滤/统计/时间格式与原实现保持一致。
 */

export function projectName(project) {
  return String(project?.title || project?.name || "未命名项目")
}

export function projectActivityMs(project) {
  const raw = project?.last_active_at || project?.updated_at || project?.created_at
  if (!raw) return 0
  const time = new Date(raw).getTime()
  return Number.isNaN(time) ? 0 : time
}

/** 当前项目置顶，其余按最近活跃倒序，再按名称 zh-CN 排序。 */
export function sortedProjects(projects = [], currentProjectId = null) {
  const current = String(currentProjectId || "")
  return [...projects].sort((a, b) => {
    const aIsCurrent = current && String(a.id) === current
    const bIsCurrent = current && String(b.id) === current
    if (aIsCurrent !== bIsCurrent) return aIsCurrent ? -1 : 1
    const activityDiff = projectActivityMs(b) - projectActivityMs(a)
    if (activityDiff !== 0) return activityDiff
    return projectName(a).localeCompare(projectName(b), "zh-CN")
  })
}

export function filterProjects(projects = [], query = "") {
  const normalized = String(query || "").trim().toLocaleLowerCase("zh-CN")
  if (!normalized) return projects
  return projects.filter((project) => (
    projectName(project).toLocaleLowerCase("zh-CN").includes(normalized)
  ))
}

export function projectCountLabel(filteredCount, totalCount) {
  return `显示 ${filteredCount} / 共 ${totalCount} 个项目`
}

const STAGE_LABELS = {
  world_building: "世界构建",
  outlining: "大纲规划",
  writing: "正文写作",
  revising: "修订中",
}

export function stageLabel(stage) {
  return STAGE_LABELS[stage] || stage
}

export function formatNumber(value) {
  return (Number(value) || 0).toLocaleString("zh-CN")
}

export function projectStats(project) {
  const stats = project?.stats || project?.statistics || {}
  const wordCount = project?.total_words
    ?? project?.word_count
    ?? project?.total_word_count
    ?? stats.total_words
    ?? stats.word_count
    ?? null
  const chapterCount = project?.chapter_count
    ?? project?.total_chapters
    ?? stats.chapter_count
    ?? stats.total_chapters
    ?? null
  return {
    wordCount: Number(wordCount) || 0,
    chapterCount: Number(chapterCount) || 0,
    wordCountText: wordCount === null || wordCount === undefined ? "待接入" : formatNumber(wordCount),
    chapterCountText: chapterCount === null || chapterCount === undefined ? "待接入" : formatNumber(chapterCount),
    wordCountTitle: wordCount === null || wordCount === undefined ? "统计接入后显示总字数" : "总字数",
    chapterCountTitle: chapterCount === null || chapterCount === undefined ? "统计接入后显示章节数" : "章节数",
  }
}

export function formatRelativeTime(value) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return "暂无活跃"
  const diffMs = Date.now() - date.getTime()
  if (diffMs < 0) return "刚刚活跃"
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diffMs < minute) return "刚刚活跃"
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} 分钟前活跃`
  if (diffMs < day) return `${Math.floor(diffMs / hour)} 小时前活跃`
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前活跃`
  return date.toLocaleDateString("zh-CN")
}

export function projectActivityTime(project) {
  const raw = project?.last_active_at || project?.updated_at || project?.created_at
  if (!raw) return { relative: "暂无活跃", full: "暂无活跃时间" }
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return { relative: "暂无活跃", full: String(raw) }
  return {
    relative: formatRelativeTime(date),
    full: date.toLocaleString("zh-CN"),
  }
}

export function projectMonogram(project) {
  const characters = Array.from(projectName(project).replace(/\s+/g, ""))
  return characters.slice(0, 2).join("") || "新作"
}
