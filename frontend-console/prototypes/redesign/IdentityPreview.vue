<script setup>
import { ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
const props = defineProps({ state: { type: String, default: 'normal' } })
const emit = defineEmits(['navigate'])
const intent = ref('')
const email = ref('writer@example.test')
const code = ref('')
const authStage = ref('填写邮箱')
function enter(value) { intent.value = value; authStage.value = props.state === 'error' ? '发送失败' : '填写邮箱' }
</script>
<template><div class="rd-page-scroll"><div class="rd-page-inner rd-identity-preview">
<section v-if="!intent" class="rd-welcome"><span class="rd-brand-mark">N</span><span class="rd-eyebrow">WELCOME TO NOVELCRAFT</span><h1>故事，因你而发生。</h1><p>构建一个世界，或走进一个世界。</p><div class="rd-identity-grid"><button @click="enter('today')"><span class="rd-color-icon tone-blue"><PreviewIcon name="writing"/></span><h2>我是创作者</h2><p>把脑海里的世界<br>变成有人想读的故事。</p><strong>进入创作空间 →</strong></button><button @click="enter('journeys')"><span class="rd-color-icon tone-purple">✦</span><h2>我是探索者</h2><p>带着自己的选择<br>走进一段未知的旅程。</p><strong>发现互动故事 →</strong></button></div><small>设计预览 · 两种体验均使用虚构内容</small></section>
<section v-else class="rd-auth-surface"><button class="rd-text-button" @click="intent = ''">← 返回身份选择</button><span class="rd-brand-mark">N</span><h1>欢迎回到故事里。</h1><p>用邮箱验证码继续。{{ intent === 'today' ? '你的创作空间' : '你的私人旅程' }}就在这里。</p><form @submit.prevent="authStage = authStage === '验证码已发送' ? '验证失败' : '验证码已发送'"><label class="rd-field">示例登录邮箱<input v-model="email" type="email" required autocomplete="off"/></label><label v-if="authStage === '验证码已发送' || authStage === '验证失败'" class="rd-field">示例验证码<input v-model="code" inputmode="numeric" maxlength="6" placeholder="6位验证码示例" autocomplete="off"/></label><button class="rd-button primary">{{ authStage === '验证码已发送' ? '演示校验验证码' : authStage === '发送失败' ? '重试发送示例' : '演示发送验证码' }}</button></form><div v-if="authStage === '验证码已发送'" class="rd-inline-notice tone-blue"><strong>验证码已发送 · 演示</strong><p>可在稍后重新发送。当前没有发送邮件。</p><button class="rd-button" disabled>等待后重新发送 · 示例</button></div><div v-if="['验证失败','发送失败'].includes(authStage)" class="rd-inline-notice tone-orange"><strong>! {{ authStage === '验证失败' ? '验证码暂时无法确认' : '邮件发送暂时失败' }}</strong><p>邮箱与当前意图保留。检查后可以重试。</p><button class="rd-text-button" @click="authStage = '验证码已发送'">重新尝试示例 →</button></div><div v-if="state === 'conflict'" class="rd-inline-notice tone-orange"><strong>这份作品暂时无法访问</strong><p>正式产品会核对当前身份与作品权限。可以切换身份，或回自己的作品。</p></div><div class="rd-local-toolbar"><button class="rd-button" @click="emit('navigate', intent)">以演示身份继续</button><button class="rd-text-button" @click="authStage = '发送失败'">查看发送失败</button></div><p class="rd-demonstration">仅演示已有邮箱验证码方式。不发送邮件、不验证真实身份、不创建账户。</p></section>
</div></div></template>
<style>
#redesign-root .rd-identity-preview .rd-auth-surface{max-width:440px;margin:55px auto;background:var(--surface);padding:34px;border:1px solid var(--line);border-radius:20px}#redesign-root .rd-identity-preview .rd-auth-surface>.rd-brand-mark{display:flex;margin:28px 0}#redesign-root .rd-identity-preview .rd-auth-surface h1{font-size:28px}#redesign-root .rd-identity-preview .rd-auth-surface p{line-height:1.9;color:var(--muted);margin:16px 0}#redesign-root .rd-identity-preview .rd-auth-surface .rd-field{margin-top:20px}@media(max-width:600px){#redesign-root .rd-identity-preview .rd-auth-surface{margin:20px auto;padding:24px}}
</style>
