/** Author-only factual Story timeline; distinct from foreshadowing/reveal plans. */

import { request, withQuery } from "./_shared.js"

export const storyTimeline = {
  async listFacts(novelId, filters = {}) {
    const query = {
      entity_id: filters.entityId || undefined,
      cutoff_scene_id: filters.cutoffSceneId || undefined,
      source: filters.source || undefined,
      status: filters.status || undefined,
      skip: Number(filters.skip) || 0,
      limit: Number(filters.limit) || 50,
    }
    return request(
      withQuery(`/novels/${encodeURIComponent(novelId)}/memories/fact-timeline`, query),
      { cache: "no-store" },
    )
  },
}
