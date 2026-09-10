import { afterEach, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { locateAssistantSource, openAssistantDestination } from "../../../vue/shared/assistantNavigation.js"

afterEach(resetBridgeOverrides)

it("only opens registered workbenches and keeps the current writing location", () => {
  const navigate = vi.fn()
  setBridgeOverrides({ router: { navigate } })
  expect(openAssistantDestination("https://example.com")).toBe(false)
  expect(openAssistantDestination("__proto__")).toBe(false)
  expect(navigate).not.toHaveBeenCalled()
  openAssistantDestination("writing_generation", { chapter_index: 3, scene_id: "current-scene" })
  expect(navigate).toHaveBeenCalledWith("generate", null, true, expect.any(URLSearchParams))
  expect(navigate.mock.calls[0][3].get("chapter_index")).toBe("3")
  expect(navigate.mock.calls[0][3].get("tab")).toBe("pov_prose")
  openAssistantDestination("project_import")
  expect(navigate.mock.calls[1][3].get("open")).toBe("import")
})

it.each([
  [{ type: "foreshadowing_plan", id: "plan" }, "outline", "threads", { information: "foreshadowing", plan_id: "plan" }],
  [{ type: "reveal_plan", id: "plan" }, "outline", "threads", { information: "reveals", plan_id: "plan" }],
  [{ type: "story_outline", id: "rev", revision_id: "rev" }, "outline", "story-outline", { revision_id: "rev" }],
  [{ target_ref: { target_type: "world_bible_page_history", target_id: "page", target_path: "2" } }, "world", "bible", { page_id: "page", history: "1", history_version: "2" }],
  [{ type: "outline_generate", task_id: "task", target_kind: "planned_scene" }, "outline", "scenes", { review: "ai", source_task_id: "task" }],
  [{ type: "import_workflow", id: "workflow", task_id: "task" }, "writing", null, { import_task_id: "task" }],
  [{ type: "imports_completion_review", target: { type: "import_workflow", id: "workflow" }, location: { chapter_index: 3, source_task_id: "task" } }, "writing", null, { import_task_id: "task", chapter_index: "3" }],
  [{ type: "world_validation", target: { type: "core_entity", id: "entity" }, location: { review_id: "review" } }, "world", "bible", { validation_run_id: "review" }],
  [{ type: "scene_story_assets", id: "scene" }, "scene", "scene", {}],
  [{ type: "map_atlas_node", id: "map" }, "map", null, { node_id: "map" }],
  [{ type: "map_atlas_node", id: "map", revision_id: "saved" }, "map", null, { node_id: "map", revision_id: "saved" }],
  [{ type: "map_atlas_page", id: "image", run_id: "run", node_id: "map" }, "map", null, { node_id: "map", run_id: "run", page_id: "image", atlas_view: "review" }],
  [{ type: "world_suggestion", id: "candidate" }, "world", "bible", { suggestion_id: "candidate", open: "suggestions" }],
])("opens the domain receipt with its original identity: %j", (source, page, subview, expected) => {
  const navigate = vi.fn()
  setBridgeOverrides({ router: { navigate } })
  locateAssistantSource(source)
  expect(navigate).toHaveBeenCalledWith(page, subview, true, expect.any(URLSearchParams))
  expect(Object.fromEntries(navigate.mock.calls[0][3])).toEqual(expected)
})
