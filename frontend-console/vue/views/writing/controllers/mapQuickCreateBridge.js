import mapQuickCreateView from "../../../../views/mapQuickCreateView.js"

/**
 * Phase 4 narrow bridge: map quick-create is a shared cross-module modal with
 * preview/layout editing. Writing only delegates open + completion callback;
 * it neither reads nor mutates that modal's DOM. The bridge can be deleted
 * once map quick-create itself becomes a Vue command surface.
 */
export function openWritingMapQuickCreate(options) {
  return mapQuickCreateView.open(options)
}
