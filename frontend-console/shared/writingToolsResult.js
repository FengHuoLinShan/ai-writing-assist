/**
 * 将 tools / autoExtraction 回调结果应用到 writingView orchestrator 的共享状态。
 *
 * 返回的 action 由 orchestrator 负责触发后续视图更新。
 */
export function applyToolsResult(result, view) {
  if (result?.new_chapter_index != null) {
    if (result.scenes) {
      view._scenes = result.scenes
    }
    view._chapters[result.source_chapter_index] = {
      ...view._chapters[result.source_chapter_index],
      title: result.source_draft?.title,
      draftCount: (view._chapters[result.source_chapter_index]?.draftCount || 0) + 1,
    }
    view._chapters[result.new_chapter_index] = {
      title: result.new_draft?.title,
      draftCount: 1,
    }
    view._chapterList = [...new Set([...view._chapterList, result.new_chapter_index])].sort((a, b) => a - b)
    return { selectChapter: result.new_chapter_index }
  }
  if (Array.isArray(result)) {
    view._scenes = result
    return { rerender: true }
  }
  return {}
}
