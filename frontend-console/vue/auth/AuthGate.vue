<template>
  <main class="auth-page">
    <section class="auth-card" aria-labelledby="auth-title" :aria-busy="busy">
      <div class="auth-brand">◆ NovelCraft</div>
      <template v-if="account?.status === 'pending_deletion'">
        <h1 id="auth-title">账号正在等待删除</h1>
        <p>项目仍会保留到 {{ purgeDate }}。撤销删除前，请先按原登录方式重新认证。</p>
        <template v-if="account.identity_type === 'email'">
          <label>登录邮箱<input v-model.trim="email" type="email" autocomplete="email"></label>
          <div class="code-row">
            <input v-model.trim="code" inputmode="numeric" maxlength="6" aria-label="重新认证验证码" autocomplete="one-time-code" placeholder="6 位验证码">
            <button type="button" class="secondary" :disabled="busy || !canResend" @click="requestCode('reauth')">{{ resendLabel }}</button>
          </div>
          <button type="button" :disabled="busy || !challengeId || code.length !== 6" @click="reauthAndRestore">验证并撤销删除</button>
        </template>
        <a v-else class="button-link" :href="api.auth.wechatStartUrl(config, 'reauth')">微信重新认证</a>
        <button v-if="reauthenticated" type="button" :disabled="busy" @click="restore">撤销删除</button>
        <button type="button" class="secondary" :disabled="busy" @click="$emit('logout')">退出登录</button>
        <p class="support">支持码：{{ account.support_code }}</p>
      </template>
      <template v-else>
        <h1 id="auth-title">登录或注册</h1>
        <p>使用邮箱验证码登录。首次验证会自动创建账号。</p>
        <label>邮箱<input v-model.trim="email" type="email" autocomplete="email" placeholder="name@example.com"></label>
        <div class="code-row">
          <input v-model.trim="code" inputmode="numeric" maxlength="6" aria-label="邮箱验证码" autocomplete="one-time-code" placeholder="6 位验证码">
          <button type="button" class="secondary" :disabled="busy || !email || !canResend" @click="requestCode('login')">{{ resendLabel }}</button>
        </div>
        <label class="consent"><input v-model="accepted" type="checkbox">我已阅读并同意
          <a :href="config.terms_url" target="_blank">用户协议</a>和
          <a :href="config.privacy_url" target="_blank">隐私政策</a>
        </label>
        <button type="button" :disabled="busy || !accepted || !challengeId || code.length !== 6" @click="verify">邮箱登录</button>
        <a v-if="config.wechat_enabled && accepted" class="button-link" :href="api.auth.wechatStartUrl(config)">微信扫码登录</a>
      </template>
      <p v-if="message" class="message" :class="{ error }" :role="error ? 'alert' : 'status'">{{ message }}</p>
    </section>
  </main>
</template>

<script setup>
import { computed, ref } from "vue"
import { getApi } from "../bridge/index.js"
import { useResendCountdown } from "../composables/useResendCountdown.js"

const props = defineProps({
  config: { type: Object, required: true },
  initialAccount: { type: Object, default: null },
})
const emit = defineEmits(["authenticated", "logout"])
const api = getApi()
const account = ref(props.initialAccount)
const email = ref("")
const code = ref("")
const accepted = ref(false)
const challengeId = ref("")
const busy = ref(false)
const message = ref("")
const error = ref(false)
const { canResend, resendLabel, start: startResendCountdown } = useResendCountdown()
const reauthenticated = computed(() => new URLSearchParams(location.search).get("auth") === "reauthenticated")
const purgeDate = computed(() => account.value?.purge_after
  ? new Date(account.value.purge_after).toLocaleDateString()
  : "30 天后")

function show(text, isError = false) {
  message.value = text
  error.value = isError
}
async function run(action) {
  busy.value = true
  show("")
  try { return await action() }
  catch (err) { show(err?.message || "操作失败", true); return null }
  finally { busy.value = false }
}
async function requestCode(purpose) {
  const result = await run(() => purpose === "reauth"
    ? api.auth.requestReauthEmailCode(email.value)
    : api.auth.requestEmailCode(email.value))
  if (!result) return
  challengeId.value = result.challenge_id
  startResendCountdown(result.resend_after)
  show("验证码已发送，5 分钟内有效")
}
async function verify() {
  const result = await run(() => api.auth.verifyEmail({
    email: email.value,
    code: code.value,
    challenge_id: challengeId.value,
    accept_terms: accepted.value,
    accept_privacy: accepted.value,
  }))
  if (result) emit("authenticated", result)
}
async function reauthAndRestore() {
  const verified = await run(() => api.auth.verifyReauthEmail({
    email: email.value,
    code: code.value,
    challenge_id: challengeId.value,
  }))
  if (verified) await restore()
}
async function restore() {
  const result = await run(() => api.auth.cancelDeletion())
  if (result) emit("authenticated", { ...account.value, status: "active" })
}
</script>

<style scoped>
.auth-page{min-height:100vh;display:grid;place-items:center;padding:24px;background:#f4f0e8;color:#292722}
.auth-card{width:min(100%,440px);display:grid;gap:18px;padding:36px;border:1px solid #d7d0c3;border-radius:18px;background:#fff;box-shadow:0 18px 50px #514a3b1a}
.auth-brand{font-weight:700;letter-spacing:.04em;color:#8c5a32}.auth-card h1{margin:0;font-size:28px}.auth-card p{margin:0;line-height:1.6}
.auth-card label{display:grid;gap:8px;font-size:14px}.auth-card input{min-width:0;padding:12px;border:1px solid #cfc7b9;border-radius:9px;font:inherit}
.code-row{display:grid;grid-template-columns:1fr auto;gap:10px}.auth-card button,.button-link{padding:12px 16px;border:0;border-radius:9px;background:#6f4628;color:#fff;font:inherit;text-align:center;text-decoration:none;cursor:pointer}
.auth-card button:disabled{opacity:.5;cursor:not-allowed}.auth-card .secondary{background:#e9dfd2;color:#4b3525}.consent{grid-template-columns:auto 1fr!important;align-items:start}.consent input{margin-top:3px}.message{color:#315c39}.message.error{color:#a23232}.support{font-size:13px;color:#6d675f}
/* 局部组件自适应断点保留（design-standard.md §6：全局仅 760/1100 两档，此处为组件级微调） */
@media(max-width:520px){.auth-card{padding:24px}.code-row{grid-template-columns:1fr}.auth-card .secondary{width:100%}}
</style>
