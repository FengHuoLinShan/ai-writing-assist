import { describe, expect, it } from "vitest"

import { sceneCheckpointHistoryGroups, sceneFieldProvenance, sceneObjectStates } from "../../../vue/views/writing/sceneLensModel.js"

describe("sceneObjectStates", () => {
  it("maps object states with author-facing field labels and belief markers", () => {
    const result = sceneObjectStates([
      {
        subject_id: "entity-1",
        label: "铜钥匙",
        location: "灯塔下",
        fields: [
          { field: "custody_holder", display: "乙", layer: "fact", confidence: "derived", possibly_false: false },
          { field: "custody_owner", display: "甲", layer: "fact", confidence: "confirmed", possibly_false: false },
        ],
        knowledge: [
          { holder: "乙", text: "钥匙已归还甲", possibly_false: true },
        ],
      },
    ])

    expect(result).toHaveLength(1)
    expect(result[0].label).toBe("铜钥匙")
    expect(result[0].location).toBe("灯塔下")
    expect(result[0].fields.map((field) => field.label)).toEqual(["保管人", "所有人"])
    expect(result[0].fields[1].confirmed).toBe(true)
    expect(result[0].knowledge[0]).toMatchObject({ holder: "乙", possiblyFalse: true })
  })

  it("drops empty entries and tolerates missing payloads", () => {
    expect(sceneObjectStates(null)).toEqual([])
    expect(sceneObjectStates([{ subject_id: "x", label: "空对象", fields: [], knowledge: [] }])).toEqual([])
  })
})

describe("sceneFieldProvenance", () => {
  const hash = "a".repeat(64)

  it("normalizes an exact provenance record with reopenable draft ranges", () => {
    const result = sceneFieldProvenance({
      field: "custody_holder",
      event_id: "event-1",
      status: "exact",
      source_refs: [{
        draft_id: "draft-1",
        chapter_index: 2,
        version_number: 1,
        content_mode: "working",
        start_offset: 10,
        end_offset: 24,
        source_hash: hash,
        range_hash: "b".repeat(64),
      }],
    })

    expect(result.status).toBe("exact")
    expect(result.statusLabel).toBe("有据")
    expect(result.eventId).toBe("event-1")
    expect(result.refs).toHaveLength(1)
    expect(result.refs[0]).toMatchObject({
      draftId: "draft-1",
      chapterIndex: 2,
      version: 1,
      startOffset: 10,
      endOffset: 24,
      reopenable: true,
    })
  })

  it("keeps unverified provenance without inventing ranges", () => {
    const result = sceneFieldProvenance({
      field: "custody_owner",
      event_id: null,
      status: "unverified",
      source_refs: [],
    })

    expect(result.statusLabel).toBe("来源待核实")
    expect(result.refs).toEqual([])
  })

  it("rejects malformed provenance instead of faking evidence", () => {
    expect(sceneFieldProvenance(null)).toBeNull()
    expect(sceneFieldProvenance({ status: "maybe", source_refs: [] })).toBeNull()
    expect(sceneFieldProvenance({
      field: "opening_key_id",
      status: "exact",
      source_refs: [{ draft_id: "draft-1", chapter_index: "x", version_number: 1, content_mode: "working", start_offset: 0, end_offset: 3 }],
    }).refs).toEqual([])
  })

  it("marks refs without full fingerprints as not reopenable", () => {
    const result = sceneFieldProvenance({
      field: "location_id",
      status: "exact",
      source_refs: [{
        draft_id: "draft-1",
        chapter_index: 1,
        version_number: 1,
        content_mode: "working",
        start_offset: 0,
        end_offset: 5,
      }],
    })

    expect(result.refs[0].reopenable).toBe(false)
  })

  it("is attached to object fields from the lens source payload", () => {
    const states = sceneObjectStates([
      {
        subject_id: "entity-1",
        label: "铜钥匙",
        fields: [{
          field: "custody_holder",
          display: "乙",
          layer: "fact",
          confidence: "derived",
          source: {
            checkpoint_id: "checkpoint-1",
            provenance: { field: "custody_holder", event_id: "event-1", status: "conflict", source_refs: [] },
          },
        }],
      },
    ])

    expect(states[0].fields[0].provenance.statusLabel).toBe("来源冲突")
  })
})

describe("sceneCheckpointHistoryGroups", () => {
  it("groups history rows into author-facing version batches", () => {
    const groups = sceneCheckpointHistoryGroups([
      { checkpoint_id: "cp-2", dimension: "entities", chapter_index: 2, version: 2, is_current: true, has_field_provenance: true, created_at: "2026-10-07T12:00:00Z" },
      { checkpoint_id: "cp-3", dimension: "locations", chapter_index: 2, version: 2, is_current: true, has_field_provenance: true, created_at: "2026-10-07T12:00:01Z" },
      { checkpoint_id: "cp-1", dimension: "entities", chapter_index: 2, version: 1, is_current: false, has_field_provenance: false, created_at: "2026-10-06T09:00:00Z" },
    ])

    expect(groups).toHaveLength(2)
    expect(groups[0].isCurrent).toBe(true)
    expect(groups[0].hasFieldProvenance).toBe(true)
    expect(groups[0].dimensionLabels).toEqual(["人物与对象", "空间与位置"])
    expect(groups[0].checkpoints.map((item) => item.checkpointId)).toEqual(["cp-2", "cp-3"])
    expect(groups[1].isCurrent).toBe(false)
    expect(groups[1].hasFieldProvenance).toBe(false)
  })

  it("tolerates missing chapter anchors and malformed rows", () => {
    const groups = sceneCheckpointHistoryGroups([
      { checkpoint_id: "cp-9", dimension: "entities", chapter_index: null, version: 1, is_current: false, has_field_provenance: false, created_at: null },
      { dimension: "entities" },
      null,
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0].chapterIndex).toBeNull()
    expect(groups[0].checkpoints).toHaveLength(1)
    expect(sceneCheckpointHistoryGroups(null)).toEqual([])
  })
})
