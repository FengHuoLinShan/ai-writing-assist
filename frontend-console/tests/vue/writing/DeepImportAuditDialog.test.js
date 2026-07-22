import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import DeepImportAuditDialog from "../../../vue/views/writing/components/DeepImportAuditDialog.vue"

describe("DeepImportAuditDialog", () => {
  it("以 Vue 文本节点展示质量、产物、验收、诊断、限流和快照审计", () => {
    const wrapper = mount(DeepImportAuditDialog, {
      props: {
        open: true,
        progress: {
          assetSummary: { scenes: 3 },
          qualityStats: {
            schema_422_rate: "2%",
            phase3: {
              error_kind: "schema_failure",
              bulk_error_kind: "unknown_bulk_code",
              supplemental_error_kind: "provider_error",
              final_error_type: "invalid_response",
            },
          },
          qualityRerun: { rounds: 1 },
          phaseArtifacts: { phase1: { retained: "<img src=x>", error_kind: "provider_error" } },
          acceptanceChecks: [{ name: "coverage", passed: true }],
          diagnosticCounts: { warnings: 2 },
          throttleReasons: ["budget"],
          phaseErrors: [{ phase: "phase2", error: "<script>" }],
          auditSummary: { latest_failure: null },
          recoverySummary: { deprecated_scenes: 1 },
          lifecycle: { state: "done" },
        },
      },
    })
    for (const text of ["资产摘要", "schema_422_rate", "phase1", "coverage", "warnings", "budget", "phase2", "快照健康", "恢复摘要"]) {
      expect(wrapper.text()).toContain(text)
    }
    expect(wrapper.text()).toContain("<img src=x>")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("error_kind")
    expect(wrapper.text()).not.toContain("schema_failure")
    expect(wrapper.text()).not.toContain("provider_error")
    expect(wrapper.text()).not.toContain("bulk_error_kind")
    expect(wrapper.text()).not.toContain("supplemental_error_kind")
    expect(wrapper.text()).not.toContain("final_error_type")
    expect(wrapper.text()).not.toContain("unknown_bulk_code")
    expect(wrapper.text()).toContain("结果格式未通过校验")
    expect(wrapper.text()).toContain("服务暂时不可用")
  })
})
