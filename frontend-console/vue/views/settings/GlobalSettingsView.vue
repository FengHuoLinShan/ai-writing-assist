<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import AuthorPreferencesForm from "./components/AuthorPreferencesForm.vue"
import { getApi, getConfirm, getRouter, getToast } from "../../bridge/index.js"
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
  connectionsLoadError: { type: String, default: null },
  authorPrefsLoadError: { type: String, default: null },
})

const connections = ref(props.llmConnections || {
  active_provider_id: "deepseek",
  providers: [],
})
const balances = ref(props.llmBalances?.items || [])
const selectedProviderId = ref(connections.value.active_provider_id || "deepseek")
const providerButtons = ref([])
const apiKey = ref("")
const imageApiKey = ref("")
const imageConnection = ref({ connected: false, model: "gpt-image-2" })
const connectionsLoadError = ref(props.connectionsLoadError)
const authorPrefsLoadError = ref(props.authorPrefsLoadError)
const imageLoadError = ref("")
const connectionsLoading = ref(false)
const authorPrefsLoading = ref(false)
const imageLoading = ref(false)
const imageSaving = ref(false)
const balanceLoading = ref(false)
const authorForm = ref(authorFormFromDefaults(props.authorPrefs))
const authorBaseline = ref(JSON.stringify(authorForm.value))
const connectionError = ref("")
const connectionFeedback = ref(null)
const imageError = ref("")
const imageFeedback = ref(null)
const authorError = ref("")
const authorFeedback = ref(null)
const connectionButton = useSaveButton()
const authorButton = useSaveButton()
let disposed = false
let connectionFormRevision = 0
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
const authorDirty = computed(() => JSON.stringify(authorForm.value) !== authorBaseline.value)
const connectionState = computed(() => {
  if (connectionFeedback.value) return connectionFeedback.value
  if (apiKey.value) return { kind: "pending", message: "新密钥尚未保存" }
  if (selectedProvider.value?.active) return { kind: "success", message: "当前正在使用这个服务" }
  if (selectedProvider.value?.connected) return { kind: "success", message: "连接已验证，可以切换使用" }
  return { kind: "muted", message: "尚未连接" }
})
const imageState = computed(() => {
  if (imageFeedback.value) return imageFeedback.value
  if (imageApiKey.value) return { kind: "pending", message: "新密钥尚未保存" }
  return imageConnection.value.connected
    ? { kind: "success", message: "已连接" }
    : { kind: "muted", message: "未连接" }
})
const authorState = computed(() => {
  if (authorFeedback.value) return authorFeedback.value
  return authorDirty.value
    ? { kind: "pending", message: "有未保存修改" }
    : { kind: "success", message: "已保存" }
})

function selectProvider(providerId) {
  if (providerId === selectedProviderId.value) return true
  if (apiKey.value && !getConfirm()("切换服务会清空尚未保存的密钥，继续吗？")) return false
  connectionFormRevision += 1
  selectedProviderId.value = providerId
  apiKey.value = ""
  connectionError.value = ""
  connectionFeedback.value = null
  return true
}

function onApiKeyInput() {
  connectionFormRevision += 1
  connectionError.value = ""
  connectionFeedback.value = null
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
  if (selectProvider(nextProviderId)) focusProvider(nextProviderId)
}

function balanceFor(providerId) {
  return balances.value.find((item) => item.provider_id === providerId) || null
}

async function returnAfterConnection() {
  if (disposed) return false
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

async function retryConnections() {
  connectionsLoading.value = true
  try {
    const response = await getApi().settings.listLLMConnections()
    if (disposed) return false
    if (!response?.providers?.length) throw new Error("没有可用的 AI 服务")
    connections.value = response
    selectedProviderId.value = response.active_provider_id || response.providers[0].provider_id
    connectionsLoadError.value = null
    connectionError.value = ""
    await refreshBalances()
  } catch {
    if (!disposed) connectionsLoadError.value = "模型连接暂时无法加载。"
  } finally {
    connectionsLoading.value = false
  }
}

async function retryAuthorPrefs() {
  authorPrefsLoading.value = true
  try {
    const prefs = await getApi().settings.listGlobalAuthorPrefs()
    if (disposed) return false
    authorForm.value = authorFormFromDefaults(prefs || {})
    authorBaseline.value = JSON.stringify(authorForm.value)
    authorPrefsLoadError.value = null
    authorError.value = ""
  } catch {
    if (!disposed) authorPrefsLoadError.value = "通用创作偏好暂时无法加载。"
  } finally {
    authorPrefsLoading.value = false
  }
}

async function loadImageConnection() {
  imageLoading.value = true
  try {
    const response = await getApi().settings.getImageConnection()
    if (disposed) return false
    imageConnection.value = response
    imageLoadError.value = ""
  } catch {
    if (!disposed) imageLoadError.value = "图片服务连接状态暂时无法加载。"
  } finally {
    imageLoading.value = false
  }
}

async function refreshBalances() {
  balanceLoading.value = true
  try {
    const response = await getApi().settings.listLLMBalances()
    if (disposed) return false
    balances.value = response?.items || []
  } catch {
    if (disposed) return false
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
    connectionError.value = "请填写服务密钥后再验证连接。"
    connectionFeedback.value = { kind: "error", message: "连接尚未保存" }
    getToast()("请先填写 API Key", "warning")
    void nextTick(() => document.getElementById("account-llm-api-key")?.focus())
    return
  }
  const providerId = provider.provider_id
  const revision = connectionFormRevision
  const ownsForm = () => (
    !disposed
    && selectedProviderId.value === providerId
    && connectionFormRevision === revision
  )

  connectionButton.saving.value = true
  connectionError.value = ""
  connectionFeedback.value = {
    kind: "pending",
    message: key ? "正在验证并保存连接…" : "正在切换当前服务…",
  }
  try {
    const response = key
      ? await getApi().settings.connectLLMProvider(providerId, key)
      : await getApi().settings.activateLLMProvider(providerId)
    if (!ownsForm()) return false
    if (response?.providers) connections.value = response
    apiKey.value = ""
    connectionFeedback.value = { kind: "success", message: "连接已验证并设为当前使用" }
    getToast()(`已启用 ${provider.label}，之后的新生成会使用此模型`, "success")
    await refreshBalances()
    if (!ownsForm()) return false
    await returnAfterConnection()
  } catch (err) {
    if (ownsForm()) {
      connectionError.value = err.message || "模型连接验证失败，请检查密钥后重试。"
      connectionFeedback.value = { kind: "error", message: "连接未保存，请检查后重试" }
      getToast()(connectionError.value, "error")
      connectionButton.flashError()
    }
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
  const providerId = provider.provider_id
  const revision = connectionFormRevision
  const ownsForm = () => (
    !disposed
    && selectedProviderId.value === providerId
    && connectionFormRevision === revision
  )
  try {
    const response = await getApi().settings.clearLLMProvider(providerId)
    if (!ownsForm()) return false
    if (response?.providers) connections.value = response
    apiKey.value = ""
    balances.value = balances.value.filter(
      (item) => item.provider_id !== providerId,
    )
    connectionFeedback.value = { kind: "success", message: "这个服务已断开" }
    getToast()(`${provider.label} 已断开`, "success")
  } catch (err) {
    if (ownsForm()) {
      connectionError.value = err.message || "断开失败，请稍后重试。"
      connectionFeedback.value = { kind: "error", message: "断开失败" }
      getToast()(connectionError.value, "error")
    }
  }
}

function onImageApiKeyInput() {
  imageError.value = ""
  imageFeedback.value = null
}

async function saveImageConnection() {
  const key = imageApiKey.value.trim()
  if (!key) {
    imageError.value = "请填写 OpenAI API Key 后再检查连接。"
    imageFeedback.value = { kind: "error", message: "图片服务尚未保存" }
    getToast()("请先填写 OpenAI API Key", "warning")
    void nextTick(() => document.getElementById("account-image-api-key")?.focus())
    return
  }
  imageSaving.value = true
  imageError.value = ""
  imageFeedback.value = { kind: "pending", message: "正在检查并保存连接…" }
  try {
    imageConnection.value = await getApi().settings.connectImageProvider(key)
    imageApiKey.value = ""
    imageFeedback.value = { kind: "success", message: "图片服务连接已保存" }
    getToast()("密钥连接成功", "success")
  } catch (err) {
    imageError.value = err.message || "图片服务连接失败，请检查密钥后重试。"
    imageFeedback.value = { kind: "error", message: "连接未保存，请检查后重试" }
    getToast()(imageError.value, "error")
  } finally { imageSaving.value = false }
}

async function clearImageConnection() {
  if (!getConfirm()("断开 OpenAI 图片服务？已生成的地图不受影响。")) return
  try {
    imageConnection.value = await getApi().settings.clearImageProvider()
    imageFeedback.value = { kind: "success", message: "图片服务已断开" }
    getToast()("图片服务已断开", "success")
  } catch (err) {
    imageError.value = err.message || "断开失败，请稍后重试。"
    imageFeedback.value = { kind: "error", message: "断开失败" }
    getToast()(imageError.value, "error")
  }
}

async function saveAuthor() {
  const toast = getToast()
  const submittedForm = JSON.stringify(authorForm.value)
  const prefs = buildAuthorPrefsPayload(authorForm.value)
  const validation = validateAuthorPreferences(prefs)
  if (!validation.ok) {
    authorError.value = validation.message
    authorFeedback.value = { kind: "error", message: "创作偏好尚未保存" }
    toast(validation.message, "warning")
    void nextTick(() => document.getElementById("author-daily-goal")?.focus())
    return
  }
  authorButton.saving.value = true
  authorError.value = ""
  authorFeedback.value = { kind: "pending", message: "正在保存…" }
  try {
    await getApi().settings.updateGlobalAuthorPrefs(prefs)
    if (disposed) return false
    if (JSON.stringify(authorForm.value) === submittedForm) {
      authorBaseline.value = submittedForm
    }
    authorFeedback.value = { kind: "success", message: "创作偏好已保存" }
    toast("作者偏好已保存", "success")
  } catch (err) {
    if (!disposed) {
      authorFeedback.value = { kind: "error", message: err.message || "保存失败，请稍后重试。" }
      toast(authorFeedback.value.message, "error")
      authorButton.flashError()
    }
  } finally {
    authorButton.saving.value = false
  }
}

function hasUnsavedChanges() {
  return Boolean(apiKey.value || imageApiKey.value)
    || JSON.stringify(authorForm.value) !== authorBaseline.value
}

watch(authorForm, () => {
  authorError.value = ""
  authorFeedback.value = null
}, { deep: true })

useLeaveGuard(() => (
  !hasUnsavedChanges()
  || getConfirm()("账户设置有未保存修改，确定放弃并离开吗？")
))

function beforeUnload(event) {
  if (!hasUnsavedChanges()) return
  event.preventDefault()
  event.returnValue = ""
}

onMounted(async () => {
  window.addEventListener("beforeunload", beforeUnload)
  await loadImageConnection()
})
onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener("beforeunload", beforeUnload)
})
</script>

<template>
  <div class="global-settings-view account-settings-view">
    <button
      v-if="returningToRp"
      class="btn btn-sm btn-link settings-return-link"
      type="button"
      @click="returnAfterConnection"
    >‹ 返回旅程</button>

    <section class="settings-section account-connection-section" :aria-busy="connectionsLoading || connectionButton.saving.value || balanceLoading">
      <h2>AI 文本服务</h2>
      <p class="settings-section-hint">
        选择服务并验证密钥。未连接时仍可正常手写，只有 AI 功能会暂停。
        <template v-if="returnTarget">连接成功后会回到刚才的旅程位置。</template>
      </p>

      <div v-if="connectionsLoadError" class="error-card settings-load-error" role="alert">
        <div>
          <strong>模型连接暂时无法加载</strong>
          <p>密钥和已有连接没有改变，可以重新加载。</p>
        </div>
        <button class="btn btn-primary" type="button" :disabled="connectionsLoading" @click="retryConnections">
          {{ connectionsLoading ? "正在加载…" : "重新加载" }}
        </button>
      </div>
      <template v-else>
        <div class="account-provider-options" role="radiogroup" aria-label="AI 文本服务">
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
            <span v-if="provider.connected" class="account-provider-card__balance">
              <template v-if="balanceFor(provider.provider_id)?.status === 'available'">
                余额 {{ balanceFor(provider.provider_id).amount }} {{ balanceFor(provider.provider_id).currency }}
              </template>
              <template v-else-if="balanceLoading">正在查询余额…</template>
              <template v-else>余额暂时无法获取</template>
              <small>余额可能有延迟</small>
            </span>
          </button>
        </div>

        <div class="form-group account-key-field">
          <label for="account-llm-api-key">服务密钥（API Key）</label>
          <input
            id="account-llm-api-key"
            v-model="apiKey"
            class="form-input"
            type="password"
            autocomplete="new-password"
            :placeholder="selectedProvider?.connected ? '留空可直接切换到已验证连接' : '请先填写 Key'"
            :aria-invalid="Boolean(connectionError)"
            :aria-describedby="connectionError ? 'account-key-help account-key-error' : 'account-key-help'"
            @input="onApiKeyInput"
          />
          <p id="account-key-help" class="settings-field-help settings-cost-warning">
            Key 只在服务端加密保存。首次填写或更换时会做一次极小的真实生成验证，可能产生少量费用。
          </p>
          <p v-if="connectionError" id="account-key-error" class="form-error" role="alert">{{ connectionError }}</p>
        </div>

        <div class="settings-actions">
          <button
            id="account-llm-save"
            class="btn btn-primary"
            :class="{
              'settings-btn-loading': connectionButton.saving.value,
              'settings-btn-error': connectionButton.error.value,
            }"
            :disabled="connectionButton.saving.value || !selectedProvider || (selectedProvider.active && !apiKey)"
            :aria-busy="connectionButton.saving.value"
            @click="saveConnection"
          >{{ selectedProvider?.active && !apiKey ? "当前正在使用" : selectedProvider?.connected && !apiKey ? "切换并使用" : "验证、保存并使用" }}</button>
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
          <p class="settings-save-state" :class="`is-${connectionState.kind}`" role="status">{{ connectionState.message }}</p>
        </div>
      </template>
    </section>

    <details v-if="!returningToRp" class="settings-advanced-section" :aria-busy="imageLoading || imageSaving">
      <summary>
        <span><strong>图片生成连接</strong><small>地图册使用，按需设置</small></span>
        <span class="settings-summary-state" :class="`is-${imageState.kind}`">{{ imageState.message }}</span>
      </summary>
      <div class="settings-advanced-section__body">
        <div v-if="imageLoadError" class="error-card settings-load-error" role="alert">
          <div><strong>图片服务状态暂时无法加载</strong><p>已有密钥没有改变。</p></div>
          <button class="btn btn-primary" type="button" :disabled="imageLoading" @click="loadImageConnection">{{ imageLoading ? "正在加载…" : "重新加载" }}</button>
        </div>
        <template v-else>
          <p class="settings-section-hint">地图册固定使用 <strong>gpt-image-2</strong>，不会改变文本模型。</p>
          <div class="form-group account-key-field">
            <label for="account-image-api-key">OpenAI API Key</label>
            <input
              id="account-image-api-key"
              v-model="imageApiKey"
              class="form-input"
              type="password"
              autocomplete="new-password"
              :placeholder="imageConnection.connected ? '填写新 Key 可替换' : '请填写 Key'"
              :aria-invalid="Boolean(imageError)"
              :aria-describedby="imageError ? 'account-image-help account-image-error' : 'account-image-help'"
              @input="onImageApiKeyInput"
            />
            <p id="account-image-help" class="settings-field-help">这里只检查连接；图片权限和额度会在首次真实生成时确认。</p>
            <p v-if="imageError" id="account-image-error" class="form-error" role="alert">{{ imageError }}</p>
          </div>
          <div class="settings-actions">
            <button class="btn btn-primary" :disabled="imageSaving || !imageApiKey.trim()" @click="saveImageConnection">{{ imageSaving ? '连接中…' : '检查连接并保存' }}</button>
            <button v-if="imageConnection.connected" class="btn btn-link" :disabled="imageSaving" @click="clearImageConnection">断开图片服务</button>
            <p class="settings-save-state" :class="`is-${imageState.kind}`" role="status">{{ imageState.message }}</p>
          </div>
        </template>
      </div>
    </details>

    <section v-if="!returningToRp" class="settings-section" :aria-busy="authorPrefsLoading || authorButton.saving.value">
      <h2>通用创作偏好</h2>
      <p class="settings-section-hint">作为所有作品的默认值；当前作品仍可单独覆盖。</p>
      <div v-if="authorPrefsLoadError" class="error-card settings-load-error" role="alert">
        <div><strong>通用创作偏好暂时无法加载</strong><p>为避免覆盖原值，加载成功前不会显示表单。</p></div>
        <button class="btn btn-primary" type="button" :disabled="authorPrefsLoading" @click="retryAuthorPrefs">{{ authorPrefsLoading ? "正在加载…" : "重新加载" }}</button>
      </div>
      <template v-else>
        <AuthorPreferencesForm v-model="authorForm" :errors="{ daily_goal: authorError }" />
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
          >保存创作偏好</button>
          <p class="settings-save-state" :class="`is-${authorState.kind}`" role="status">{{ authorState.message }}</p>
        </div>
      </template>
    </section>
  </div>
</template>
