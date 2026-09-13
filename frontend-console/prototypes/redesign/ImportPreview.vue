<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  state: { type: String, default: 'normal' },
  initialSection: { type: String, default: 'file' },
})
const emit = defineEmits(['navigate', 'open'])

const chapters = [
  { id: 1, title: '雾中的灯塔', words: '2,840', note: '正文已识别' },
  { id: 2, title: '一封迟到的信', words: '3,126', note: '正文已识别' },
  { id: 3, title: '潮汐之间：码头上的初次相遇与未说出口的话', words: '1,862', note: '正文已识别' },
  { id: 4, title: '没有名字的航线', words: '待开始', note: '提纲片段' },
]
const step = ref(props.initialSection === 'prepare' ? 3 : props.initialSection === 'chapters' ? 2 : 1)
const fileChosen = ref(props.initialSection === 'chapters' || props.initialSection === 'prepare')
const parseState = ref(props.state === 'error' ? 'error' : 'ready')
const workflowState = ref('未开始')
const successItems = reactive(['人物 2 项'])
const selected = reactive(new Set(chapters.map(chapter => chapter.id)))
const selectedCount = computed(() => selected.size)
const stepLabel = computed(() => step.value === 1 ? '选择文稿' : step.value === 2 ? '检查章节' : '准备资料')
function chooseSample() { fileChosen.value = true; step.value = 2 }
function retryParse() { parseState.value = 'ready' }
function toggleChapter(id) { selected.has(id) ? selected.delete(id) : selected.add(id) }
function prepareMaterials() {
  if (!selectedCount.value || parseState.value === 'error') return
  step.value = 3
}
function startOrganize() { workflowState.value = '进行中' }
function stopOrganize() { workflowState.value = '已停止' }
function failOrganize() { workflowState.value = '失败' }
function resumeOrganize() { workflowState.value = '进行中' }
function retryOrganize() { workflowState.value = '进行中' }
function finishOrganize() { workflowState.value = '待决定'; if (!successItems.includes('地点 1 项')) successItems.push('地点 1 项') }
function back() {
  if (step.value > 1) step.value -= 1
  else emit('navigate', 'projects')
}
function cancel() { emit('navigate', 'projects') }
watch(() => props.state, value => { if (value === 'error') parseState.value = 'error' })
</script>

<template>
  <div class="rd-page-scroll"><div class="rd-page-inner rd-import-preview" aria-labelledby="import-preview-title">
    <header class="rd-page-heading">
      <div><span class="rd-eyebrow">导入与整理 · 演示</span><h1 id="import-preview-title">让故事在这里继续</h1><p>选择一份示例文稿，先检查章节，再准备资料。</p></div>
      <button class="rd-text-button" @click="cancel">返回作品档案</button>
    </header>

    <nav class="rd-import-steps" aria-label="导入步骤">
      <span v-for="item in [[1, '选择文稿'], [2, '检查章节'], [3, '准备资料']]" :key="item[0]" :class="{ active: step === item[0], done: step > item[0] }">{{ item[0] }} {{ item[1] }}</span>
    </nav>

    <section v-if="step === 1" class="rd-import-card">
      <div class="rd-color-icon tone-blue">⌁</div>
      <h2>选择示例文稿</h2>
      <p>支持 txt、epub、html、htm，单个文件最大 50MB。这里只使用虚构内容，不读取本地文件。</p>
      <button class="rd-button primary" @click="chooseSample">选择《潮汐来信.txt》</button>
      <button class="rd-button" @click="cancel">取消</button>
    </section>

    <template v-else-if="step === 2">
      <section class="rd-import-card rd-import-file-summary">
        <div><span class="rd-badge tone-green">示例文件 · 已识别</span><h2>潮汐来信.txt</h2><p>纯文本 · 7,828 字 · 4 个章节候选</p></div>
        <button class="rd-text-button" @click="step = 1">重新选择</button>
      </section>
      <div v-if="parseState === 'error'" class="rd-inline-notice tone-orange" role="alert"><strong>! 章节解析暂时没有完成 · 演示</strong><p>原始示例仍保留。可以重试解析，或返回重新选择。</p><button class="rd-button" @click="retryParse">重试解析</button></div>
      <section v-else class="rd-import-card">
        <div class="rd-detail-heading"><div><span class="rd-eyebrow">第 2 步</span><h2>检查章节拆分</h2></div><span class="rd-badge tone-blue">{{ selectedCount }} / {{ chapters.length }} 章已选</span></div>
        <p>确认要作为工作稿导入的范围。标题较长时会完整保留，导入不会自动写入正式正文。</p>
        <div class="rd-import-chapters">
          <label v-for="chapter in chapters" :key="chapter.id" class="rd-import-chapter"><input type="checkbox" :checked="selected.has(chapter.id)" @change="toggleChapter(chapter.id)"/><span><strong>{{ chapter.title }}</strong><small>{{ chapter.words }} 字 · {{ chapter.note }}</small></span></label>
        </div>
        <div class="rd-local-toolbar"><button class="rd-button" @click="selected.clear">清空选择</button><button class="rd-button" @click="chapters.forEach(chapter => selected.add(chapter.id))">全选章节</button></div>
        <div class="rd-import-actions"><button class="rd-button" @click="back">上一步</button><button class="rd-button primary" :disabled="!selectedCount" @click="prepareMaterials">准备资料</button></div>
      </section>
    </template>

    <section v-else class="rd-import-card">
      <div class="rd-detail-heading"><div><span class="rd-eyebrow">第 3 步</span><h2>准备资料</h2></div><span class="rd-badge tone-purple">尚未写入作品 · 演示</span></div>
      <p>已选择 {{ selectedCount }} 个章节。下一步可决定整理人物、地点、关系与剧情线的范围。</p>
      <div class="rd-import-scope"><label><input type="checkbox" checked/>人物与地点</label><label><input type="checkbox" checked/>关系与规则</label><label><input type="checkbox"/>剧情线与节拍</label></div>
      <div class="rd-import-quality"><span class="rd-eyebrow">整理质量与授权范围</span><p>先生成可供你核对的候选资料；低置信或冲突内容会留在待决定，不会自动写入正式设定。</p><label><input type="checkbox" checked/>本次允许整理所选章节</label><label><input type="checkbox"/>持续整理后续新增章节（演示授权）</label><label>质量偏好<select><option>平衡：保留原文证据</option><option>谨慎：只整理高置信内容</option><option>完整：多保留待核对建议</option></select></label></div>
      <section class="rd-import-workflow" aria-label="整理工作流">
        <div class="rd-detail-heading"><div><span class="rd-eyebrow">整理进度 · 演示</span><h2>{{ workflowState }}</h2></div><span class="rd-badge" :class="workflowState === '失败' ? 'tone-red' : workflowState === '待决定' ? 'tone-orange' : 'tone-purple'">{{ successItems.length }} 项已完成</span></div>
        <p v-if="workflowState === '未开始'">确认范围后手动开始；这里不会自动运行模型或伪造进度。</p>
        <p v-else-if="workflowState === '进行中'">正在整理已选择章节。已完成项会保留。</p>
        <p v-else-if="workflowState === '已停止'">整理已停止，可以稍后恢复；已完成项仍可查看。</p>
        <p v-else-if="workflowState === '失败'">本轮整理没有完成。重试会继续未完成范围，不会重置已完成项。</p>
        <p v-else>有内容需要你决定。候选资料尚未写入正式设定。</p>
        <ul class="rd-import-successes"><li v-for="item in successItems" :key="item">✓ {{ item }} · 已保留</li></ul>
        <div class="rd-local-toolbar"><button v-if="workflowState === '未开始'" class="rd-button purple" @click="startOrganize">开始整理示例</button><button v-if="workflowState === '进行中'" class="rd-button" @click="stopOrganize">停止</button><button v-if="workflowState === '进行中'" class="rd-button" @click="finishOrganize">演示整理完成</button><button v-if="workflowState === '进行中'" class="rd-button danger" @click="failOrganize">演示失败</button><button v-if="workflowState === '已停止'" class="rd-button" @click="resumeOrganize">恢复整理</button><button v-if="workflowState === '失败'" class="rd-button" @click="retryOrganize">重试未完成部分</button><button v-if="workflowState === '待决定'" class="rd-button primary" @click="emit('open', '审阅导入世界资料', 'compare', true)">审阅导入世界资料</button><button v-if="workflowState === '待决定'" class="rd-text-button" @click="emit('open', '查漏与处理记录', 'import', true)">查看查漏与处理记录 →</button></div>
      </section>
      <p class="rd-demonstration">以上工作流均为手动演示；正式任务、候选审阅和处理记录由后续整理流程承接。</p>
      <div class="rd-import-actions"><button class="rd-button" @click="back">返回章节检查</button><button class="rd-button primary" @click="emit('open', '准备整理资料', 'import', true)">查看整理范围 · 演示</button></div>
    </section>

    <footer class="rd-import-footer"><span>当前步骤：{{ stepLabel }} · 虚构示例</span><button class="rd-text-button" @click="cancel">取消并返回档案</button></footer>
  </div></div>
</template>

<style>
#redesign-root .rd-import-preview { max-width: 980px; margin: 0 auto; padding: 0 42px 60px; color: var(--ink); }
#redesign-root .rd-import-preview .rd-page-heading { align-items: end; }
#redesign-root .rd-import-preview .rd-import-steps { display: flex; gap: 22px; align-items: center; margin: 28px 0; color: var(--muted); font-size: 12px; }
#redesign-root .rd-import-preview .rd-import-steps span.active { color: var(--blue); font-weight: 650; }
#redesign-root .rd-import-preview .rd-import-steps span.done { color: var(--green); }
#redesign-root .rd-import-preview .rd-import-card { padding: 26px; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
#redesign-root .rd-import-preview .rd-import-card h2 { margin: 12px 0 8px; font-size: 21px; }
#redesign-root .rd-import-preview .rd-import-card p { color: var(--muted); line-height: 1.9; }
#redesign-root .rd-import-preview .rd-import-file-summary { display: flex; justify-content: space-between; align-items: center; }
#redesign-root .rd-import-preview .rd-import-chapters { display: grid; gap: 8px; margin-top: 20px; }
#redesign-root .rd-import-preview .rd-import-chapter { display: flex; gap: 12px; align-items: start; padding: 14px; border: 1px solid var(--line); border-radius: 10px; cursor: pointer; }
#redesign-root .rd-import-preview .rd-import-chapter:hover { background: var(--hover); }
#redesign-root .rd-import-preview .rd-import-chapter span { display: grid; gap: 5px; min-width: 0; }
#redesign-root .rd-import-preview .rd-import-chapter strong { overflow-wrap: anywhere; }
#redesign-root .rd-import-preview .rd-import-chapter small { color: var(--muted); }
#redesign-root .rd-import-preview .rd-import-scope { display: grid; gap: 12px; margin: 20px 0; }
#redesign-root .rd-import-preview .rd-import-quality { display: grid; gap: 10px; margin: 22px 0; padding: 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
#redesign-root .rd-import-preview .rd-import-quality p { margin: 0; }
#redesign-root .rd-import-preview .rd-import-quality select { margin-left: 8px; }
#redesign-root .rd-import-preview .rd-import-workflow { margin: 22px 0; padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--bg); }
#redesign-root .rd-import-preview .rd-import-workflow h2 { margin: 5px 0 0; font-size: 18px; }
#redesign-root .rd-import-preview .rd-import-successes { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 0; list-style: none; color: var(--green); font-size: 12px; }
#redesign-root .rd-import-preview .rd-import-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
#redesign-root .rd-import-preview .rd-import-footer { display: flex; justify-content: space-between; gap: 12px; margin-top: 22px; color: var(--muted); font-size: 11px; }
@media (max-width: 760px) {
  #redesign-root .rd-import-preview { padding: 24px 18px 42px; }
  #redesign-root .rd-import-preview .rd-import-steps { gap: 10px; flex-wrap: wrap; }
  #redesign-root .rd-import-preview .rd-import-file-summary { align-items: start; flex-direction: column; gap: 12px; }
  #redesign-root .rd-import-preview .rd-import-actions { justify-content: stretch; }
  #redesign-root .rd-import-preview .rd-import-actions .rd-button { flex: 1; }
  #redesign-root .rd-import-preview .rd-import-footer { align-items: start; flex-direction: column; }
}
</style>
