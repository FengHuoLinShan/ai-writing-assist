<script setup>
import { computed, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
const props = defineProps({ state: { type: String, default: 'normal' } })
const emit = defineEmits(['navigate'])
const choice = ref(-1)
const adoptedChoice = ref(-1)
const readerInput = ref('')
const hasChoice = computed(() => choice.value >= 0 || Boolean(readerInput.value.trim()))
const branchPreview = ref(false)
const panel = ref('')
const stage = ref('阅读中')
watch(() => props.state, value => { stage.value = value === 'loading' ? '等待回应' : value === 'error' ? '超时' : '阅读中' }, { immediate: true })
const convention = ref('请保持林舟的好奇心，让秘密通过细节逐渐露出来。')
const savedConvention = ref('')
const progress = ref('第三章 · 码头初遇')
const upgrade = ref(false)
const viewing = ref(false)
function openRecap() { panel.value = '回顾' }
defineExpose({ openRecap })
</script>
<template><div class="rd-page-scroll"><div class="rd-page-inner rd-reader-inner rd-reading-preview">
<div v-if="stage === '超时'" class="rd-inline-notice tone-orange"><strong>这一段暂时没有等到回应</strong><p>你已经读到的文字和当前输入都保留着。可以稍后再试，也可以先回看故事。</p><button class="rd-button" @click="stage = '阅读中'">回到已读内容</button><button class="rd-text-button" @click="stage = '等待回应'">重试示例 →</button></div>
<div v-if="['等待回应','流式进行中'].includes(stage)" class="rd-inline-notice tone-purple" role="status"><span class="rd-spinner"/><strong>{{ stage === '流式进行中' ? '故事正在继续 · 演示' : '正在等待下一段 · 演示' }}</strong><p>下面已读内容保持稳定。</p><button class="rd-button" @click="stage = '已停止'">停止等待</button></div>
<div v-if="state === 'empty'" class="rd-dense-empty"><h1>故事还在等你开场</h1><p>说说你是谁，想在什么地方遇见故事。</p><button class="rd-button purple" @click="emit('navigate', 'journeys')">准备新的旅程</button></div>
<template v-else>
<header class="rd-reader-heading"><span class="rd-eyebrow">潮汐之间 · 第三幕</span><h1>最后一班渡船</h1><span class="rd-badge tone-teal">白沙港 · 黄昏</span></header><article class="rd-reader-prose"><p>码头上只剩下你和那个提着风灯的年轻人。远处的船影渐渐消失在雾里，你意识到，自己已经没有回程的船票。</p><p>你抬起头。一个穿深蓝色外套的年轻人站在石阶上，手里提着一盏没有点亮的风灯。他的袖口沾着盐，目光却落在你手里的海图上。</p><blockquote>“如果你想知道海图的事，”他说，“今夜，不要离开港口。”</blockquote><p>他把风灯放在你身旁。灯芯没有点燃，玻璃罩里却隐隐透着一抹蓝色。你听见远处传来钟声，一下，又一下。</p><p>你想先问他什么？</p></article><div class="rd-reader-choices"><button v-for="(item,i) in ['问他为什么认识这张海图','问起三年前熄灭的灯塔','暂时沉默，观察那盏风灯']" :key="item" :aria-pressed="choice === i" @click="choice = i; branchPreview = true"><span>{{ String(i+1).padStart(2,'0') }}</span>{{ item }}<PreviewIcon :name="choice === i ? 'check' : 'forward'"/></button></div><div class="rd-reader-input"><label><span class="rd-sr-only">写下自己的选择</span><input v-model="readerInput" placeholder="也可以，写下自己的选择…" /></label><button class="rd-icon-button" aria-label="查看分支反馈示例" :disabled="!hasChoice" @click="branchPreview = hasChoice"><span class="rd-button-content">↑</span></button></div><div class="rd-reader-bottom"><button class="rd-text-button" @click="panel = panel === '回顾' ? '' : '回顾'"><PreviewIcon name="clock"/>旅程回顾</button><button class="rd-text-button" @click="panel = panel === '来源与进度' ? '' : '来源与进度'">人物与线索 <PreviewIcon name="forward"/></button><span>分支选择演示 · 不生成内容</span></div>
<section v-if="branchPreview" class="rd-detail-surface rd-reader-branch"><span class="rd-badge tone-purple">候选发展 · 尚未选中</span><h2>先看看，故事会走向哪里。</h2><p>{{ readerInput || ['海图上的银色记号，让沈雁想起一位旧人。','三年前的灯塔，在风暴来临时熄灭。','风灯玻璃里的微光，回应了远处的钟声。'][Math.max(choice,0)] }}</p><div class="rd-local-toolbar"><button class="rd-button" @click="branchPreview = false">暂不选择</button><button class="rd-button purple" :disabled="!hasChoice" @click="adoptedChoice = readerInput.trim() ? 3 : choice; branchPreview = false">采用这个发展 · 演示</button></div><small>这里只演示分支决定，不请求生成、不追加新正文。</small></section>
<p v-if="adoptedChoice >= 0" class="rd-demonstration">✓ {{ adoptedChoice === 3 ? '你写下的发展' : `第 ${adoptedChoice + 1} 个发展` }}已选中 · 演示。未选候选没有进入故事。</p>
<nav class="rd-detail-tabs" aria-label="阅读辅助"><button v-for="item in ['回顾','长期约定','来源与进度']" :key="item" :aria-pressed="panel === item" @click="panel = panel === item ? '' : item">{{ item }}</button><button @click="emit('navigate', 'settings', '外观')">阅读外观</button></nav>
<section v-if="panel" class="rd-detail-surface"><div class="rd-detail-heading"><h2>{{ panel }}</h2><button class="rd-icon-button" aria-label="关闭阅读辅助" @click="panel = ''"><PreviewIcon name="close"/></button></div><template v-if="panel === '回顾'"><ol class="rd-reader-recap"><li><strong>抵达白沙港</strong><p>你错过了最后一班渡船。</p></li><li><strong>码头初遇</strong><p>沈雁认出了你手里的海图。</p></li><li><strong>灯塔亮起</strong><p>你决定在港口再留一晚。</p></li></ol><p>回顾基于当前示例已选故事；它不会改写你保留的长期约定。</p><button class="rd-text-button" @click="panel = '长期约定'">修改希望故事记住的事 →</button></template><template v-else-if="panel === '长期约定'"><label class="rd-field">希望故事一直记住什么？<textarea v-model="convention" rows="4"/></label><button class="rd-button purple" @click="savedConvention = convention">保留约定示例</button><p v-if="savedConvention" role="status" class="rd-inline-notice tone-green">✓ 约定已保留 · 演示。自动回顾不会覆盖它。</p></template><template v-else><span class="rd-badge tone-teal">潮汐来信 · 示例资料版本</span><p>你扮演林舟。资料只展示到当前故事进度，后续秘密不提前带入。</p><label class="rd-field">故事进度<select v-model="progress"><option>第三章 · 码头初遇</option><option>第三章 · 灯塔亮起</option><option>第四章 · 夜探灯塔</option></select></label><button class="rd-button" @click="upgrade = !upgrade">查看新资料版本示例</button><div v-if="upgrade" class="rd-inline-notice tone-orange"><strong>有一份新的作品资料</strong><p>更新可能改变当前人物资料。先比较，再决定是否继续使用。</p><button class="rd-text-button" @click="upgrade = false">继续使用当前版本</button></div><label class="rd-check-label"><input type="checkbox"/>固定关注沈雁的线索</label><label class="rd-check-label"><input type="checkbox"/>忽略与当前旅程无关的组织资料</label></template></section>
<details class="rd-reader-demo"><summary>阅读反馈演示</summary><div class="rd-local-toolbar"><button v-for="item in ['阅读中','等待回应','流式进行中','超时','已停止']" :key="item" class="rd-button" :aria-pressed="stage === item" @click="stage = item">{{ item }}</button><button class="rd-switch" role="switch" aria-label="连续观看示例" :aria-checked="viewing" @click="viewing = !viewing"><span/></button><span>连续观看 · {{ viewing ? '开启样式' : '关闭' }}</span></div><p>手动切换反馈，不自动播放故事，不根据动画结束生成结果。</p></details>
</template></div></div></template>
<style>
#redesign-root .rd-reading-preview .rd-reader-branch{margin:24px 0}#redesign-root .rd-reading-preview .rd-reader-branch h2{margin:15px 0}#redesign-root .rd-reading-preview .rd-detail-surface p{line-height:2}#redesign-root .rd-reading-preview .rd-reader-recap{padding-left:20px}#redesign-root .rd-reading-preview .rd-reader-recap li{padding:12px 0}#redesign-root .rd-reading-preview .rd-reader-demo{margin-top:30px;color:var(--muted);font-size:12px}#redesign-root .rd-reading-preview .rd-reader-demo summary{cursor:pointer;padding:12px 0}
</style>
