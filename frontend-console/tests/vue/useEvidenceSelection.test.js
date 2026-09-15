import { beforeEach, describe, expect, it } from "vitest"

import { useEvidenceSelection } from "../../vue/composables/useEvidenceSelection.js"

describe("useEvidenceSelection 双分区", () => {
  beforeEach(() => sessionStorage.clear())

  it("分开保存生成资料与仅复核资料", () => {
    const selection = useEvidenceSelection(() => "novel-1:writing")
    selection.add({ kind: "target", target_ref: { target_type: "core_entity", target_id: "a" } })
    selection.addAudit({ kind: "target", target_ref: { target_type: "world_bible_page", target_id: "b" } })

    expect(selection.refs.value).toHaveLength(1)
    expect(selection.auditRefs.value).toHaveLength(1)
    expect(selection.refs.value[0]).toEqual({
      kind: "target",
      target_ref: { target_type: "core_entity", target_id: "a" },
    })
    expect(selection.auditRefs.value[0]).toEqual({
      kind: "target",
      target_ref: { target_type: "world_bible_page", target_id: "b" },
    })
  })
})
