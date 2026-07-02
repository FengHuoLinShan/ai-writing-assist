/**
 * llmSettingsView 测试
 *
 * 验证项目级 LLM 配置页的加载、模板切换和保存行为。
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import llmSettingsView from "../views/llmSettingsView.js"
import { resetState } from "./helpers.js"

const templates = [
  {
    id: "deepseek",
    name: "DeepSeek",
    category: "供应商",
    base_url: "https://api.deepseek.com/v1",
    default_model: "deepseek-chat",
    models: ["deepseek-chat", "deepseek-reasoner"],
    default_parameters: {
      timeout: 180,
      max_tokens: 4096,
      temperature: 0.3,
      top_p: null,
      extra: { reasoning_effort: "high" },
    },
  },
  {
    id: "kimi",
    name: "Kimi / Moonshot",
    category: "供应商",
    base_url: "https://api.moonshot.cn/v1",
    default_model: "moonshot-v1-8k",
    models: ["moonshot-v1-8k", "moonshot-v1-32k"],
    default_parameters: {
      timeout: 180,
      max_tokens: 8192,
      temperature: 0.2,
      top_p: 0.9,
      extra: {},
    },
  },
  {
    id: "mimo",
    name: "MiMo",
    category: "供应商",
    base_url: "",
    default_model: "",
    models: [],
    default_parameters: {
      timeout: 180,
      max_tokens: 4096,
      temperature: 0.3,
      top_p: null,
      extra: {},
    },
  },
]

beforeEach(() => {
  resetState()
  vi.clearAllMocks()
  api.projects.listLlmProviderTemplates = vi.fn()
  api.projects.getLlmSettings = vi.fn()
  api.projects.updateLlmSettings = vi.fn()
  state.currentProjectId = "p1"
  state.currentProject = { id: "p1", title: "测试项目" }
})

describe("llmSettingsView", () => {
  it("加载模板和当前设置并渲染脱敏状态", async () => {
    api.projects.listLlmProviderTemplates.mockResolvedValue({ items: templates })
    api.projects.getLlmSettings.mockResolvedValue({
      provider_id: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key_configured: true,
    })

    await llmSettingsView.onEnter()
    const html = await llmSettingsView.render()

    expect(api.projects.listLlmProviderTemplates).toHaveBeenCalledOnce()
    expect(api.projects.getLlmSettings).toHaveBeenCalledWith("p1")
    expect(html).toContain("DeepSeek")
    expect(html).toContain("Kimi / Moonshot")
    expect(html).toContain("MiMo")
    expect(html).toContain("已保存")
    expect(html).toContain("显示 Key")
    expect(html).not.toContain("sk-")
  })

  it("可以切换 API Key 输入框显示状态", async () => {
    api.projects.listLlmProviderTemplates.mockResolvedValue({ items: templates })
    api.projects.getLlmSettings.mockResolvedValue({})
    await llmSettingsView.onEnter()

    document.body.innerHTML = await llmSettingsView.render()
    llmSettingsView.bindEvents()

    const keyInput = document.getElementById("llm-api-key")
    document.getElementById("llm-toggle-api-key").click()

    expect(keyInput.type).toBe("text")
    expect(document.getElementById("llm-toggle-api-key").textContent).toContain("隐藏")
  })

  it("切换模板时填充 base URL 和默认模型", async () => {
    api.projects.listLlmProviderTemplates.mockResolvedValue({ items: templates })
    api.projects.getLlmSettings.mockResolvedValue({})
    await llmSettingsView.onEnter()

    document.body.innerHTML = await llmSettingsView.render()
    const provider = document.getElementById("llm-provider")
    const baseUrl = document.getElementById("llm-base-url")
    const model = document.getElementById("llm-model")
    const maxTokens = document.getElementById("llm-max-tokens")
    const temperature = document.getElementById("llm-temperature")
    const topP = document.getElementById("llm-top-p")

    provider.value = "kimi"
    llmSettingsView.applyTemplate("kimi")

    expect(baseUrl.value).toBe("https://api.moonshot.cn/v1")
    expect(model.value).toBe("moonshot-v1-8k")
    expect(maxTokens.value).toBe("8192")
    expect(temperature.value).toBe("0.2")
    expect(topP.value).toBe("0.9")
  })

  it("保存时提交项目级 LLM 配置", async () => {
    api.projects.listLlmProviderTemplates.mockResolvedValue({ items: templates })
    api.projects.getLlmSettings.mockResolvedValue({
      provider_id: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key_configured: false,
    })
    api.projects.updateLlmSettings.mockResolvedValue({ api_key_configured: true })
    await llmSettingsView.onEnter()

    document.body.innerHTML = await llmSettingsView.render()
    document.getElementById("llm-provider").value = "deepseek"
    document.getElementById("llm-base-url").value = "https://api.deepseek.com/v1"
    document.getElementById("llm-model").value = "deepseek-chat"
    document.getElementById("llm-timeout").value = "180"
    document.getElementById("llm-max-tokens").value = "8192"
    document.getElementById("llm-temperature").value = "0.2"
    document.getElementById("llm-top-p").value = "0.8"
    document.getElementById("llm-extra").value = '{"reasoning_effort":"high"}'
    document.getElementById("llm-api-key").value = "sk-user-input"

    await llmSettingsView.save()

    expect(api.projects.updateLlmSettings).toHaveBeenCalledWith("p1", {
      provider_id: "deepseek",
      label: "DeepSeek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      timeout: 180,
      max_tokens: 8192,
      temperature: 0.2,
      top_p: 0.8,
      extra: { reasoning_effort: "high" },
      api_key: "sk-user-input",
      clear_api_key: false,
    })
    expect(toast).toHaveBeenCalledWith("LLM 配置已保存", "success")
  })

  it("扩展参数不是 JSON object 时阻止保存", async () => {
    api.projects.listLlmProviderTemplates.mockResolvedValue({ items: templates })
    api.projects.getLlmSettings.mockResolvedValue({
      provider_id: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key_configured: false,
    })
    await llmSettingsView.onEnter()

    document.body.innerHTML = await llmSettingsView.render()
    document.getElementById("llm-extra").value = "[1,2,3]"

    await llmSettingsView.save()

    expect(api.projects.updateLlmSettings).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("供应商扩展参数必须是 JSON object", "warning")
  })
})
