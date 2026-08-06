import { describe, expect, it } from "vitest"

import {
  authorFacingStateText,
  assetAttentionReasons,
  contextContentModeLabel,
  mapAssetDisplay,
  structureAssetDisplay,
  worldAssetDisplay,
  writingAssetDisplay,
} from "../../shared/assetDisplayState.js"

describe("author-facing asset display state", () => {
  it("folds world draft and candidate into pending while keeping adopted and history distinct", () => {
    expect(worldAssetDisplay({ status: "draft" }).label).toBe("待处理")
    expect(worldAssetDisplay({ status: "candidate" }).label).toBe("待处理")
    expect(worldAssetDisplay({ status: "canonical" }).label).toBe("已采用")
    expect(worldAssetDisplay({ status: "deprecated" })).toMatchObject({ label: "历史", isHistory: true })
  })

  it("treats an explicit backend display projection as authoritative", () => {
    expect(worldAssetDisplay({ status: "canonical", display_state: "review" })).toMatchObject({
      displayState: "review",
      label: "待处理",
    })
  })

  it("keeps legacy structure candidates pending while drafts remain working content", () => {
    expect(structureAssetDisplay({ status: "draft" }).label).toBe("工作稿")
    expect(structureAssetDisplay({ status: "candidate" }).label).toBe("待处理")
    expect(structureAssetDisplay({ status: "canonical" }).label).toBe("已采用")
    expect(structureAssetDisplay({ status: "deprecated" }).label).toBe("历史")
  })

  it("keeps writing maturity separate from structured asset adoption", () => {
    expect(writingAssetDisplay({ status: "candidate" }).label).toBe("待处理")
    expect(writingAssetDisplay({ status: "draft" }).label).toBe("工作稿")
    expect(writingAssetDisplay({ status: "published" }).label).toBe("正式正文")
  })

  it("keeps map observation and fact models distinct while simplifying their labels", () => {
    expect(mapAssetDisplay({ item_kind: "observation", review_state: "candidate" }).label).toBe("待处理")
    expect(mapAssetDisplay({ item_kind: "observation", review_state: "conflicted" })).toMatchObject({
      label: "待处理",
      attentionReasons: ["存在冲突"],
    })
    expect(mapAssetDisplay({ item_kind: "fact", fact_status: "confirmed" }).label).toBe("已采用")
    expect(mapAssetDisplay({ item_kind: "fact", fact_status: "rolled_back" }).label).toBe("历史")
  })

  it("derives attention reasons independently from lifecycle", () => {
    expect(assetAttentionReasons({
      status: "canonical",
      needs_review: true,
      confidence: 0.4,
      boundary_status: "uncertain",
    })).toEqual(["低置信度", "边界不确定"])
  })

  it("preserves canonical and working wire values behind writing-oriented labels", () => {
    expect(contextContentModeLabel("canonical")).toBe("正式正文内容")
    expect(contextContentModeLabel("working")).toBe("工作稿内容")
    expect(contextContentModeLabel("candidate")).toBe("待处理内容")
  })

  it("normalizes legacy lifecycle words embedded in backend-authored display text", () => {
    expect(authorFacingStateText("候选对象依赖待确认地图观察，需复核后进入正史")).toBe(
      "待处理对象依赖待处理地图观察，需要人工检查后进入已采用",
    )
  })
})
