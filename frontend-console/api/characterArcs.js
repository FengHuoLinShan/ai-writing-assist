/** Story-owned character arc plans and cutoff comparisons. */

import { post, request, withQuery } from "./_shared.js"

const base = "/story/character-arcs"

export const characterArcs = {
  sceneCharacters: (novelId, sceneId) => request(
    withQuery(`${base}/scenes/${encodeURIComponent(sceneId)}/characters`, { novel_id: novelId }),
    { cache: "no-store" },
  ),
  compare: (novelId, sceneId, characterId) => request(
    withQuery(`${base}/scenes/${encodeURIComponent(sceneId)}/characters/${encodeURIComponent(characterId)}/comparison`, { novel_id: novelId }),
    { cache: "no-store" },
  ),
  history: (novelId, sceneId, characterId) => request(
    withQuery(`${base}/scenes/${encodeURIComponent(sceneId)}/characters/${encodeURIComponent(characterId)}/history`, { novel_id: novelId }),
    { cache: "no-store" },
  ),
  previewPlan: (novelId, body) => post(withQuery(`${base}/plans/preview`, { novel_id: novelId }), body),
  confirmPlan: (novelId, body) => post(withQuery(`${base}/plans/confirm`, { novel_id: novelId }), body),
  previewRestore: (novelId, body) => post(withQuery(`${base}/plans/restore/preview`, { novel_id: novelId }), body),
  confirmRestore: (novelId, body) => post(withQuery(`${base}/plans/restore/confirm`, { novel_id: novelId }), body),
  previewArchive: (novelId, body) => post(withQuery(`${base}/plans/archive/preview`, { novel_id: novelId }), body),
  confirmArchive: (novelId, body) => post(withQuery(`${base}/plans/archive/confirm`, { novel_id: novelId }), body),
  previewUnarchive: (novelId, body) => post(withQuery(`${base}/plans/unarchive/preview`, { novel_id: novelId }), body),
  confirmUnarchive: (novelId, body) => post(withQuery(`${base}/plans/unarchive/confirm`, { novel_id: novelId }), body),
}
