<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import { getApi, getConfirm, getRouter, getToast, useStateKey } from "../../bridge/index.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { useSaveButton } from "../../composables/useSaveButton.js"
import { normalizeRpReturnTarget } from "../../shell/navigation.js"
import {
  authorFormFromDefaults,
  buildAuthorPrefsPayload,
  validateAuthorPreferences,
} from "./logic/authorPreferences.js"

const props = defineProps({
  llmConnections: { type: Object, default: null },
  llmBalances: { type: Object, default: () => ({ items: [] }) },
  authorPrefs: { type: Object, default: () => ({}) },
})

const currentProjectId = useStateKey("currentProjectId")
const connections = ref(props.llmConnections || {
  active_provider_id: "deepseek",
  providers: [],
})
const balances = ref(props.llmBalances?.items || [])
const selectedProviderId = ref(connections.value.active_provider_id || "deepseek")
const providerButtons = ref([])
const apiKey = ref("")
const balanceLoading = ref(false)
const authorForm = ref(authorFormFromDefaults(props.authorPrefs))
const authorBaseline = ref(JSON.stringify(authorForm.value))
const connectionButton = useSaveButton()
const authorButton = useSaveButton()
const returnTarget = normalizeRpReturnTarget(
  getRouter()?.getCurrentQuery?.()?.get?.("return_to"),
)
const returningToRp = Boolean(returnTarget)

const providers = computed(() => connections.value?.providers || [])
const selectedProvider = computed(() => (
  providers.value.find((item) => item.provider_id === selectedProviderId.value)
  || providers.value[0]
  || null
))

function selectProvider(providerId) {
  selectedProviderId.value = providerId
  apiKey.value = ""
}

function focusProvider(providerId) {
  void nextTick(() => {
    providerButtons.value
      .find((button) => button?.dataset?.providerId === providerId)
      ?.focus()
  })
}

function onProviderKeydown(event, providerId) {
  const currentIndex = providers.value.findIndex(
    (provider) => provider.provider_id === providerId,
  )
  if (currentIndex < 0) return
  let nextIndex = currentIndex
  if (["ArrowLeft", "ArrowUp"].includes(event.key)) {
    nextIndex = (currentIndex - 1 + providers.value.length) % providers.value.length
  } else if (["ArrowRight", "ArrowDown"].includes(event.key)) {
    nextIndex = (currentIndex + 1) % providers.value.length
  } else if (event.key === "Home") {
    nextIndex = 0
  } else if (event.key === "End") {
    nextIndex = providers.value.length - 1
  } else {
    return
  }
  event.preventDefault()
  const nextProviderId = providers.value[nextIndex]?.provider_id
  if (!nextProviderId) return
  if (nextProviderId === selectedProviderId.value) {
    focusProvider(nextProviderId)
    return
  }
  selectProvider(nextProviderId)
  focusProvider(nextProviderId)
}

function balanceFor(providerId) {
  return balances.value.find((item) => item.provider_id === providerId) || null
}

function gotoRecentProject() {
  if (currentProjectId.value) getRouter().navigate("project-settings")
}

async function returnAfterConnection() {
  if (!returnTarget) return
  if (returnTarget === "journeys") {
    await getRouter().navigate("journeys")
    return
  }
  if (returnTarget === "journeys:new") {
    await getRouter().navigate("journeys", "new")
    return
  }
  const journeyId = returnTarget.slice("interaction:".length)
  await getRouter().navigate("interaction", journeyId)
}

async function refreshBalances() {
  balanceLoading.value = true
  try {
    const response = await getApi().settings.listLLMBalances()
    balances.value = response?.items || []
  } catch {
    balances.value = providers.value
      .filter((provider) => provider.connected)
      .map((provider) => ({
        provider_id: provider.provider_id,
        status: "unavailable",
      }))
  } finally {
    balanceLoading.value = false
  }
}

async function saveConnection() {
  const provider = selectedProvider.value
  if (!provider) return
  const key = apiKey.value.trim()
  if (!key && !provider.connected) {
    getToast()("请先填写 API Key", "warning")
    return
  }

  connectionButton.saving.value = true
  try {
    const response = key
      ? await getApi().settings.connectLLMProvider(provider.provider_id, key)
      : await getApi().settings.activateLLMProvider(provider.provider_id)
    if (response?.providers) connections.value = response
    apiKey.value = ""
    getToast()(`已启用 ${provider.label}，之后的新生成会使用此模型`, "success")
    await refreshBalances()
    await returnAfterConnection()
  } catch (err) {
    getToast()(err.message || "模型连接验证失败", "error")
    connectionButton.flashError()
  } finally {
    connectionButton.saving.value = false
  }
}

async function clearConnection() {
  const provider = selectedProvider.value
  if (!provider?.connected) return
  if (!getConfirm()(
    `清除 ${provider.label} 的 API Key？已有内容不会受影响；重新连接前，作者创作与 RP 的新生成都会暂停。`,
  )) return
  try {
    const response = await getApi().settings.clearLLMProvider(provider.provider_id)
    if (response?.providers) connections.value = response
    apiKey.value = ""
    balances.value = balances.value.filter(
      (item) => item.provider_id !== provider.provider_id,
    )
    getToast()(`${provider.label} 已断开`, "success")
  } catch (err) {
    getToast()(err.message || "断开失败", "error")
  }
}

async function saveAuthor() {
  const toast = getToast()
  const submittedForm = JSON.stringify(authorForm.value)
  const prefs = buildAuthorPrefsPayload(authorForm.value)
  const validation = validateAuthorPreferences(prefs)
  if (!validation.ok) return toast(validation.message, "warning")
  authorButton.saving.value = true
  try {
    await getApi().settings.updateGlobalAuthorPrefs(prefs)
    if (JSON.stringify(authorForm.value) === submittedForm) {
      authorBaseline.value = submittedForm
    }
    toast("作者偏好已保存", "success")
  } catch (err) {
    toast(err.message || "保存失败", "error")
    authorButton.flashError()
  } finally {
    authorButton.saving.value = false
  }
}

function hasUnsavedChanges() {
  return Boolean(apiKey.value)
    || JSON.stringify(authorForm.value) !== authorBaseline.value
}

useLeaveGuard(() => (
  !hasUnsavedChanges()
  || getConfirm()("账户设置有未保存修改，确定放弃并离开吗？")
))

function beforeUnload(event) {
  if (!hasUnsavedChanges()) return
  event.preventDefault()
  event.returnValue = ""
}

onMounted(() => window.addEventListener("beforeunload", beforeUnload))
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload))
</script>

<template>
  <div class="global-settings-view account-settings-view">
    <div class="view-header section-header">
      <div class="view-header__title account-settings-title">
        <button
          v-if="returningToRp"
          class="rp-icon-button"
          type="button"
          aria-label="返回旅程"
          @click="returnAfterConnection"
        >‹</button>
        <h2>账户设置</h2>
      </div>
      <div class="view-header__actions">
        <button
          v-if="!returningToRp"
          id="goto-recent-project-btn"
          class="btn btn-sm btn-link"
          :disabled="!currentProjectId"
          @click="gotoRecentProject"
        >进入当前项目 →</button>
      </div>
    </div>

    <section class="settings-section account-connection-section" :aria-busy="connectionButton.saving.value || balanceLoading">
      <h3>模型连接</h3>
      <p class="settings-section-hint">
        作者创作和 RP 旅程共用这里选择的模型，只影响之后的新生成。
        <template v-if="returnTarget">连接成功后会回到刚才的旅程位置。</template>
      </p>

      <div class="account-provider-options" role="radiogroup" aria-label="模型模板">
        <button
          v-for="provider in providers"
          :key="provider.provider_id"
          type="button"
          class="account-provider-card"
          :class="{
            selected: selectedProviderId === provider.provider_id,
            active: provider.active,
          }"
          ref="providerButtons"
          :data-provider-id="provider.provider_id"
          role="radio"
          :aria-checked="selectedProviderId === provider.provider_id"
          :tabindex="selectedProviderId === provider.provider_id ? 0 : -1"
          @click="selectProvider(provider.provider_id)"
          @keydown="onProviderKeydown($event, provider.provider_id)"
        >
          <span class="account-provider-card__name">{{ provider.label }}</span>
          <span class="account-provider-card__model">{{ provider.model }}</span>
          <span class="account-provider-card__status">
            {{ provider.connected ? "已连接" : "未连接" }}
            <template v-if="provider.active"> · 当前使用</template>
          </span>
          <span
            v-if="provider.connected"
            class="account-provider-card__balance"
          >
            <template v-if="balanceFor(provider.provider_id)?.status === 'available'">
              余额 {{ balanceFor(provider.provider_id).amount }}
              {{ balanceFor(provider.provider_id).currency }}
            </template>
            <template v-else-if="balanceLoading">正在查询余额…</template>
            <template v-else>余额暂时无法获取</template>
            <small>余额可能有延迟</small>
          </span>
        </button>
      </div>

      <label class="form-group account-key-field">
        <span>API Key</span>
        <input
          id="account-llm-api-key"
          v-model="apiKey"
          class="form-input"
          type="password"
          autocomplete="new-password"
          :placeholder="selectedProvider?.connected ? '留空可直接切换到已验证连接' : '请先填写 Key'"
        />
      </label>
      <p class="settings-section-hint">
        Key 只在服务端加密保存。首次填写或更换 Key 时会做一次极小的真实生成验证，可能产生少量费用。
      </p>

      <div class="settings-actions">
        <button
          id="account-llm-save"
          class="btn btn-primary"
          :class="{
            'settings-btn-loading': connectionButton.saving.value,
            'settings-btn-error': connectionButton.error.value,
          }"
          :disabled="connectionButton.saving.value || !selectedProvider"
          :aria-busy="connectionButton.saving.value"
          @click="saveConnection"
        >{{ selectedProvider?.connected && !apiKey ? "切换并使用" : "验证、保存并使用" }}</button>
        <button
          v-if="selectedProvider?.connected"
          id="account-llm-clear"
          class="btn btn-link"
          :disabled="connectionButton.saving.value"
          @click="clearConnection"
        >清除这个 Key</button>
        <button
          id="account-balance-refresh"
          class="btn btn-link"
          :disabled="balanceLoading"
          :aria-busy="balanceLoading"
          @click="refreshBalances"
        >刷新余额</button>
      </div>
    </section>

    <section v-if="!returningToRp" class="settings-section" :aria-busy="authorButton.saving.value">
      <h3>作者偏好</h3>
      <AuthorPreferencesForm v-model="authorForm" />
      <div class="settings-actions">
        <button
          id="global-author-save"
          class="btn btn-primary"
          :class="{
            'settings-btn-loading': authorButton.saving.value,
            'settings-btn-error': authorButton.error.value,
          }"
          :disabled="authorButton.saving.value"
          :aria-busy="authorButton.saving.value"
          @click="saveAuthor"
        >保存作者偏好</button>
      </div>
    </section>
  </div>
</template>
