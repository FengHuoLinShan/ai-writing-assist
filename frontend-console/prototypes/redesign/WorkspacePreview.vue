<script setup>
import { computed, ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import PreviewNotice from './PreviewNotice.vue'
import { vReveal } from './motion.js'
const props = defineProps({ page: { type: String, required: true }, state: { type: String, default: 'normal' }, initialSection: { type: String, default: '全部' } })
const emit = defineEmits(['navigate', 'open'])
const tab = ref(props.initialSection)
const query = ref('')
const activeBook = ref(null)
const editingBook = ref(false)
const bookName = ref('')
const archivedBooks = ref([])
const books = ref(['潮汐来信','群山的回声','星期天的宇宙'])
const tasks = ref([
 { name: '写完码头相遇的最后一幕', note: '让灯塔在落潮前亮起。', source: 'writing', group: '今天', done: false },
 { name: '补全沈雁的过往', note: '从海难后的三年开始。', source: 'world', group: '今天', done: false },
 { name: '梳理第一部的三条线索', note: '保持人物知识边界。', source: 'outline', group: '之后', done: false },
])
const taskGroup = ref('今天')
const activeTask = ref(null)
const taskDraft = ref({ name: '', note: '', group: '今天', source: 'writing', done: false })
const feedback = ref('')
const taskDrafts = new Map()
const bookDrafts = new Map()
const visibleBooks = computed(() => books.value.filter(book => book.includes(query.value) && ((tab.value === '已归档') === archivedBooks.value.includes(book))))
const visibleTasks = computed(() => tasks.value.filter(task => taskGroup.value === '已完成' ? task.done : !task.done && task.group === taskGroup.value))
function editTask(task) { if (activeTask.value) taskDrafts.set(activeTask.value, { ...taskDraft.value }); activeTask.value = task; taskDraft.value = { ...(taskDrafts.get(task) || task) }; feedback.value = '' }
function saveTask() { if (!taskDraft.value.name.trim()) return; if (tasks.value.includes(activeTask.value)) Object.assign(activeTask.value, taskDraft.value); else tasks.value.push({ ...taskDraft.value }); taskDrafts.delete(activeTask.value); activeTask.value = null; feedback.value = '✓ 创作计划已更新 · 本次预览' }
function selectBook(book) { if (editingBook.value) bookDrafts.set(activeBook.value, bookName.value); activeBook.value = book; editingBook.value = false }
function editBook(book) { if (editingBook.value) bookDrafts.set(activeBook.value, bookName.value); activeBook.value = book; bookName.value = bookDrafts.get(book) ?? book ?? ''; editingBook.value = true }
function saveBook() { if (!bookName.value.trim()) return; if (activeBook.value) books.value[books.value.indexOf(activeBook.value)] = bookName.value.trim(); else books.value.push(bookName.value.trim()); bookDrafts.delete(activeBook.value); activeBook.value = bookName.value.trim(); editingBook.value = false; feedback.value = '✓ 作品档案已更新 · 本次预览' }
function archiveBook() { if (confirm('将这部示例作品移入回收区？可从已归档恢复。')) { archivedBooks.value.push(activeBook.value); activeBook.value = null } }
</script>
<template>
  <div class="rd-page-scroll"><div v-reveal class="rd-page-inner">
    <PreviewNotice :state="state" @action="emit('open', '状态与下一步', 'states')" />
    <template v-if="state !== 'empty'">
    <template v-if="page === 'today'">
      <header class="rd-page-heading"><div><h1>创作概览</h1><p>潮汐来信 · 今天的创作</p></div><span class="rd-date">星期六 · 9 月 12 日</span></header>
      <div class="rd-overview-grid"><button class="rd-continue-card" @click="emit('navigate', 'writing')"><span class="rd-eyebrow">继续你的故事</span><h2>潮汐来信</h2><p>第三章 · 潮汐之间</p><span class="rd-continue-bottom">回到写作 <PreviewIcon name="forward"/></span><span class="rd-mini-cover" aria-hidden="true">潮</span></button><section class="rd-stat-card"><span class="rd-color-icon tone-green"><PreviewIcon name="writing" /></span><h3>今天的文字</h3><div class="rd-stat">862 <small>字</small></div><progress value="862" max="1500" aria-label="示例写作目标"/><p>完成每日目标的 57%</p><span class="rd-badge tone-green">✓ 连续创作 5 天</span></section><section class="rd-stat-card attention"><span class="rd-color-icon tone-orange">!</span><h3>需要你的决定</h3><div class="rd-stat">3 <small>项</small></div><p>两条设定建议，一处故事冲突。<br>你的判断，让世界更清晰。</p><button class="rd-text-button" @click="emit('navigate', 'world', '需要决定')">一起看看 →</button></section></div>
      <div class="rd-two-columns"><section><div class="rd-section-title"><h2>今日计划</h2><button class="rd-text-button" @click="emit('navigate', 'tasks')">全部计划 <PreviewIcon name="forward"/></button></div><button v-for="(item, i) in ['写完码头相遇的最后一幕', '补全沈雁的过往', '梳理第一部的三条线索']" :key="item" class="rd-task-row" @click="emit('open', item, 'task', true)"><span class="rd-task-circle"/><span><strong>{{ item }}</strong><small>{{ ['第三章 · 写作', '人物与世界', '故事结构'][i] }}</small></span><span class="rd-badge" :class="i === 0 ? 'tone-blue' : ''">{{ i === 0 ? '今天' : '稍后' }}</span></button></section><section><div class="rd-section-title"><h2>灵感便笺</h2><span class="rd-purple-text">✦</span></div><div class="rd-inspiration-card"><span class="rd-eyebrow">写作灵感</span><h3>如果一个人守着秘密，<br>是为了保护那个追问的人呢？</h3><p>试着从沈雁的视角，重新看一遍码头上的相遇。</p><button class="rd-button purple" @click="emit('open', '探索这个念头', 'ai', true)"><span class="rd-button-content">和写作伙伴聊聊 <PreviewIcon name="forward"/></span></button></div></section></div>
    </template>
    <template v-else-if="page === 'projects'">
      <header class="rd-page-heading"><div><h1>作品档案</h1><p>3 部作品 · 按最近编辑排序</p></div><button class="rd-button primary" @click="editBook(null)"><span class="rd-button-content"><PreviewIcon name="plus"/>新建作品</span></button></header>
      <div class="rd-section-title"><div class="rd-segments" :style="{ '--rd-segments': 3, '--rd-selected': ['正在创作','已完成','已归档'].indexOf(tab === '全部' ? '正在创作' : tab) }"><button v-for="item in ['正在创作','已完成','已归档']" :key="item" :aria-pressed="(tab === '全部' ? '正在创作' : tab) === item" @click="tab = item">{{ item }}</button></div><button class="rd-text-button" @click="emit('navigate', 'import')">导入已有作品 <PreviewIcon name="forward"/></button></div>
      <div class="rd-books"><button v-for="(book, i) in visibleBooks" :key="book" class="rd-book" @click="selectBook(book)"><span class="rd-book-cover" :class="`cover-${i % 3}`"><span class="rd-eyebrow">{{ ['LETTERS FROM THE TIDE','ECHOES OF THE MOUNTAINS','A SUNDAY UNIVERSE'][i] }}</span><strong>{{ book }}</strong><span class="rd-book-art"/><small>林间 / 著</small></span><strong>{{ book }}</strong><span>{{ ['奇幻 · 6 章 · 今天编辑','文学 · 12 章 · 昨天编辑','短篇集 · 3 章 · 3 天前'][i] }}</span></button><button class="rd-book rd-book-new" @click="editBook(null)"><span>＋</span><strong>下一个故事</strong><small>灵感便笺</small></button></div>
      <div v-if="!visibleBooks.length" class="rd-dense-empty"><h2>这里还没有作品</h2><p>调整搜索，或开始下一个故事。</p></div>
      <label class="rd-field">按名称查找作品<input v-model="query" placeholder="作品名称"/></label>
      <section v-if="activeBook || editingBook" class="rd-detail-surface"><div class="rd-detail-heading"><h2>{{ activeBook || '新的作品' }}</h2><button class="rd-icon-button" aria-label="关闭作品资料" @click="activeBook = null; editingBook = false"><PreviewIcon name="close"/></button></div><template v-if="editingBook"><label class="rd-field">作品名称<input v-model="bookName"/></label><label class="rd-field">故事简介<textarea rows="3" placeholder="这个故事，关于什么…"/></label><div class="rd-local-toolbar"><button class="rd-button primary" :disabled="!bookName.trim()" @click="saveBook">保存档案示例</button><button class="rd-button" @click="editingBook = false">取消</button></div></template><template v-else><p>封面与档案仅用于展示；本次预览共用《潮汐来信》的虚构创作内容。</p><div class="rd-local-toolbar"><button class="rd-button primary" @click="emit('navigate', 'writing')">进入示例写作</button><button class="rd-button" @click="editBook(activeBook)">编辑资料</button><button v-if="archivedBooks.includes(activeBook)" class="rd-button" @click="archivedBooks = archivedBooks.filter(book => book !== activeBook); tab = '正在创作'">恢复作品</button><button v-else class="rd-button danger" @click="archiveBook">移入回收区</button></div></template></section>
    </template>
    <template v-else-if="page === 'tasks'">
      <header class="rd-page-heading"><div><h1>创作计划</h1><p>给故事一点方向，也给灵感留些余地。</p></div><button class="rd-button primary" @click="editTask({ name: '', note: '', group: '今天', source: 'writing', done: false })"><span class="rd-button-content"><PreviewIcon name="plus"/>添加计划</span></button></header><div class="rd-task-summary"><span class="rd-color-icon tone-blue"><PreviewIcon name="outline"/></span><div><strong>本周的小目标</strong><p>完成第一部初稿，让主角真正踏上航线。</p></div><span class="rd-badge tone-green">✓ {{ tasks.filter(task => task.done).length }} / {{ tasks.length }} 已完成</span></div>
      <div class="rd-filter-pills"><button v-for="group in ['今天','收件箱','之后','已完成']" :key="group" :aria-pressed="taskGroup === group" @click="taskGroup = group">{{ group }}</button></div><ul class="rd-data-list"><li v-for="task in visibleTasks" :key="task.name"><label class="rd-check-label"><input v-model="task.done" type="checkbox" :aria-label="`完成计划：${task.name}`"/></label><div><strong>{{ task.name }}</strong><small>{{ task.note }}</small></div><button class="rd-text-button" @click="editTask(task)">编辑 →</button><button class="rd-text-button" @click="emit('navigate', task.source)">回到来源 →</button></li></ul><div v-if="!visibleTasks.length" class="rd-dense-empty"><h2>{{ taskGroup === '已完成' ? '每一步完成，都值得留下。' : '给新的想法留一个位置。' }}</h2><p>添加计划，或切换到其他安排。</p></div>
      <form v-if="activeTask" class="rd-detail-surface" @submit.prevent="saveTask"><h2>计划详情</h2><label class="rd-field">计划名称<input v-model="taskDraft.name" required/></label><label class="rd-field">记下想法<textarea v-model="taskDraft.note" rows="3"/></label><div class="rd-form-grid"><label class="rd-field">安排<select v-model="taskDraft.group"><option>今天</option><option>收件箱</option><option>之后</option></select></label><label class="rd-field">日期<input type="date"/></label></div><div class="rd-local-toolbar"><button class="rd-button primary">保存计划示例</button><button type="button" class="rd-button" @click="activeTask = null">取消修改</button></div></form><p class="rd-demonstration">创作计划由作者安排，与写作伙伴的后台任务分开。修改只保留在本次预览。</p>
    </template>

    </template>
    <p v-if="feedback" role="status" class="rd-inline-notice tone-green">{{ feedback }}</p>
  </div></div>
</template>
