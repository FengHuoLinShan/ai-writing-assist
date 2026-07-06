/**
 * 根据章节索引和光标 offset 定位当前 Scene。
 *
 * 匹配优先级：
 * 1. scene_chunks 中 chapter_index + offset 范围精确命中
 * 2. chapter_ids 直接包含当前章节
 * 3. scene_chunks 中任意 chunk 包含当前章节
 */
export function findCurrentScene({ scenes, chapterIndex, cursorOffset = 0 }) {
  if (!chapterIndex || !scenes?.length) return null
  const chStr = String(chapterIndex)
  const offset = cursorOffset || 0

  const byOffset = scenes.find((s) =>
    (s.scene_chunks || []).some((c) =>
      String(c.chapter_index) === chStr &&
      Number(c.start_pos || 0) <= offset &&
      offset < Number(c.end_pos || 0)
    )
  )
  if (byOffset) return byOffset

  const exact = scenes.find((s) => (s.chapter_ids || []).includes(chStr))
  if (exact) return exact

  return scenes.find((s) =>
    (s.scene_chunks || []).some((c) => String(c.chapter_index) === chStr)
  ) || null
}
