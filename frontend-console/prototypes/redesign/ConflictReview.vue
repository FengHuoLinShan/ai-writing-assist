<script setup>
import { ref } from 'vue'
const emit = defineEmits(['open','navigate'])
const scope = ref('当前章节与场景')
const stage = ref('准备检查')
const selected = ref(0)
const decisions = ref({})
const issues = [
 { title: '灯塔亮起的时间', before: '第三章：灯塔在落潮前亮起。', source: '场景计划：落潮后才看到灯光。', impact: '两人的出发时间与通行条件需要一致。' },
 { title: '林舟知道多少秘密', before: '第三章：林舟仍在追问父亲的去向。', source: '人物资料：沈雁尚未透露三年前的真相。', impact: '本章对白不宜让林舟提前知道沈雁的身份。' },
]
</script>
<template><section class="rd-conflict-preview"><label class="rd-field">检查范围<select v-model="scope"><option>当前章节与场景</option><option>第一部 · 正式资料</option><option>当前人物与地点</option></select></label><p>仅演示故事一致性检查。它与保存时的版本冲突分开处理。</p><div class="rd-local-toolbar"><button class="rd-button purple" @click="stage = '检查中'">开始检查示例</button><button v-if="stage === '检查中'" class="rd-button" @click="stage = '已停止'">停止</button><button v-if="stage === '检查中'" class="rd-button" @click="stage = '待决定'">演示检查完成</button><button v-if="stage === '已停止'" class="rd-button" @click="stage = '检查中'">继续检查示例</button></div><progress v-if="stage === '检查中'" aria-label="故事一致性检查中"/><template v-if="stage === '待决定'"><div class="rd-inline-notice tone-orange"><strong>! 两处细节需要作者核对</strong><p>{{ scope }} · 这些是待判断的疑点，不代表已确认出错。</p></div><nav class="rd-detail-tabs"><button v-for="(item,i) in issues" :key="item.title" :aria-pressed="selected === i" @click="selected = i">{{ decisions[i] ? '✓ ' : '' }}{{ item.title }}</button></nav><h3>{{ issues[selected].title }}</h3><div class="rd-comparison"><section><span class="rd-eyebrow">正文来源</span><p>{{ issues[selected].before }}</p></section><section><span class="rd-eyebrow">相关资料</span><p>{{ issues[selected].source }}</p></section></div><p>{{ issues[selected].impact }}</p><div class="rd-local-toolbar"><button class="rd-button" @click="emit('navigate', 'search')">定位来源</button><button class="rd-button purple" @click="emit('open', '冲突处置建议', 'compare', true)">查看 AI 复审示例</button><button class="rd-button" @click="decisions[selected] = '已核对'">标为已核对 · 演示</button></div><p v-if="decisions[selected]" class="rd-inline-notice tone-green">✓ 已核对 · 演示。没有自动改写正文或资料。</p></template></section></template>
