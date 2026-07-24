<template>
  <div v-if="open" class="account-overlay" role="presentation" @click.self="$emit('close')">
    <section class="account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-title">
      <button class="account-close" type="button" aria-label="关闭" @click="$emit('close')">×</button>
      <h2 id="account-title">账号</h2>
      <p>支持码：{{ account?.support_code || "—" }}</p>
      <button type="button" class="secondary" @click="$emit('logout')">退出登录</button>
      <details>
        <summary>删除账号</summary>
        <p>申请后有 30 天恢复期，期间项目不会被删除，但未完成任务会立即取消。</p>
        <template v-if="account?.identity_type === 'email'">
          <label>登录邮箱<input v-model.trim="email" type="email" autocomplete="email"></label>
          <div class="account-code-row">
            <input v-model.trim="code" inputmode="numeric" maxlength="6" placeholder="6 位验证码">
            <button type="button" class="secondary" :disabled="busy || !canResend" @click="requestCode">{{ resendLabel }}</button>
          </div>
          <button type="button" class="danger" :disabled="busy || !challengeId || code.length !== 6" @click="verifyAndDelete">验证并申请删除</button>
        </template>
        <template v-else>
          <a class="button-link" :href="api.auth.wechatStartUrl(config, 'reauth')">微信重新认证</a>
          <button v-if="reauthenticated" type="button" class="danger" :disabled="busy" @click="requestDeletion">申请删除账号</button>
        </template>
        <p v-if="message" class="account-message" :class="{ error }">{{ message }}</p>
      </details>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"
import { getApi } from "../../bridge/index.js"
import { useResendCountdown } from "../../composables/useResendCountdown.js"

const props = defineProps({
  open: Boolean,
  account: { type: Object, default: null },
  config: { type: Object, required: true },
})
const emit = defineEmits(["close", "logout", "account-invalidated"])
const api = getApi()
const account = props.account
const config = props.config
const email = ref("")
const code = ref("")
const challengeId = ref("")
const busy = ref(false)
const message = ref("")
const error = ref(false)
const { canResend, resendLabel, start: startResendCountdown } = useResendCountdown()
const reauthenticated = computed(() => new URLSearchParams(location.search).get("auth") === "reauthenticated")

async function run(action) {
  busy.value = true
  message.value = ""
  error.value = false
  try { return await action() }
  catch (err) { message.value = err?.message || "操作失败"; error.value = true; return null }
  finally { busy.value = false }
}
async function requestCode() {
  const result = await run(() => api.auth.requestReauthEmailCode(email.value))
  if (result) {
    challengeId.value = result.challenge_id
    startResendCountdown(result.resend_after)
    message.value = "验证码已发送"
  }
}
async function verifyAndDelete() {
  const result = await run(() => api.auth.verifyReauthEmail({
    email: email.value,
    code: code.value,
    challenge_id: challengeId.value,
  }))
  if (result) await requestDeletion()
}
async function requestDeletion() {
  const result = await run(() => api.auth.requestDeletion())
  if (result) emit("account-invalidated")
}
</script>

<style scoped>
.account-overlay{position:fixed;inset:0;z-index:1200;display:grid;place-items:center;padding:20px;background:#1d1a1699}
.account-dialog{position:relative;width:min(100%,440px);display:grid;gap:16px;padding:28px;border-radius:14px;background:#fff;color:#292722}
.account-dialog h2,.account-dialog p{margin:0}.account-close{position:absolute;right:12px;top:10px;border:0;background:transparent;font-size:25px}
.account-dialog details{display:grid;gap:12px;border-top:1px solid #ddd;padding-top:14px}.account-dialog details[open]{display:grid}
.account-dialog label{display:grid;gap:6px}.account-dialog input{padding:10px;border:1px solid #bbb;border-radius:8px}
.account-dialog button,.button-link{padding:10px 14px;border:0;border-radius:8px;text-align:center;text-decoration:none}.secondary{background:#ece7df;color:#332b24}.danger{background:#9b3434;color:#fff}.button-link{background:#6f4628;color:#fff}
.account-code-row{display:grid;grid-template-columns:1fr auto;gap:8px}.account-message{color:#315c39}.account-message.error{color:#9b3434}
</style>
