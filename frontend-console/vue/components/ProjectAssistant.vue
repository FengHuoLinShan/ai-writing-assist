<template>
  <div v-if="state.enabled" v-show="open" ref="overlayRef" class="project-assistant" :class="{ 'project-assistant--mobile': narrow }">
    <button v-if="narrow" type="button" class="project-assistant-backdrop" aria-label="关闭项目助手" @click="$emit('close')"></button>
    <aside id="project-assistant-panel" ref="dialogRef" class="project-assistant-panel" :role="narrow ? 'dialog' : 'complementary'" :aria-modal="narrow || undefined" aria-label="项目助手" tabindex="-1" @keydown="handleKeydown" @focusin="onFocusin">
      <header class="project-assistant-header"><div><strong>项目助手</strong><p>查资料、理思路，准备可审阅的修改。</p></div><button class="btn btn-sm" type="button" aria-label="关闭项目助手" @click="$emit('close')">关闭</button></header>
      <div class="project-assistant-tabs" role="group" aria-label="助手页面">
        <button type="button" :aria-pressed="activeTab === 'chat'" @click="activeTab = 'chat'">讨论</button>
        <button type="button" :aria-pressed="activeTab === 'care'" @click="activeTab = 'care'">提醒</button>
      </div>
      <ProactiveCare v-show="activeTab === 'care'" :target-id="projectId" standalone @locate="locateAssistantSource" />
      <div v-show="activeTab === 'chat'" class="project-assistant-chat">
      <div class="project-assistant-sessions"><label for="assistant-session">讨论</label><select id="assistant-session" :value="state.sessionId || ''" :disabled="state.busy || state.loading" @change="assistant.selectSession($event.target.value)"><option v-if="!state.sessionId" value="">新的讨论</option><option v-for="session in state.sessions" :key="session.id" :value="session.id">{{ session.title }}</option></select><button type="button" class="btn btn-sm" :disabled="state.busy" @click="assistant.newSession">新讨论</button></div>
      <div v-if="state.error" class="project-assistant-error" role="alert">{{ state.error }}</div>
      <button v-if="state.pendingSubmission && state.error" class="btn" type="button" :disabled="state.busy" @click="assistant.recoverSubmission">恢复上次提交</button>
      <button v-if="state.sessions.length < state.total" class="btn btn-sm" type="button" :disabled="state.loading" @click="assistant.moreSessions">更多讨论</button>
      <p v-if="state.backupError" class="project-assistant-error" role="alert">本地备份暂不可用。未提交的输入仍保留在此页，请勿刷新。</p>
      <div class="project-assistant-history" aria-label="讨论记录">
        <button v-if="state.messages.length < state.messageTotal" class="btn btn-sm" type="button" :disabled="state.loading" @click="assistant.moreMessages">查看更早的讨论</button>
        <p v-if="state.loading" role="status">正在读取讨论…</p>
        <div v-if="!state.messages.length && !state.loading" class="project-assistant-empty"><p>可以直接说你想完成的事。</p><button v-for="hint in hints" :key="hint" class="btn" type="button" @click="assistant.setInput(hint)">{{ hint }}</button></div>
        <article v-for="message in state.messages" :key="message.id" class="project-assistant-message" :class="{ 'is-author': message.role === 'author' }"><strong>{{ message.role === 'author' ? '你' : '助手' }}</strong><p>{{ message.content }}</p><button v-if="receiptMessageIds.has(message.id)" class="btn btn-sm" type="button" :disabled="state.busy || state.loading || running" @click="assistant.openRun(message.assistant_run_id)">查看本轮方案与结果</button><button v-if="message.outcome_suggestion_id" class="btn btn-sm" type="button" @click="locateAssistantSource({ type: message.outcome_kind === 'checkpoint' ? 'world_checkpoint' : 'world_suggestion', id: message.outcome_suggestion_id })">查看这次讨论的成果</button></article>
        <section v-if="state.run" class="project-assistant-result" aria-label="本次处理结果">
          <p role="status">{{ statusLabel }}</p>
          <div v-if="state.run.result?.next_steps?.length" class="project-assistant-actions"><button v-for="destination in state.run.result.next_steps" :key="destination" type="button" class="btn btn-sm" @click="openAssistantDestination(destination, state.context || {})">{{ state.destinations?.find(item => item.id === destination)?.label || '打开相关工作区' }}</button></div><p v-if="state.run.error" class="project-assistant-error">{{ state.run.error }}</p>
          <button v-if="running" class="btn btn-sm" type="button" :disabled="state.busy" @click="assistant.stop">停止本次处理</button>
          <div v-if="['failed', 'budget_exceeded', 'cancelled'].includes(state.run.status)" class="project-assistant-actions"><button v-if="state.run.can_resume" class="btn btn-sm" type="button" :disabled="state.busy" @click="assistant.resume(false)">恢复本次查证</button><button class="btn btn-sm" type="button" :disabled="state.busy" @click="assistant.resume(true)">开始新一轮查证</button></div>
          <details v-if="state.run.result?.sources?.length"><summary>查看依据（{{ state.run.result.sources.length }}）</summary><article v-for="source in state.run.result.sources" :key="source.evidence_id" class="project-assistant-source"><strong>{{ source.title || '参考资料' }}</strong><p>{{ source.snippet || source.text || source.answer || '' }}</p><p v-if="source.excerpted">以上为摘录，可打开来源查看全文。</p><button v-if="source.source_ref || source.target_ref" type="button" class="btn btn-sm" @click="locateAssistantSource(source)">打开来源</button><button v-if="source.domain_reference?.type === 'world_validation'" type="button" class="btn btn-sm" @click="locateAssistantSource(source.domain_reference)">打开世界复核回执</button><div v-if="source.domain_reference?.type === 'smart_dedup_scan'"><p>{{ source.domain_result?.summary || source.domain_result?.authority }}</p><button type="button" class="btn btn-sm" @click="locateAssistantSource(source.domain_reference)">打开相似资料比较</button></div><details v-if="source.related_results?.length"><summary>该地图的图片与历史</summary><button v-for="item in source.related_results" :key="item.id" class="btn btn-sm" @click="locateAssistantSource(item)">{{ item.title || '查看图片成果' }}</button></details><AssistantReviewResult v-if="source.review_result" :result="source.review_result" /><div v-if="source.domain_result?.candidate"><p>{{ source.domain_result.authority }}</p><button type="button" class="btn btn-sm" @click="locateAssistantSource(source.domain_result.candidate)">查看正文候选</button></div><details v-if="source.domain_result?.draft_structure"><summary>查看结构提案</summary><button v-if="source.domain_reference" type="button" class="btn btn-sm" @click="locateAssistantSource(source.domain_reference)">打开结构审阅页</button><p>{{ source.domain_result.authority }}</p><AssistantValue :value="source.domain_result.draft_structure" /></details><a v-for="link in (source.sources || []).filter(item => safeUrl(item.url))" :key="link.url" :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.title || '查看外部来源' }}</a></article></details>
          <ul v-if="state.run.result?.omissions?.length" class="project-assistant-omissions"><li v-for="item in state.run.result.omissions" :key="item">{{ item }}</li></ul>
          <section v-if="batch" aria-label="修改方案" class="project-assistant-batch"><h3>修改方案</h3><p>核对具体内容后，可选择部分或全部确认。</p>
            <article v-for="action in state.run.result.actions" :key="action.key" class="project-assistant-proposal"><label><input v-if="batch.status === 'pending'" v-model="state.selected" type="checkbox" :value="action.key" :disabled="state.busy" /> <strong>{{ action.title }}</strong></label><p>{{ action.reason }}</p><p class="project-assistant-effect">{{ action.preview?.effect }}</p><details><summary>查看具体修改</summary><p v-if="action.preview?.before !== undefined"><strong>原内容</strong></p><AssistantValue v-if="action.preview?.before !== undefined" :value="action.preview.before" /><p><strong>拟修改为</strong></p><AssistantValue :value="action.preview?.after || action.preview?.title" /></details><p v-if="action.depends_on.length">需要同时选择：{{ dependencyTitles(action) }}</p></article>
            <div v-if="batch.status === 'pending'" class="project-assistant-actions"><button class="btn btn-primary" type="button" :disabled="state.busy || !state.selected.length" @click="assistant.decide()">{{ state.busy ? '正在确认…' : '确认所选修改' }}</button><button class="btn" type="button" :disabled="state.busy" @click="assistant.decide([])">暂不采用</button></div>
            <p v-else role="status">{{ batch.status === 'completed' ? '所选操作已执行。' : batch.status === 'declined' ? '本次方案未采用。' : '部分操作未完成，请查看结果。' }}</p>
            <button v-if="batch.status === 'partial'" type="button" class="btn" :disabled="state.busy" @click="assistant.decide(state.selected, true)">重试未完成的操作</button><button v-if="batch.status === 'partial'" type="button" class="btn" :disabled="state.busy" @click="assistant.recheckBatch">重新查证剩余方案</button>
            <ul v-if="batch.results?.length"><li v-for="item in batch.results" :key="item.key">{{ item.result?.label || item.message || '操作已处理' }}<button v-if="item.result" class="btn btn-sm" type="button" @click="locateAssistantSource(item.result)">查看成果</button></li></ul>
          </section>
          <details v-if="state.run.usage?.requests" class="project-assistant-usage"><summary>查看本次用量</summary><p>模型请求 {{ state.run.usage.requests }} 次，联网请求 {{ state.run.usage.web_requests || 0 }} 次。</p><p>已知输入 {{ state.run.usage.prompt_tokens || 0 }}，已知输出 {{ state.run.usage.completion_tokens || 0 }}。费用未知{{ state.run.usage.usage_complete === false ? '，部分用量未返回' : '' }}。</p></details>
        </section>
      </div>
      <form class="project-assistant-composer" @submit.prevent="send"><div class="project-assistant-context"><span>本次参考：{{ contextLabel }}</span><button class="btn btn-sm" type="button" :disabled="state.busy" @click="useCurrent">使用当前页面</button></div><label class="project-assistant-scope">参考范围 <select :value="state.context?.scope || 'current'" :disabled="state.busy || Boolean(state.context?.context_confirmation_id)" @change="setScope($event.target.value)"><option value="current">当前位置优先</option><option value="project">整个作品</option></select></label><p v-if="state.context?.context_confirmation_id" class="project-assistant-selection">沿用已确认资料；“使用当前页面”会替换这份范围。</p><p v-if="state.context?.excluded_targets?.length" class="project-assistant-selection">沿用 {{ state.context.excluded_targets.length }} 项排除选择。<button class="btn btn-sm" type="button" :disabled="state.busy" @click="state.context = { ...state.context, excluded_targets: [] }; assistant.setInput(state.input)">清除排除项</button></p><p v-if="state.context?.selection" class="project-assistant-selection">选区：{{ state.context.selection.slice(0, 140) }}<button class="btn btn-sm" type="button" @click="clearSelection">移除选区</button></p><label class="sr-only" for="assistant-input">告诉助手你想完成什么</label><textarea id="assistant-input" :value="state.input" rows="3" maxlength="20000" placeholder="例如：核对这章的人物行为，给我具体修改建议" :disabled="state.busy" @input="assistant.setInput($event.target.value)"></textarea><div class="project-assistant-actions"><label><input :checked="state.allowWeb && !state.webUnavailableReason" type="checkbox" :disabled="state.busy || Boolean(state.webUnavailableReason)" @change="assistant.setAllowWeb($event.target.checked)" /> 允许通过本站搜索服务查证现实资料</label><small>仅发送通用事实问题至搜索网站并读取公开网页，不发送作品原文。</small><p v-if="state.modelUnavailableReason" role="status">{{ state.modelUnavailableReason }} <button type="button" class="btn btn-sm" @click="openAssistantDestination('model_settings')">连接模型</button></p><p v-if="state.webUnavailableReason" role="status">{{ state.webUnavailableReason }}</p><button class="btn btn-primary" type="submit" :disabled="!state.input.trim() || state.busy || running || Boolean(state.modelUnavailableReason)">{{ state.busy ? '提交中…' : '发送' }}</button></div></form>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getAssistantWorkContext } from "../bridge/index.js"
import { createProjectAssistant } from "../composables/useProjectAssistant.js"
import { registerProjectAssistantOpener } from "../bridge/index.js"
import { useModalDialog } from "../composables/useModalDialog.js"
import AssistantValue from "./AssistantValue.vue"
import AssistantReviewResult from "./AssistantReviewResult.vue"
import ProactiveCare from "./ProactiveCare.vue"
import { locateAssistantSource, openAssistantDestination } from "../shared/assistantNavigation.js"

const props = defineProps({ projectId: { type: String, default: null }, page: { type: String, default: "today" }, open: Boolean, initialContext: { type: Object, default: null } })
const emit = defineEmits(["open", "close", "availability"])
const assistant = createProjectAssistant()
const state = assistant.state
const receiptMessageIds = computed(() => new Set(new Map(state.messages.filter(message => message.assistant_run_id).map(message => [message.assistant_run_id, message.id])).values()))
const narrow = ref(false)
const activeTab = ref("chat")
let media
const close = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open && state.enabled && narrow.value, requestClose: close })
const hints = ["检查当前章节的前后设定", "帮我整理已有正文", "把接下来要处理的事项理清楚"]
const running = computed(() => ["pending", "running"].includes(state.run?.status))
const batch = computed(() => state.run?.result?.batch)
const statusLabel = computed(() => ({ pending: "已提交，等待处理。", running: "正在分析和查证，可离开后继续查看。", completed: "本次处理已完成。", waiting_approval: "修改方案已准备好，等待你确认。", failed: "本次处理未完成。", cancelled: "本次处理已停止。", budget_exceeded: "本次查证已达到预算。" })[state.run?.status] || "")
const contextLabel = computed(() => state.context?.chapter_index ? `第 ${state.context.chapter_index} 章` : ({ world: "人物与世界", writing: "写作页面", outline: "故事结构", scene: "当前场景", map: "地图", rag: "查找结果" })[state.context?.page || props.page] || "当前作品")
function capture() { return props.initialContext?.projectId === props.projectId ? props.initialContext.context : getAssistantWorkContext(props.projectId, props.page) }
function handleKeydown(event) { if (!narrow.value && event.key === "Escape") { event.stopPropagation(); close() } else onKeydown(event) }
function useCurrent() { try { state.context = { ...getAssistantWorkContext(props.projectId, props.page), excluded_targets: state.context?.excluded_targets || [] }; assistant.setInput(state.input) } catch (error) { state.error = error.message } }
function setScope(value) { try { state.context = { ...(state.context || capture()), scope: value }; assistant.setInput(state.input) } catch (error) { state.error = error.message } }
function clearSelection() { state.context = { ...(state.context || {}), selection: "" }; assistant.setInput(state.input) }
async function send() { try { await assistant.send(state.context || capture()) } catch (error) { state.error = error.message || "暂时无法提交。" } }
function dependencyTitles(action) { return action.depends_on.map(key => state.run.result.actions.find(item => item.key === key)?.title || "前置修改").join("、") }
function safeUrl(value) { try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password } catch { return false } }
function syncMedia() { narrow.value = media?.matches || false }
let loadPromise = Promise.resolve()
let disposed = false
const removeOpener = registerProjectAssistantOpener(async request => {
  await loadPromise
  if (disposed || request.projectId !== props.projectId || !state.enabled) throw new Error("该作品的项目助手尚未启用。")
  if (state.busy || state.loading) throw new Error("项目助手正在保存或读取讨论，请稍后打开；本页内容仍保留。")
  if (request.sessionId) await assistant.selectSession(request.sessionId)
  if (disposed || request.projectId !== props.projectId || state.error) throw new Error(state.error || "作品已切换。")
  if (request.context && !state.context && !state.input) state.context = request.context
  if (request.message) {
    if (state.input && state.input !== request.message) throw new Error("项目助手中还有未发送的输入，请先处理；这次内容仍保留在共创页。")
    assistant.setInput(request.message)
  }
  activeTab.value = "chat"
  emit("open")
})
watch(() => props.projectId, value => { activeTab.value = "chat"; loadPromise = assistant.load(value) }, { immediate: true })
watch(() => state.enabled, value => emit("availability", value))
watch(() => props.open, async value => { if (value && !state.input && !state.context) { try { state.context = capture() } catch (error) { state.error = error.message } } if (value) await nextTick() })
onMounted(() => { media = globalThis.matchMedia?.("(max-width: 1100px)"); syncMedia(); media?.addEventListener?.("change", syncMedia) })
onBeforeUnmount(() => { disposed = true; removeOpener(); assistant.dispose(); media?.removeEventListener?.("change", syncMedia) })
</script>

<style>
.project-assistant-scope{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;margin-top:8px}.project-assistant-scope select{min-height:40px;padding:6px;background:var(--bg-muted);color:inherit;border:1px solid var(--border);border-radius:6px}
.project-assistant{flex:0 0 min(25rem,36vw);min-width:0;border-left:1px solid var(--border-color,var(--border));background:var(--bg-primary,var(--bg-base));color:var(--text-primary);height:100%;overflow:hidden}
.project-assistant-chat{display:flex;flex-direction:column;flex:1;min-height:0}.project-assistant-tabs{display:flex;padding:6px 16px;gap:8px;border-bottom:1px solid var(--border-color,var(--border))}.project-assistant-tabs button{border:0;background:transparent;color:var(--text-secondary);padding:8px 16px;min-height:40px;cursor:pointer}.project-assistant-tabs button[aria-pressed=true]{color:var(--text-primary);background:var(--bg-muted);border-radius:6px;font-weight:600}.project-assistant-panel{height:100%;display:flex;flex-direction:column;min-width:0;outline:none}
.project-assistant-header,.project-assistant-sessions,.project-assistant-composer{padding:14px 16px;border-bottom:1px solid var(--border-color,var(--border))}
.project-assistant-header,.project-assistant-sessions,.project-assistant-actions,.project-assistant-context{display:flex;align-items:center;justify-content:space-between;gap:8px}
.project-assistant-header p,.project-assistant-context{font-size:12px;color:var(--text-secondary);margin:4px 0}
.project-assistant-sessions select{min-width:0;flex:1;padding:8px;background:var(--bg-muted);color:inherit;border:1px solid var(--border-color,var(--border));border-radius:6px}
.project-assistant-history{flex:1;overflow-y:auto;padding:16px;min-height:0;overscroll-behavior:contain}
.project-assistant-message{padding:12px 0;border-bottom:1px solid var(--border-color,var(--border))}
.project-assistant-message p,.assistant-value-text,.project-assistant-source p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;margin:8px 0}
.project-assistant-message strong{font-size:12px;color:var(--text-secondary)}
.project-assistant-message.is-author{padding:12px;background:var(--bg-muted);border-radius:8px;margin-bottom:12px}
.project-assistant-empty{display:grid;gap:10px;color:var(--text-secondary);padding:20px 0}
.project-assistant-empty .btn{text-align:left;white-space:normal;min-height:44px}
.project-assistant-error{color:var(--danger);padding:8px 16px;line-height:1.6;overflow-wrap:anywhere}
.project-assistant-result{padding-top:12px}.project-assistant-result details{margin:12px 0}.project-assistant-result summary{cursor:pointer;min-height:32px;line-height:32px}
.project-assistant-proposal{border:1px solid var(--border-color,var(--border));border-radius:8px;padding:12px;margin:12px 0}.project-assistant-effect{color:var(--text-secondary);font-size:13px;line-height:1.6}
.project-assistant-actions{flex-wrap:wrap}.project-assistant-actions label{font-size:12px}.project-assistant-usage{color:var(--text-secondary);font-size:12px}
.project-assistant-composer{border-top:1px solid var(--border-color,var(--border));border-bottom:none;flex-shrink:0}
.project-assistant-composer textarea{box-sizing:border-box;width:100%;min-height:80px;resize:vertical;max-height:220px;padding:10px;background:var(--bg-muted);color:inherit;border:1px solid var(--border-color,var(--border));border-radius:8px;font:inherit;line-height:1.6;margin:8px 0}
.project-assistant-selection{font-size:12px;line-height:1.5;overflow-wrap:anywhere}.assistant-value-fields{display:grid;grid-template-columns:minmax(4rem,auto) minmax(0,1fr);gap:6px 12px}.assistant-value-fields dt{font-weight:600}.assistant-value-fields dd{margin:0;min-width:0}.assistant-value-list{padding-left:20px}
.project-assistant button,.project-assistant input,.project-assistant select,.project-assistant textarea,.project-assistant summary{outline-offset:3px}
@media(max-width:1100px){.project-assistant{position:fixed;inset:0;z-index:1300;border:none;background:transparent}.project-assistant-backdrop{position:absolute;inset:0;border:0;background:rgba(0,0,0,.35)}.project-assistant-panel{position:absolute;inset:0 0 0 auto;width:min(100%,28rem);background:var(--bg-primary,var(--bg-base));padding-bottom:env(safe-area-inset-bottom)}.project-assistant .btn{min-height:44px}.project-assistant input[type=checkbox]{width:20px;height:20px}.project-assistant-composer textarea{font-size:16px}}
</style>
