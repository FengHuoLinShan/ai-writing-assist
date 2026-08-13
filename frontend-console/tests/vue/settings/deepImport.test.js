/**
 * 深度导入纯逻辑测试 — 对应原 tests/settings/shared/deepImportFields.test.js。
 */
import { describe, it, expect } from "vitest"
import {
  DEEP_IMPORT_GROUPS,
  buildDeepImportPayload,
  deepImportFieldId,
  deepImportFormFromSettings,
} from "../../../vue/views/settings/logic/deepImport.js"

describe("deepImportFieldId", () => {
  it("生成与原实现一致的 DOM id", () => {
    expect(deepImportFieldId("phase0", "target_input_chars")).toBe("deep-import-phase0-target-input-chars")
    expect(deepImportFieldId("phase2", "batch_size_scenes")).toBe("deep-import-phase2-batch-size-scenes")
  })
})

describe("deepImportFormFromSettings", () => {
  it("未覆盖时取内嵌默认值", () => {
    const form = deepImportFormFromSettings({})
    expect(form.phase0.target_input_chars).toBe("72000")
    expect(form.phase1c.decision_max_tokens).toBe("")
    expect(form.phase2.boundary_supplement_enabled).toBe("false")
    expect(form.phase1b.use_llm).toBe("")
  })

  it("已覆盖字段优先", () => {
    const form = deepImportFormFromSettings({
      phase0: { target_input_chars: 5000 },
      phase2: { boundary_supplement_enabled: true },
      phase1b: { use_llm: false },
    })
    expect(form.phase0.target_input_chars).toBe("5000")
    expect(form.phase2.boundary_supplement_enabled).toBe("true")
    expect(form.phase1b.use_llm).toBe("false")
  })
})

describe("buildDeepImportPayload", () => {
  it("空表单回退默认值，产出完整分组结构", () => {
    const form = deepImportFormFromSettings({})
    const out = buildDeepImportPayload(form)
    expect(out.ok).toBe(true)
    expect(out.value.phase0.target_input_chars).toBe(72000)
    expect(out.value.phase1c.decision_max_tokens).toBeNull()
    expect(Object.keys(out.value)).toEqual(DEEP_IMPORT_GROUPS.map((g) => g.id))
  })

  it("越界输入返回带字段名的错误（与原 readDeepImportFields 一致）", () => {
    const form = deepImportFormFromSettings({})
    form.phase0.target_input_chars = "10"
    const out = buildDeepImportPayload(form)
    expect(out.ok).toBe(false)
    expect(out.groupId).toBe("phase0")
    expect(out.fieldKey).toBe("target_input_chars")
    expect(out.error).toContain("必须是")
    expect(out.error).toContain("1000-500000")
  })

  it("int 字段拒绝小数，float 字段接受", () => {
    const form = deepImportFormFromSettings({})
    form.phase0.max_chapters_per_window = "1.5"
    expect(buildDeepImportPayload(form).ok).toBe(false)

    const form2 = deepImportFormFromSettings({})
    form2.phase0.max_tokens_per_input_char = "1.25"
    const out = buildDeepImportPayload(form2)
    expect(out.ok).toBe(true)
    expect(out.value.phase0.max_tokens_per_input_char).toBe(1.25)
  })

  it("bool 与 nullableBool 解析", () => {
    const form = deepImportFormFromSettings({
      phase2: { boundary_supplement_enabled: true },
      phase1b: { use_llm: true },
    })
    const out = buildDeepImportPayload(form)
    expect(out.ok).toBe(true)
    expect(out.value.phase2.boundary_supplement_enabled).toBe(true)
    expect(out.value.phase1b.use_llm).toBe(true)

    const form2 = deepImportFormFromSettings({})
    form2.phase1b.use_llm = ""
    expect(buildDeepImportPayload(form2).value.phase1b.use_llm).toBe("")
  })
})
