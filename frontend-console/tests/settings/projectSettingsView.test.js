/**
 * projectSettingsView 测试
 *
 * 依赖 tests/setup.js 提供的全局 api/state/router/toast/esc mocks。
 * 不使用 vi.mock —— 生产代码通过全局标识符访问这些模块。
 */
import { describe, it, expect, beforeEach } from "vitest"
import projectSettingsView from "../../views/settings/projectSettingsView.js"
import { resetState } from "../helpers.js"

describe("projectSettingsView", () => {
  beforeEach(() => {
    resetState()
    projectSettingsView._projectId = null
    projectSettingsView._effectiveLLM = null
    projectSettingsView._effectivePrefs = null
    projectSettingsView._templates = []
    projectSettingsView._tab = "main"
  })

  it("renders empty state when no project id", async () => {
    projectSettingsView._projectId = null
    projectSettingsView._effectiveLLM = null
    projectSettingsView._effectivePrefs = null
    const html = await projectSettingsView.render()
    expect(html).toContain("请先进入项目")
    expect(html).toContain("返回全局设置")
  })

  it("renders tabs when effective data loaded", async () => {
    projectSettingsView._projectId = "abc"
    projectSettingsView._tab = "main"
    projectSettingsView._effectiveLLM = {
      provider_id: { value: "x", source: "system" },
      label: { value: null, source: "unset" },
      base_url: { value: "", source: "system" },
      model: { value: "", source: "system" },
      timeout: { value: 180, source: "system" },
      max_tokens: { value: 12000, source: "system" },
      temperature: { value: 0.3, source: "system" },
      top_p: { value: null, source: "unset" },
      extra: { value: {}, source: "system" },
      creative_mode: { value: null, source: "unset" },
      api_key_configured: { value: false, source: "unset" },
      deep_import: { value: null, source: "system" },
    }
    projectSettingsView._effectivePrefs = {
      daily_goal: { value: null, source: "system" },
      editor_font: { value: "system", source: "system" },
      default_focus_mode: { value: false, source: "system" },
    }
    projectSettingsView._templates = []
    const html = await projectSettingsView.render()
    expect(html).toContain("主配置")
    expect(html).toContain("深度导入")
    expect(html).toContain("作者偏好")

    projectSettingsView._tab = "deep"
    const deepHtml = await projectSettingsView.render()
    expect(deepHtml).toContain("深度导入不继承“默认输出上限”")
  })
})
