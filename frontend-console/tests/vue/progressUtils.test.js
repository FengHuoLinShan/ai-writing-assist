import { describe, expect, it } from "vitest"

import {
  authorFacingDiagnosticValue,
  authorFacingDiagnosticText,
  checkItems,
  errorItems,
  eventItems,
  timelineItems,
} from "../../vue/components/progressUtils.js"

describe("progressUtils 作者诊断投影", () => {
  it("可读错误保留原因但不暴露异常类名", () => {
    expect(authorFacingDiagnosticText("RuntimeError: 直接关联对象查读未完成，已保留进度供恢复")).toBe("直接关联对象查读未完成，已保留进度供恢复")
  })

  it("修复摘要中的阶段编号显示为作者可读步骤", () => {
    expect(authorFacingDiagnosticText("phase1a_scene_slicing 已尝试修复 1 次")).toBe("阶段 2 · 划分场景边界 已尝试修复 1 次")
  })

  it("递归转换 imports 真实嵌套错误字段与未知内部码", () => {
    const projected = authorFacingDiagnosticValue({
      phase2: {
        bulk_error_kind: "bulk_transport_v7",
        supplemental_error_kind: "provider_error",
        final_error_type: "schema_failure",
      },
    })

    expect(JSON.stringify(projected)).not.toMatch(
      /bulk_error_kind|supplemental_error_kind|final_error_type|bulk_transport_v7|provider_error|schema_failure/,
    )
    expect(projected.phase2).toEqual({
      批量处理原因: "需要人工检查",
      补充处理原因: "服务暂时不可用",
      最终失败原因: "结果格式未通过校验",
    })
  })

  it("事件、检查、时间线与阶段错误统一隐藏内部码", () => {
    const events = eventItems([{
      phase: "entity_extraction",
      status: "failed",
      message: "provider_error",
      details: { supplemental_error_kind: "transport_failure" },
    }])
    const checks = checkItems([{
      phase: "structure_analysis",
      message: "phase3_health_failed",
      details: { final_error_type: "schema_failure" },
    }])
    const timeline = timelineItems([{
      phase: "structure_analysis",
      status: "failed",
      bulk_error_kind: "unknown_bulk_code",
    }])
    const errors = errorItems([{
      phase: "entity_extraction",
      supplemental_error_kind: "provider_error",
      message: "schema_failure",
    }])
    const text = JSON.stringify({ events, checks, timeline, errors })

    expect(text).not.toMatch(
      /provider_error|transport_failure|phase3_health_failed|schema_failure|unknown_bulk_code|error_kind|error_type/,
    )
    expect(text).toContain("服务暂时不可用")
    expect(text).toContain("结果格式未通过校验")
    expect(text).toContain("需要人工检查")
  })
})
