import { describe, expect, it } from "vitest"
import { buildMapDiagnosticInfo, formatMapDiagnosticInfo } from "../views/mapDiagnosticInfo.js"

describe("mapDiagnosticInfo", () => {
  it("keeps only the diagnostic allowlist and strips secrets", () => {
    const result = buildMapDiagnosticInfo({
      item_kind: "observation",
      item_id: "obs-1",
      target_entity_id: "entity-1",
      normalization_error: "unknown location",
      source_ref: {
        workflow_id: "workflow-1",
        source_id: "source-1",
        api_key: "do-not-copy",
        prompt: "private prompt",
        nested_payload: { token: "nope" },
      },
      evidence_text: "正文内容不应进入诊断复制",
    }, { mapId: "map-1" })

    expect(result).toEqual({
      kind: "observation",
      map_id: "map-1",
      observation_id: "obs-1",
      entity_id: "entity-1",
      normalization_error: "unknown location",
      source_ref: { workflow_id: "workflow-1", source_id: "source-1" },
    })
    expect(JSON.stringify(result)).not.toMatch(/do-not-copy|private prompt|正文内容/)
  })

  it("removes URL query strings and remains inert text", () => {
    const text = formatMapDiagnosticInfo({
      item_kind: "fact",
      item_id: "fact-1",
      normalization_error: "请检查 https://example.test/error?token=secret#details",
      source_ref: {
        source_id: "https://example.test/source?id=secret#part",
        workflow: '<img src=x onerror="alert(1)">',
      },
    })

    expect(text).toContain("https://example.test/source#part")
    expect(text).toContain("https://example.test/error#details")
    expect(text).not.toContain("id=secret")
    expect(text).not.toContain("token=secret")
    expect(text).toContain('<img src=x onerror=\\"alert(1)\\">')
  })

  it("drops non-scalar top-level values instead of copying nested payloads", () => {
    const result = buildMapDiagnosticInfo({
      item_kind: "observation",
      item_id: { token: "secret", raw: "must-not-copy" },
      normalization_message: { prompt: "private", message: "must-not-copy" },
      revision: ["unexpected", { password: "secret" }],
      source_ref: { workflow_id: "workflow-1" },
    })

    expect(result).toEqual({
      kind: "observation",
      source_ref: { workflow_id: "workflow-1" },
    })
    expect(JSON.stringify(result)).not.toMatch(/secret|must-not-copy|private|unexpected/)
  })
})
