/**
 * globalSettingsView 测试
 */

import { describe, it, expect, beforeEach } from "vitest"
import globalSettingsView from "../../views/settings/globalSettingsView.js"
import { resetState } from "../helpers.js"

describe("globalSettingsView", () => {
  beforeEach(() => {
    resetState()
    globalSettingsView._llmDefaults = {}
    globalSettingsView._authorPrefs = {}
    globalSettingsView._projectsUsingDefaults = { items: [], total: 0, truncated: false }
  })

  it("renders empty hint when no projects inherit", () => {
    globalSettingsView._projectsUsingDefaults = { items: [], total: 0, truncated: false }
    const html = globalSettingsView._renderProjectsUsingDefaults()
    expect(html).toContain("没有项目继承全局默认")
  })

  it("renders truncated tail when truncated=true", () => {
    globalSettingsView._projectsUsingDefaults = {
      items: [{ project_id: "x", title: "p1", inherited_fields: [] }],
      total: 200,
      truncated: true,
    }
    const html = globalSettingsView._renderProjectsUsingDefaults()
    expect(html).toContain("更多项目省略")
  })

  it("renders section headers and disabled enter-project button when no current project", async () => {
    state.currentProjectId = null
    globalSettingsView._llmDefaults = {}
    globalSettingsView._authorPrefs = {}
    const html = await globalSettingsView.render()
    expect(html).toContain("全局设置")
    expect(html).toContain("owner: local")
    expect(html).toContain("LLM 全局默认")
    expect(html).toContain("作者偏好全局默认")
    expect(html).toContain("本地迁移")
    expect(html).toContain("进入当前项目")
    const btnMatch = html.match(/<button[^>]*id="goto-recent-project-btn"[^>]*>/)
    expect(btnMatch).not.toBeNull()
    expect(btnMatch[0]).toContain("disabled")
  })

  it("enables enter-project button when state.currentProjectId is set", async () => {
    state.currentProjectId = "abc-123"
    const html = await globalSettingsView.render()
    const btnMatch = html.match(/<button[^>]*id="goto-recent-project-btn"[^>]*>/)
    expect(btnMatch).not.toBeNull()
    expect(btnMatch[0]).not.toContain("disabled")
    expect(html).toContain("进入当前项目")
  })
})
