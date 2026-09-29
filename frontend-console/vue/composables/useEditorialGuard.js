/**
 * useEditorialGuard — 编辑审读“会失效”确认守卫。
 *
 * 后台编辑审读（作者助手·编辑审读）排队或进行中时，若作者显式保存新的编辑约定、
 * 修改世界设定 / 大纲结构，或发布章节新正文，后端会把该项目全部进行中的审读标记
 * 为 stale 并停止（对应 EditorialDesk.vue 的 status === "stale"）。这里只做保存前
 * 的作者语言提醒，从不阻塞自动保存；后端正确性不依赖本守卫，请求失败或功能未开放
 * 时一律放行（fail open）。
 */
import { getApi, getConfirm } from "../bridge/index.js"

const ACTIVE_STATUSES = new Set(["queued", "running"])
const CACHE_TTL_MS = 5000
// 功能未开放时结果不会很快变化，缓存更久，避免写作页轮询空跑。
const UNAVAILABLE_TTL_MS = 60000

// projectId -> { expiresAt, reviews }
const reviewCache = new Map()

function reviewCoversChapter(review, chapterIndex) {
  if (review.scope?.scope === "book") return true
  const target = Number(chapterIndex)
  const sources = Array.isArray(review.sources) ? review.sources : []
  return sources.some((item) => Number(item?.chapter_index) === target)
}

async function fetchActiveReviews(projectId) {
  const api = getApi()
  try {
    const policy = await api.assistant.editorialPolicy(projectId)
    if (!policy?.feature_available) return { reviews: [], ttl: UNAVAILABLE_TTL_MS }
  } catch {
    return { reviews: [], ttl: CACHE_TTL_MS }
  }
  try {
    const reviews = await api.assistant.editorialReviews(projectId)
    return {
      reviews: (reviews || []).filter((review) => ACTIVE_STATUSES.has(review?.status)),
      ttl: CACHE_TTL_MS,
    }
  } catch {
    return { reviews: [], ttl: CACHE_TTL_MS }
  }
}

/**
 * 项目当前排队/进行中的编辑审读列表；任意失败或功能未开放时返回 []（fail open）。
 * 带若干秒的按项目缓存，避免同一批动作对每个字段改动都发一次请求。
 */
export async function activeEditorialReviews(projectId, { chapterIndex } = {}) {
  if (!projectId) return []
  const now = Date.now()
  const cached = reviewCache.get(projectId)
  let reviews
  if (cached && now < cached.expiresAt) {
    reviews = cached.reviews
  } else {
    const fetched = await fetchActiveReviews(projectId)
    reviews = fetched.reviews
    reviewCache.set(projectId, { expiresAt: now + fetched.ttl, reviews })
  }
  if (chapterIndex == null) return reviews
  return reviews.filter((review) => reviewCoversChapter(review, chapterIndex))
}

/** 保存前清空缓存的项目切换保护；调用方一般不需要主动调用。 */
export function invalidateEditorialReviewCache(projectId) {
  if (projectId) reviewCache.delete(projectId)
  else reviewCache.clear()
}

const MESSAGES = {
  brief: (count) => `有 ${count} 项编辑审读正在进行。保存新的编辑约定后，这些审读会停止并标为已失效，已产生的模型用量不退回。仍要保存吗？`,
  world: (count) => `有 ${count} 项编辑审读正在进行。修改世界设定会让这些审读失效并停止，已读部分会保留。仍要继续吗？`,
  outline: (count) => `有 ${count} 项编辑审读正在进行。修改大纲/剧情结构会让这些审读失效并停止，已读部分会保留。仍要继续吗？`,
  chapter: (count, chapterIndex) => `第 ${chapterIndex} 章正在接受编辑审读。发布新正文会让本次审读失效，已读部分会保留。仍要发布吗？`,
}

/** 按 kind 构造确认文案；chapterIndex 仅 kind === "chapter" 时使用。 */
export function editorialImpactMessage(kind, count, chapterIndex = null) {
  const build = MESSAGES[kind] || MESSAGES.world
  return build(count, chapterIndex)
}

/**
 * 作者是否可以继续本次改动：没有相关的进行中审读，或作者已在确认框中确认。
 * `reviews` 可选——调用方已经持有当前审读列表时（例如 EditorialDesk 自身的
 * reviews.value）直接传入，跳过一次网络请求；否则本函数会经 activeEditorialReviews 拉取。
 */
export async function confirmEditorialImpact(projectId, { kind = "world", chapterIndex = null, reviews = null } = {}) {
  const activeReviews = reviews ?? await activeEditorialReviews(projectId, { chapterIndex })
  if (!activeReviews.length) return true
  return getConfirm()(editorialImpactMessage(kind, activeReviews.length, chapterIndex))
}
