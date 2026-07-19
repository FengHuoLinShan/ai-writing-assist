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
          qualityStats: { schema_422_rate: "2%" },
          qualityRerun: { rounds: 1 },
          phaseArtifacts: { phase1: { retained: "<img src=x>" } },
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
  })
})
