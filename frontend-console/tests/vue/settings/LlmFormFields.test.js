/**
 * LlmFormFields 组件测试 — 对应原 llmFormFields.test.js 的 DOM 行为契约。
 */
import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import LlmFormFields from "../../../vue/views/settings/components/LlmFormFields.vue"

const DEEPSEEK_TEMPLATE = {
  id: "deepseek",
  name: "DeepSeek",
  base_url: "https://api.deepseek.com",
  default_model: "deepseek-v4-flash",
  models: ["deepseek-v4-flash", "deepseek-v4-pro"],
  default_parameters: { timeout: 180, max_tokens: 12000, temperature: 0.3, top_p: null, extra: {} },
}
const OTHER_TEMPLATE = {
  id: "other",
  name: "Other",
  base_url: "https://other.example.com/v1",
  default_model: "other-model",
  models: ["other-model"],
  default_parameters: { timeout: 60, max_tokens: 4096, temperature: 0.7, top_p: 0.9, extra: { stream: true } },
}

function makeForm(overrides = {}) {
  return {
    provider_id: "deepseek",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
    timeout: "180",
    max_tokens: "12000",
    temperature: "0.3",
    top_p: "",
    extraJson: "",
    api_key: "",
    clear_api_key: false,
    ...overrides,
  }
}

function mountFields({ form = makeForm(), ...props } = {}) {
  return mount(LlmFormFields, {
    props: { modelValue: form, templates: [DEEPSEEK_TEMPLATE], ...props },
  })
}

describe("渲染契约", () => {
  it("渲染全部字段 id（e2e 依赖）", () => {
    const wrapper = mountFields()
    for (const id of [
      "llm-provider", "llm-base-url", "llm-model", "llm-label",
      "llm-timeout", "llm-max-tokens", "llm-temperature", "llm-top-p", "llm-extra",
      "llm-api-key", "llm-toggle-api-key", "llm-clear-api-key", "llm-key-status",
    ]) {
      expect(wrapper.find(`#${id}`).exists(), `#${id}`).toBe(true)
    }
    expect(wrapper.find(".llm-main-form").exists()).toBe(true)
    expect(wrapper.findAll(".llm-preset-item")).toHaveLength(4)
  })

  it("withApiKey=false 隐藏 Key 区并显示全局提示", () => {
    const wrapper = mountFields({ withApiKey: false })
    expect(wrapper.find("#llm-api-key").exists()).toBe(false)
    expect(wrapper.find(".llm-global-hint").text()).toContain("全局默认不存 API Key")
  })

  it("无模板时供应商下拉禁用且回退 DeepSeek 占位", () => {
    const wrapper = mountFields({ templates: [] })
    const select = wrapper.find("#llm-provider")
    expect(select.attributes("disabled")).toBeDefined()
    expect(select.findAll("option")).toHaveLength(1)
    expect(select.find("option").text()).toBe("DeepSeek")
  })
})

describe("API Key 可见性切换（原 bindLLMApiKeyEvents 契约）", () => {
  it("切换 input type 与按钮文案，已输入值不丢失", async () => {
    const form = makeForm()
    const wrapper = mountFields({ form })
    const input = wrapper.find("#llm-api-key")
    const toggle = wrapper.find("#llm-toggle-api-key")

    await input.setValue("test-key-not-real")
    expect(form.api_key).toBe("test-key-not-real")
    expect(input.element.type).toBe("password")

    await toggle.trigger("click")
    expect(input.element.type).toBe("text")
    expect(toggle.text()).toBe("隐藏 Key")
    expect(toggle.attributes("aria-pressed")).toBe("true")
    expect(form.api_key).toBe("test-key-not-real")

    await toggle.trigger("click")
    expect(input.element.type).toBe("password")
    expect(toggle.text()).toBe("显示 Key")
    expect(toggle.attributes("aria-pressed")).toBe("false")
  })
})

describe("创作模式预设", () => {
  it("点击预设写入 temperature/top_p 并高亮；custom 仅高亮", async () => {
    const form = makeForm()
    const wrapper = mountFields({ form })

    await wrapper.find('[data-preset-id="creative"]').trigger("click")
    expect(form.temperature).toBe("0.9")
    expect(form.top_p).toBe("0.95")
    expect(wrapper.find('[data-preset-id="creative"]').classes()).toContain("active")

    await wrapper.find('[data-preset-id="custom"]').trigger("click")
    expect(form.temperature).toBe("0.9")
    expect(wrapper.find('[data-preset-id="custom"]').classes()).toContain("active")
  })

  it("参数与预设均不匹配时 custom 高亮（初始默认态）", () => {
    const wrapper = mountFields()
    expect(wrapper.find('[data-preset-id="custom"]').classes()).toContain("active")
  })
})

describe("供应商模板联动（原 bindLLMProviderTemplateEvents 契约）", () => {
  it("切换供应商回填模板字段、清空 Key、更新状态与 datalist", async () => {
    const form = makeForm({ api_key: "old-key", clear_api_key: true })
    const wrapper = mountFields({ form, templates: [DEEPSEEK_TEMPLATE, OTHER_TEMPLATE] })

    await wrapper.find("#llm-provider").setValue("other")
    expect(form.base_url).toBe("https://other.example.com/v1")
    expect(form.model).toBe("other-model")
    expect(form.label).toBe("Other")
    expect(form.timeout).toBe("60")
    expect(form.max_tokens).toBe("4096")
    expect(form.temperature).toBe("0.7")
    expect(form.top_p).toBe("0.9")
    expect(form.extraJson).toBe(JSON.stringify({ stream: true }, null, 2))
    expect(form.api_key).toBe("")
    expect(form.clear_api_key).toBe(false)
    expect(wrapper.find("#llm-key-status").text()).toBe("此模板未保存")
    expect(wrapper.findAll("#llm-model-options option")).toHaveLength(1)
  })

  it("已配置 Key 的模板显示已保存到此模板", async () => {
    const form = makeForm()
    const wrapper = mountFields({
      form,
      templates: [DEEPSEEK_TEMPLATE, OTHER_TEMPLATE],
      configuredProviders: ["other"],
    })
    await wrapper.find("#llm-provider").setValue("other")
    expect(wrapper.find("#llm-key-status").text()).toBe("已保存到此模板")
    expect(wrapper.find("#llm-key-status").classes()).toContain("success")
  })

  it("初始状态按 apiKeyConfigured 显示已保存/未保存", () => {
    expect(mountFields({ apiKeyConfigured: true }).find("#llm-key-status").text()).toBe("已保存")
    expect(mountFields({ apiKeyConfigured: false }).find("#llm-key-status").text()).toBe("未保存")
  })
})

describe("模型成本提示", () => {
  it("仅 deepseek-v4-pro 显示提示", async () => {
    const wrapper = mountFields()
    const hint = wrapper.find("#llm-model-cost-hint")
    expect(hint.attributes("hidden")).toBeDefined()

    await wrapper.find("#llm-model").setValue("deepseek-v4-pro")
    expect(wrapper.find("#llm-model-cost-hint").attributes("hidden")).toBeUndefined()
  })
})

describe("来源标签", () => {
  it("sourceMap 提供时渲染 settings-field-source", () => {
    const wrapper = mountFields({
      sourceMap: { provider_id: { value: "deepseek", source: "global" } },
    })
    const source = wrapper.find(".settings-field-source")
    expect(source.exists()).toBe(true)
    expect(source.text()).toContain("继承全局")
    expect(source.text()).toContain("deepseek")
  })

  it("Key 已配置且供应商/BaseURL 来自全局或系统时显示匹配警告", () => {
    const wrapper = mountFields({
      apiKeyConfigured: true,
      sourceMap: {
        provider_id: { value: "deepseek", source: "global" },
        base_url: { value: "https://api.deepseek.com", source: "system" },
      },
    })
    expect(wrapper.find(".settings-key-mismatch-warning").exists()).toBe(true)
  })
})
