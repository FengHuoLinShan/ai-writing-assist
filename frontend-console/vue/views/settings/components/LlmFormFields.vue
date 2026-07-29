<script setup>
import { computed, ref, watch } from "vue"
import SourceLabel from "./SourceLabel.vue"
import {
  CREATIVE_PRESETS,
  detectCreativeMode,
  modelsForProvider,
  providerTemplatePatch,
} from "../logic/llmForm.js"

/**
 * LLM 设置表单（全局默认 / 项目主配置共用）。
 * DOM 契约与 vanilla renderLLMFormFields 保持一致：id、class、source 标签位置。
 * 表单对象为 v-model（同一对象引用，深属性变更无需 emit）。
 */
const form = defineModel({ type: Object, required: true })

const props = defineProps({
  templates: { type: Array, default: () => [] },
  /** 项目模式下的字段来源映射（effective-llm-settings 原样），全局模式为空对象 */
  sourceMap: { type: Object, default: () => ({}) },
  withApiKey: { type: Boolean, default: true },
  apiKeyConfigured: { type: Boolean, default: false },
  configuredProviders: { type: Array, default: () => [] },
})

const showKey = ref(false)
// 预设高亮 = 初始按参数检测 + 点击后跟随最后点击项（vanilla bindLLMPresetEvents 契约；
// 手动改参数或模板联动不回写高亮，与 vanilla 一致）
const activePreset = ref(detectCreativeMode(form.value))

const modelOptions = computed(() => modelsForProvider(props.templates, form.value.provider_id))
const modelCostHintVisible = computed(() => String(form.value.model ?? "").trim() === "deepseek-v4-pro")

// 加载时的供应商：effective 值（sourceMap）或挂载时点表单值的快照。
// 必须是快照而非 computed——否则组件重挂载后无法识别"未保存的供应商切换"
// （跨 Tab 往返时表单对象保留，挂载快照才是不变基准）。
const loadedProviderId = props.sourceMap?.provider_id?.value ?? form.value.provider_id

const keyStatus = computed(() => {
  if (form.value.provider_id !== loadedProviderId) {
    const hasKey = props.configuredProviders.includes(form.value.provider_id)
    return { text: hasKey ? "已保存到此模板" : "此模板未保存", ok: hasKey }
  }
  return props.apiKeyConfigured
    ? { text: "已保存", ok: true }
    : { text: "未保存", ok: false }
})

const keyMismatchWarning = computed(() => {
  if (!props.withApiKey || !props.apiKeyConfigured) return false
  const sources = [props.sourceMap?.provider_id?.source, props.sourceMap?.base_url?.source]
  return sources.some((source) => source === "global" || source === "system")
})

watch(() => form.value.provider_id, (providerId) => {
  const patch = providerTemplatePatch(props.templates, providerId)
  if (!patch) return
  Object.assign(form.value, patch)
  form.value.api_key = ""
  form.value.clear_api_key = false
})

function applyPreset(presetId) {
  const preset = CREATIVE_PRESETS[presetId]
  if (!preset) return
  if (presetId !== "custom") {
    form.value.temperature = String(preset.temperature)
    form.value.top_p = String(preset.top_p)
  }
  activePreset.value = presetId
}

function presetSummary(presetId, preset) {
  return presetId === "custom" ? "保留当前参数" : `T ${preset.temperature} · P ${preset.top_p}`
}
</script>

<template>
  <div class="llm-main-form">
    <p v-if="!withApiKey" class="llm-global-hint">模型 Key 在账户级模型连接中统一管理。</p>
    <div class="form-row">
      <div class="form-group">
        <label for="llm-provider">供应商模板</label>
        <select class="form-input" id="llm-provider" v-model="form.provider_id" :disabled="!templates.length">
          <option v-if="!templates.length" value="deepseek">DeepSeek</option>
          <option v-for="template in templates" :key="template.id" :value="template.id">{{ template.name }}</option>
        </select>
        <div v-if="sourceMap.provider_id" class="settings-field-source">
          <SourceLabel :source="sourceMap.provider_id.source" :value="sourceMap.provider_id.value" />
        </div>
      </div>
      <div v-if="withApiKey" class="form-group">
        <label>API Key</label>
        <div class="settings-key-row">
          <input
            class="form-input"
            id="llm-api-key"
            :type="showKey ? 'text' : 'password'"
            autocomplete="off"
            placeholder="留空保留已保存密钥"
            v-model="form.api_key"
          />
          <button
            class="btn btn-sm"
            id="llm-toggle-api-key"
            type="button"
            :aria-pressed="String(showKey)"
            @click="showKey = !showKey"
          >{{ showKey ? "隐藏 Key" : "显示 Key" }}</button>
          <label class="llm-clear-key">
            <input id="llm-clear-api-key" type="checkbox" v-model="form.clear_api_key" />
            清除
          </label>
        </div>
        <div id="llm-key-status" class="settings-key-status" :class="keyStatus.ok ? 'success' : 'muted'">{{ keyStatus.text }}</div>
        <p v-if="keyMismatchWarning" class="settings-key-mismatch-warning">当前供应商/BaseURL 来自全局或系统默认，请确认 Key 与该供应商匹配</p>
      </div>
    </div>
    <div class="form-group">
      <label for="llm-base-url">Base URL</label>
      <input class="form-input" id="llm-base-url" v-model="form.base_url" placeholder="https://api.example.com/v1" />
      <div v-if="sourceMap.base_url" class="settings-field-source">
        <SourceLabel :source="sourceMap.base_url.source" :value="sourceMap.base_url.value" />
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label for="llm-model">模型</label>
        <input class="form-input" id="llm-model" list="llm-model-options" v-model="form.model" placeholder="输入或选择模型名" />
        <datalist id="llm-model-options">
          <option v-for="model in modelOptions" :key="model" :value="model"></option>
        </datalist>
        <small id="llm-model-cost-hint" class="settings-section-hint" :hidden="!modelCostHintVisible">deepseek-v4-pro 预计约为 Flash 的 8 倍耗时；高质量开关不会自动切换模型。</small>
        <div v-if="sourceMap.model" class="settings-field-source">
          <SourceLabel :source="sourceMap.model.source" :value="sourceMap.model.value" />
        </div>
      </div>
      <div class="form-group">
        <label for="llm-label">显示名称</label>
        <input class="form-input" id="llm-label" v-model="form.label" placeholder="可选" />
        <div v-if="sourceMap.label" class="settings-field-source">
          <SourceLabel :source="sourceMap.label.source" :value="sourceMap.label.value" />
        </div>
      </div>
    </div>
    <div class="llm-advanced-panel">
      <div class="form-group">
        <label>创作模式</label>
        <div class="llm-preset-list">
          <button
            v-for="(preset, presetId) in CREATIVE_PRESETS"
            :key="presetId"
            class="llm-preset-item"
            :class="{ active: activePreset === presetId }"
            type="button"
            :data-preset-id="presetId"
            @click="applyPreset(presetId)"
          >
            <span>{{ preset.label }}</span>
            <small>{{ presetSummary(presetId, preset) }}</small>
          </button>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="llm-timeout">超时（秒）</label>
          <input class="form-input" id="llm-timeout" type="number" min="1" max="3600" v-model="form.timeout" placeholder="180" />
          <div v-if="sourceMap.timeout" class="settings-field-source">
            <SourceLabel :source="sourceMap.timeout.source" :value="sourceMap.timeout.value" />
          </div>
        </div>
        <div class="form-group">
          <label for="llm-max-tokens">默认输出上限（tokens）</label>
          <input class="form-input" id="llm-max-tokens" type="number" min="1" max="200000" v-model="form.max_tokens" placeholder="12000" />
          <small class="settings-section-hint">深度导入以外的业务 LLM 调用继承此值。</small>
          <div v-if="sourceMap.max_tokens" class="settings-field-source">
            <SourceLabel :source="sourceMap.max_tokens.source" :value="sourceMap.max_tokens.value" />
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="llm-temperature">Temperature</label>
          <input class="form-input" id="llm-temperature" type="number" min="0" max="2" step="0.1" v-model="form.temperature" placeholder="0.3" />
          <div v-if="sourceMap.temperature" class="settings-field-source">
            <SourceLabel :source="sourceMap.temperature.source" :value="sourceMap.temperature.value" />
          </div>
        </div>
        <div class="form-group">
          <label for="llm-top-p">Top P</label>
          <input class="form-input" id="llm-top-p" type="number" min="0" max="1" step="0.05" v-model="form.top_p" placeholder="可选" />
          <div v-if="sourceMap.top_p" class="settings-field-source">
            <SourceLabel :source="sourceMap.top_p.source" :value="sourceMap.top_p.value" />
          </div>
        </div>
      </div>
      <div class="form-group">
        <label for="llm-extra">供应商扩展参数（JSON）</label>
        <textarea class="form-input llm-extra-json" id="llm-extra" rows="4" placeholder='{"reasoning_effort":"high"}' v-model="form.extraJson"></textarea>
        <div v-if="sourceMap.extra" class="settings-field-source">
          <SourceLabel :source="sourceMap.extra.source" :value="sourceMap.extra.value" />
        </div>
      </div>
    </div>
  </div>
</template>
