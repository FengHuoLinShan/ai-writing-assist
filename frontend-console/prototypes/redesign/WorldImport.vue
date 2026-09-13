<script setup>
import { computed, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'

const props = defineProps({
  state: { type: String, default: 'normal' },
  initialSection: { type: String, default: '导入目录' },
})
const emit = defineEmits(['open', 'navigate', 'recovered'])

const files = [
  { name: 'worldbook.md', kind: 'Markdown', count: 12, status: '已识别', tone: 'green', detail: '包含人物、地点和规则的长篇说明。' },
  { name: 'characters.yml', kind: 'YAML', count: 6, status: '缺少来源', tone: 'orange', detail: '有 2 项资料没有对应章节或原文引用。' },
  { name: 'timeline.json', kind: 'JSON', count: 5, status: '存在冲突', tone: 'red', detail: '“灯塔熄灭三年”与第一章记录需要比较。' },
]
const tabs = ['导入目录', '资料健康', '处理历史']
const tab = ref(tabs.includes(props.initialSection) ? props.initialSection : '导入目录')
const scanned = ref(false)
const draftCreated = ref(false)
const scopeOpen = ref(false)
const selectedFile = ref(null)
const feedback = ref('')
const retried = ref(false)
const healthChecked = ref(false)
const historyFilter = ref('全部记录')
const historyFeedback = ref('')
const healthItems = [
  { title: '来源完整度', value: '2 项缺少来源', tone: 'orange', detail: 'characters.yml 中有两项只有说明，没有对应章节或原文引用。' },
  { title: '内容冲突', value: '1 项需要比较', tone: 'red', detail: 'timeline.json 的灯塔时间与第一章记录不同，不能直接确认。' },
  { title: '对象重复', value: '可继续检查', tone: 'green', detail: '沈雁与守塔人的称呼可以归并到同一已有对象。' },
]
const historyItems = [
  { id: 'run-1', time: '今天 14:32', title: '世界书目录整理', status: '部分完成', tone: 'orange', detail: '23 项候选资料已生成，2 项来源不完整。', next: '继续处理来源问题' },
  { id: 'run-2', time: '昨天 18:10', title: '冲突检查', status: '失败可恢复', tone: 'red', detail: '检查在 timeline.json 处中断，原始目录没有变化。', next: '重新检查冲突' },
  { id: 'run-3', time: '周一 09:20', title: '人物资料预览', status: '已完成', tone: 'green', detail: '8 项人物候选已保留为待审阅资料。', next: '查看采用范围' },
]

watch(() => props.initialSection, value => { if (tabs.includes(value)) tab.value = value })
const totalCandidates = computed(() => files.reduce((sum, file) => sum + file.count, 0))
const issueCount = computed(() => files.filter(file => file.tone !== 'green').length)
function scan() { emit('recovered'); scanned.value = true; retried.value = true; feedback.value = '示例目录已扫描 · 发现 23 项候选资料' }
function createDraft() { draftCreated.value = true; feedback.value = '工作稿示例已建立 · 尚未进入正式世界资料' }
function showFile(file) { selectedFile.value = file }
function review() { emit('open', '审阅世界资料', 'compare', true) }
function runHealthCheck() { healthChecked.value = true; feedback.value = '资料健康检查完成 · 仍有 2 项需要处理，未代表审查通过' }
function continueHistory(item) { historyFeedback.value = item.status === '已完成' ? `${item.next} · 已打开范围示例` : `${item.next} · 已恢复失败步骤示例，等待下一步` }
</script>

<template>
  <section class="rd-world-import" aria-label="世界书目录导入">
    <header class="rd-world-review-heading">
      <div><span class="rd-eyebrow">世界资料 / 世界书 · 本次预览</span><h2>先看清目录，再决定哪些资料留下。</h2><p>示例导入只展示整理范围，不读取本地文件，也不会自动修改世界资料。</p></div>
      <span class="rd-badge tone-blue">候选资料 · {{ totalCandidates }} 项</span>
    </header>
    <nav class="rd-segments rd-fit rd-world-import-tabs" aria-label="世界书视图"><button v-for="item in tabs" :key="item" type="button" :aria-pressed="tab === item" @click="tab = item; feedback = ''; historyFeedback = ''">{{ item }}</button></nav>

    <div v-if="props.state === 'loading'" class="rd-inline-notice tone-blue" role="status"><strong>正在扫描示例目录</strong><p>这里只展示加载状态，不会访问文件系统。</p></div>
    <div v-if="props.state === 'error' && !retried" class="rd-inline-notice tone-orange" role="alert"><strong>! 目录预览暂时没有更新</strong><p>上次示例内容仍然可用，可以重新扫描。</p><button class="rd-button" type="button" @click="scan">重新扫描示例</button></div>
    <div v-else-if="props.state === 'error' && retried" class="rd-inline-notice tone-green" role="status"><strong>✓ 示例目录已重新扫描</strong><p>这是本地预览反馈，没有访问文件系统。</p></div>

    <section class="rd-import-dropzone" :class="{ scanned }">
      <span class="rd-color-icon tone-blue"><PreviewIcon name="project" /></span>
      <div><h3>{{ scanned ? '示例目录已准备好' : '扫描一个世界书目录' }}</h3><p>{{ scanned ? '下面是可供审阅的候选资料范围。' : '目录中的 Markdown、YAML 和 JSON 会先进入候选资料。' }}</p></div>
      <button class="rd-button primary" type="button" @click="scan">{{ scanned ? '重新扫描' : '扫描示例目录' }}</button>
    </section>

    <template v-if="tab === '导入目录' && scanned">
      <div class="rd-import-summary">
        <div><span>候选资料</span><strong>{{ totalCandidates }} 项</strong><small>等待审阅</small></div>
        <PreviewIcon name="arrow" />
        <div><span>工作稿示例</span><strong>{{ draftCreated ? totalCandidates : 0 }} 项</strong><small>{{ draftCreated ? '已建立，尚未采用' : '尚未建立' }}</small></div>
        <div><span>需要注意</span><strong class="rd-danger-text">{{ issueCount }} 个文件</strong><small>冲突或缺少来源</small></div>
      </div>

      <div class="rd-world-import-actions"><button class="rd-button primary" type="button" @click="createDraft">{{ draftCreated ? '重新查看工作稿示例' : '建立工作稿示例' }}</button><button class="rd-button" type="button" @click="scopeOpen = !scopeOpen">{{ scopeOpen ? '收起采用范围' : '查看采用范围' }}</button><button class="rd-text-button" type="button" @click="review">进入资料审阅 <PreviewIcon name="forward" /></button></div>
      <section v-if="scopeOpen" class="rd-import-scope" aria-label="采用范围"><span class="rd-eyebrow">采用范围 · 示例</span><h3>只处理这次目录产生的 23 项候选资料。</h3><p>确认后进入工作稿的对象：人物 8 项、地点 6 项、物品 4 项、规则 5 项。冲突和缺来源项目仍需你的判断。</p><span class="rd-badge tone-purple">不会覆盖已有正式资料</span></section>

      <div class="rd-import-files"><div class="rd-section-title"><h3>目录预览</h3><span class="rd-muted">{{ files.length }} 个文件 · {{ totalCandidates }} 项候选</span></div><button v-for="file in files" :key="file.name" class="rd-import-file" :class="{ selected: selectedFile?.name === file.name }" type="button" @click="showFile(file)"><span class="rd-small-icon" :class="`tone-${file.tone}`"><PreviewIcon name="project" /></span><span><strong>{{ file.name }}</strong><small>{{ file.kind }} · {{ file.count }} 项候选</small></span><span class="rd-badge" :class="`tone-${file.tone}`">{{ file.status }}</span><PreviewIcon name="forward" /></button></div>
      <section v-if="selectedFile" class="rd-import-file-detail" aria-label="导入文件说明"><div><span class="rd-eyebrow">{{ selectedFile.name }} · 需要注意</span><h3>{{ selectedFile.status }}</h3><p>{{ selectedFile.detail }}</p></div><button class="rd-text-button" type="button" @click="selectedFile = null">关闭 <PreviewIcon name="close" /></button></section>
    </template>
    <section v-else-if="tab === '导入目录'" class="rd-import-before-scan rd-empty"><span class="rd-empty-symbol"><PreviewIcon name="project" /></span><h3>扫描后才会显示候选资料</h3><p>先查看示例目录里有哪些文件，再决定是否建立工作稿。</p></section>
    <section v-else-if="tab === '资料健康'" class="rd-world-health" aria-label="资料健康检查">
      <div class="rd-world-health-heading"><div><span class="rd-eyebrow">资料健康 · 状态检查</span><h3>{{ healthChecked ? '检查完成，但还有事项需要处理。' : '先看资料是否准备好。' }}</h3><p>健康检查帮助定位问题，不等于候选审阅通过，也不会自动采用任何资料。</p></div><button class="rd-button" type="button" @click="runHealthCheck">{{ healthChecked ? '再次检查示例' : '检查示例资料' }}</button></div>
      <div class="rd-world-health-grid"><article v-for="item in healthItems" :key="item.title" class="rd-world-health-card"><span class="rd-badge" :class="`tone-${item.tone}`">{{ item.value }}</span><h4>{{ item.title }}</h4><p>{{ item.detail }}</p><button class="rd-text-button" type="button" @click="tab = '导入目录'; scanned = true">去查看范围 <PreviewIcon name="forward" /></button></article></div>
      <div class="rd-inline-notice tone-orange"><strong>仍需作者判断 · 示例</strong><p>存在冲突或缺少来源的资料会留在候选队列，先补证据或逐项决定。</p><button class="rd-button" type="button" @click="review">打开资料审阅</button></div>
    </section>
    <section v-else class="rd-world-history-view" aria-label="处理历史">
      <div class="rd-world-health-heading"><div><span class="rd-eyebrow">处理历史 · 本次预览</span><h3>每次整理都留下下一步。</h3><p>失败记录可以恢复，处理历史不会把中断写成已完成。</p></div><label class="rd-field">显示<select v-model="historyFilter" aria-label="处理历史筛选"><option>全部记录</option><option>可恢复</option><option>已完成</option></select></label></div>
      <div class="rd-world-history-view-list"><article v-for="item in historyItems.filter(item => historyFilter === '全部记录' || (historyFilter === '可恢复' ? item.status === '失败可恢复' : item.status === '已完成'))" :key="item.id" class="rd-world-history-view-row"><div><span class="rd-eyebrow">{{ item.time }}</span><h4>{{ item.title }} <span class="rd-badge" :class="`tone-${item.tone}`">{{ item.status }}</span></h4><p>{{ item.detail }}</p><small>下一步：{{ item.next }}</small></div><button class="rd-button" type="button" @click="continueHistory(item)">{{ item.status === '已完成' ? '查看范围' : '继续处理' }}</button></article></div>
      <p v-if="historyFeedback" class="rd-inline-notice tone-green" role="status">{{ historyFeedback }}</p>
    </section>
    <p v-if="feedback" class="rd-inline-notice tone-green" role="status">{{ feedback }}</p>
    <p class="rd-demonstration">候选资料、工作稿示例和正式世界资料分开表达；本预览不会上传文件或写入作品。</p>
  </section>
</template>
