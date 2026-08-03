import { describe, expect, it } from "vitest"
import {
  buildPageProposalApplyPayload,
  capturePageProposalDraft,
  editorFromPageProposal,
  pageProposalDraftMatches,
} from "../../../vue/views/generate/pageProposalSession.js"

const result = {
  kind: "world_bible_page",
  suggestion: { id: "suggestion-汉字", status: "pending" },
  proposal: {
    page: {
      title: "寒潮中的\"港口\"",
      page_type: "custom",
      free_text: "作者的概览 🐉",
      sections_json: [{ section_id: "s-1", content: { names: ["黎明", "\uD83C\uDF0A"], nested: { quote: "\\\"原样\\\"" } } }],
      linked_asset_refs_json: [{ asset_id: "asset-1", meta: { label: "潮汐" } }],
    },
  },
}

describe("page proposal editor session", () => {
  it("round-trips nested JSON and Unicode from a result into the unchanged apply payload", () => {
    const editor = editorFromPageProposal(result)
    const draft = capturePageProposalDraft(result, editor)

    expect(pageProposalDraftMatches(result, draft)).toEqual(draft)
    expect(buildPageProposalApplyPayload(draft.editor)).toEqual({ page: result.proposal.page })
  })

  it("keeps invalid raw JSON recoverable but rejects it before an apply payload is made", () => {
    const editor = editorFromPageProposal(result)
    editor.sectionsText = '{"unfinished":'
    const draft = capturePageProposalDraft(result, editor)

    expect(pageProposalDraftMatches(result, draft)?.editor.sectionsText).toBe('{"unfinished":')
    expect(() => buildPageProposalApplyPayload(draft.editor)).toThrow()
  })

  it("does not match malformed schemas or another suggestion", () => {
    const editor = editorFromPageProposal(result)
    expect(pageProposalDraftMatches(result, { schemaVersion: 2, suggestionId: "suggestion-汉字", editor })).toBeNull()
    expect(pageProposalDraftMatches({ ...result, suggestion: { id: "another" } }, capturePageProposalDraft(result, editor))).toBeNull()
    expect(pageProposalDraftMatches({ ...result, suggestion: { ...result.suggestion, status: "accepted" } }, capturePageProposalDraft(result, editor))).toBeNull()
  })
})
