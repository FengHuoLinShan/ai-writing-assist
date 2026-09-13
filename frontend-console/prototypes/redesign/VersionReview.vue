<script setup>
import { computed, ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
const emit = defineEmits(['close','open'])
const versions = [
  { name: '当前工作稿', time: '今天 14:32', type: '工作稿', text: '林舟抵达白沙港时，最后一班渡船刚刚离岸。年轻人没有立刻回答，他的手指收紧了一瞬。' },
  { name: '码头对话', time: '今天 11:08', type: '历史版本', text: '林舟走到码头，渡船已经离开。年轻人看着她手中的海图，似乎想起了什么。' },
  { name: '第一版场景', time: '昨天 20:16', type: '正式正文', text: '林舟来到白沙港。她展开了父亲的海图，等待一艘去往北方的船。' },
]
const left = ref(2)
const right = ref(0)
const comparing = ref(false)
const confirmAction = ref('')
const result = ref('')
const archived = ref(false)
const diff = computed(() => Math.abs(versions[right.value].text.length - versions[left.value].text.length))
function complete() {
  result.value = confirmAction.value === '正式正文' ? '✓ 正式正文确认完成 · 演示' : confirmAction.value === '恢复工作稿' ? '✓ 已从历史版本建立工作稿 · 演示' : '✓ 版本已移入历史 · 演示'
  if (confirmAction.value === '移入历史') archived.value = true
  confirmAction.value = ''
}
</script>
<template><section class="rd-version-review">
<p class="rd-dialog-lead">每一次修改，都有来处。</p><ul class="rd-data-list"><li v-for="(item,i) in versions" :key="item.name"><span class="rd-small-icon" :class="i === 0 ? 'tone-blue' : 'tone-green'"><PreviewIcon :name="i === 0 ? 'writing' : 'clock'"/></span><div><strong>{{ item.name }}</strong><small>{{ item.time }} · {{ item.type }} · 示例</small></div><button class="rd-text-button" @click="left = i; comparing = true">查看与比较 →</button></li></ul>
<div class="rd-local-toolbar"><button class="rd-button" @click="comparing = !comparing">{{ comparing ? '收起比较' : '任意两版比较' }}</button><button class="rd-button" @click="confirmAction = '正式正文'">设为正式正文</button></div>
<div v-if="comparing"><div class="rd-form-grid"><label class="rd-field">左侧版本<select v-model.number="left"><option v-for="(item,i) in versions" :key="item.name" :value="i">{{ item.name }}</option></select></label><label class="rd-field">右侧版本<select v-model.number="right"><option v-for="(item,i) in versions" :key="item.name" :value="i">{{ item.name }}</option></select></label></div><p class="rd-demonstration">{{ left === right ? '选择了同一版本，内容相同。' : `文字数量相差 ${diff} 字 · 示例片段` }}</p><div class="rd-comparison"><section><span class="rd-eyebrow">{{ versions[left].name }} · 只读</span><p>{{ versions[left].text }}</p></section><section><span class="rd-eyebrow">{{ versions[right].name }} · 只读</span><p>{{ versions[right].text }}</p></section></div><div class="rd-local-toolbar"><button class="rd-button primary" @click="confirmAction = '恢复工作稿'">从左侧版本继续写</button><button class="rd-button" :disabled="left === 0 || archived" @click="confirmAction = '移入历史'">{{ archived ? '已移入历史 · 演示' : '移入历史' }}</button></div></div>
<section v-if="confirmAction" class="rd-inline-notice" :class="confirmAction === '移入历史' ? 'tone-orange' : 'tone-blue'" aria-label="版本操作确认"><strong>{{ confirmAction === '正式正文' ? '将当前工作稿设为正式正文？' : confirmAction === '恢复工作稿' ? `从「${versions[left].name}」继续写？` : '将此版本移入历史？' }}</strong><p>{{ confirmAction === '正式正文' ? '正式正文用于作品内的稳定引用与后续整理，不是向外发布。候选采用后仍需这一步作者确认。' : confirmAction === '恢复工作稿' ? '原工作稿应先保全。正式接回后将建立可编辑工作稿，历史版本仍保留。' : '此版本会从常用列表收起，内容仍保留在历史中。' }}</p><ul v-if="confirmAction === '正式正文'"><li>当前对象：第三章 · 潮汐之间</li><li>仅确认正文；后续资料整理单独反馈</li><li>正式功能须重新检查保存与冲突状态</li></ul><div class="rd-local-toolbar"><button class="rd-button" @click="confirmAction = ''">取消并保留</button><button class="rd-button primary" @click="complete">演示确认结果</button></div></section>
<p v-if="result" role="status" class="rd-inline-notice tone-green">{{ result }}</p><details v-if="result.includes('正式正文')"><summary class="rd-text-button">查看后续整理失败示例</summary><p class="rd-inline-notice tone-orange">! 正文已确认，但资料整理暂未完成。正文状态不回退，请从任务中心重试整理。以上均为演示。</p><button class="rd-button" @click="emit('open', '正文整理任务', 'ai', true)">查看后续任务</button></details><p class="rd-demonstration">版本与操作均为示例，不恢复、覆盖或确认真实正文。</p>
</section></template>
