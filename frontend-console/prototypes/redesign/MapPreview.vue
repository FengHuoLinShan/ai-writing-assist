<script setup>
import { ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import { vReveal } from './motion.js'
defineProps({ state: { type: String, default: 'normal' } })
const emit = defineEmits(['navigate','open'])
const tabs = ['浏览','图层','地图结构','变更审阅','时点与排演']
const tab = ref('浏览')
const places = ['白沙港','旧灯塔','雾隐岛','北境航线']
const mapPlace = ref('白沙港')
const showPlaces = ref(true)
const showRoutes = ref(true)
const detailsOpen = ref(false)
const query = ref('')
const selectedSource = ref('第一部 · 已确认的海岸资料')
const timepoint = ref(2)
const rehearsal = ref('未开始')
const reviewState = ref('待决定')
const imageState = ref('可用')
const note = ref('白沙港位于北境海西岸。旧灯塔坐落在港口东北方的半岛。')
</script>
<template><div class="rd-page-scroll"><div class="rd-page-inner">

      <header class="rd-page-heading"><div><h1>白沙海岸</h1><p>4 处地点 · 潮汐来信</p></div><button class="rd-button" @click="tab = tab === '图层' ? '浏览' : '图层'"><span class="rd-button-content">图层与标记</span></button></header>

<nav class="rd-detail-tabs" aria-label="地图视图"><button v-for="item in tabs" :key="item" :aria-pressed="tab === item" @click="tab = item">{{ item }}</button></nav>
<div v-if="state === 'loading'" class="rd-dense-empty" role="status"><span class="rd-spinner"/> 正在展开海岸…</div>
<div v-else-if="state === 'empty'" class="rd-dense-empty"><h2>给故事一个发生的地方</h2><p>从地点清单开始，也可以先构思一张地图。</p><button class="rd-button" @click="tab = '地图结构'">查看地点结构样例</button></div>
<template v-else>
<div v-if="state === 'error' || imageState === '加载失败'" class="rd-inline-notice tone-orange"><strong>! 地图图片暂时无法显示</strong><p>地点资料仍然可用。可继续用名称浏览，或稍后重新加载图片。</p><button class="rd-button" @click="imageState = '可用'; tab = '地图结构'">查看地点列表</button></div>
<div v-if="tab === '浏览'" class="rd-local-toolbar"><label class="rd-field">查找地点<input v-model="query" placeholder="白沙港、灯塔、航线…"/></label><button v-for="place in places.filter(name => name.includes(query))" :key="place" class="rd-button" :aria-pressed="mapPlace === place" @click="mapPlace = place">{{ place }}</button></div>
<div v-if="tab === '图层'" class="rd-local-toolbar"><label class="rd-check-label"><input v-model="showPlaces" type="checkbox"/>地点名称与标记</label><label class="rd-check-label"><input v-model="showRoutes" type="checkbox"/>航线与关联</label><label class="rd-field">图片状态演示<select v-model="imageState"><option>可用</option><option>加载失败</option></select></label></div>
<div v-if="tab === '浏览' || tab === '图层' || tab === '时点与排演'" class="rd-map" :class="{ 'rd-hide-routes': !showRoutes }"><svg viewBox="0 0 1000 560" role="img" aria-label="虚构白沙海岸地图，标示白沙港、旧灯塔、雾隐岛与北境航线"><defs><pattern id="rd-map-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="currentColor" stroke-opacity=".09"/></pattern></defs><rect width="1000" height="560" fill="url(#rd-map-grid)"/><path class="rd-map-land" d="M0 0H360L380 80 330 155 380 225 325 310 230 360 280 440 190 560H0ZM1000 0H820L770 100 810 170 750 240 820 335 1000 380ZM630 290q-70 60-20 115t95-10 0-85Z"/><path class="rd-map-contour" d="M20 60L305 45 315 105 285 165 335 225 270 290 160 345 200 420 140 520M45 100L260 90 245 175 290 225 240 265 105 335 140 430M1000 80L850 70 825 120 855 180 800 245 845 300"/><path class="rd-map-route" d="M330 310Q540 480 650 355T780 100"/><text x="450" y="195" class="rd-map-sea-label">北 境 海</text><text x="87" y="245" class="rd-map-land-label">白 沙 海 岸</text><text x="735" y="430" class="rd-map-label">潮 汐 航 线</text></svg><button v-for="(place,i) in places" v-show="showPlaces" :key="place" class="rd-map-marker" :class="[`marker-${i}`, { selected: mapPlace === place }]" :aria-pressed="mapPlace === place" @click="mapPlace = place"><span>{{ ['●','✦','◆','➤'][i] }}</span>{{ place }}</button><span class="rd-map-compass">N<br>↑</span><div v-reveal="mapPlace" class="rd-map-info"><span class="rd-badge tone-teal">地点 · 示例</span><h3>{{ mapPlace }}</h3><p>{{ mapPlace === '白沙港' ? '林舟与沈雁初次相遇的地方。潮水退去时，旧路才会出现。' : '每条航线的尽头，都有一个等待被讲述的故事。' }}</p><button class="rd-text-button" @click="detailsOpen = !detailsOpen">查看地点资料 →</button></div><span class="rd-map-scale">━━━━<br>约 5 海里 · 示意</span></div>

<section v-if="detailsOpen && ['浏览','图层'].includes(tab)" class="rd-detail-surface rd-map-details"><div class="rd-detail-heading"><h2>{{ mapPlace }}</h2><button class="rd-icon-button" aria-label="关闭地点资料" @click="detailsOpen = false"><PreviewIcon name="close"/></button></div><p>{{ note }}</p><span class="rd-badge tone-teal">本章关联地点</span><div class="rd-local-toolbar"><button class="rd-button" @click="emit('navigate', 'writing')">返回本章写作</button><button class="rd-text-button" @click="emit('navigate', 'search')">查找原文证据 →</button></div></section>
<section v-if="tab === '地图结构'" class="rd-detail-workspace"><div class="rd-detail-surface"><div class="rd-detail-heading"><div><span class="rd-eyebrow">地图 / 地点结构</span><h2>一条海岸，四个故事坐标。</h2></div><span class="rd-badge tone-blue">工作稿示例</span></div><div class="rd-table-scroll"><table class="rd-data-table"><thead><tr><th>地点</th><th>所属范围</th><th>关联</th></tr></thead><tbody><tr v-for="place in places" :key="place"><td><button class="rd-text-button" @click="mapPlace = place">{{ place }}</button></td><td>白沙海岸</td><td>{{ place === '旧灯塔' ? '雾隐岛 · 潮汐航线' : '白沙港 · 沿岸道路' }}</td></tr></tbody></table></div><label class="rd-field">{{ mapPlace }} · 地点说明<textarea v-model="note" rows="3"/></label><div class="rd-form-grid"><label class="rd-field">上级地图<select><option>白沙海岸</option><option>北境海全图</option></select></label><label class="rd-field">跨地图关联<select><option>雾隐岛 · 岛屿地图</option><option>北境航线 · 航海图</option></select></label></div><button class="rd-button purple" @click="tab = '变更审阅'">预览结构变更</button></div><aside class="rd-detail-surface"><h2>这张图依据什么</h2><label class="rd-field">资料范围<select v-model="selectedSource"><option>第一部 · 已确认的海岸资料</option><option>当前章 · 地点与行动路线</option></select></label><p>来源与作者选择一同展示。新的地图建议不会自动改写地点。</p><button class="rd-source-link" @click="emit('navigate', 'search')">回看白沙港原文 →</button></aside></section>
<section v-if="tab === '变更审阅'" class="rd-detail-surface"><div class="rd-detail-heading"><div><span class="rd-eyebrow">地图 / 候选变更</span><h2>让地图与故事彼此对应。</h2></div><span class="rd-badge" :class="reviewState === '已采用' ? 'tone-green' : 'tone-purple'">{{ reviewState }} · 演示</span></div><div class="rd-comparison"><section><span class="rd-eyebrow">当前结构</span><h3>白沙港 → 旧灯塔</h3><p>沿岸道路常年可通行。</p></section><section><span class="rd-eyebrow">拟议变更</span><h3>白沙港 ⇢ 旧灯塔</h3><p><mark>道路仅在落潮时出现。</mark>补充潮汐限制与通行时点。</p></section></div><div v-if="state === 'conflict'" class="rd-inline-notice tone-red"><strong>! 地点来源已经变化</strong><p>原文更新后，这份建议不能直接采用。重新查证再决定。</p><button class="rd-button" @click="emit('open', '重新核对地图来源', 'compare', true)">查看来源冲突</button></div><p>采用范围：此处通行关系与说明；不会替换地图图片或其他地点。</p><div class="rd-local-toolbar"><button class="rd-button" @click="reviewState = '保留原结构'">保留原结构</button><button class="rd-button purple" :disabled="state === 'conflict' || reviewState === '已采用'" @click="reviewState = '已采用'">演示采用变更</button><button class="rd-text-button" @click="reviewState = '待决定'">重新查看原始示例</button></div></section>
<section v-if="tab === '时点与排演'" class="rd-detail-surface rd-map-details"><div class="rd-detail-heading"><div><span class="rd-eyebrow">时点 {{ timepoint }} / 6</span><h2>{{ ['清晨','渡船离岸','码头初遇','落潮','灯塔亮起','夜航'][timepoint - 1] }}</h2></div><span class="rd-badge tone-purple">预演，不是正史</span></div><label class="rd-field">选择故事时点<input v-model.number="timepoint" type="range" min="1" max="6"/></label><p>当前位置：{{ mapPlace }}。本次预览只切换时点说明，不自动飞行或缩放地图。</p><div class="rd-local-toolbar"><button class="rd-button purple" @click="rehearsal = '进行中'">演示路线排演</button><button v-if="rehearsal === '进行中'" class="rd-button" @click="rehearsal = '已停止'">停止排演</button><button v-if="rehearsal === '进行中'" class="rd-button" @click="rehearsal = '结果可查看'">演示完成</button><button v-if="rehearsal === '已停止'" class="rd-button" @click="rehearsal = '进行中'">继续示例</button><span class="rd-badge">{{ rehearsal }}</span></div><p v-if="rehearsal === '结果可查看'" class="rd-inline-notice tone-purple">✦ 落潮后的石路只开放一小时。建议两人在灯塔亮起前抵达半岛。</p></section>
<p class="rd-demonstration">虚构地图与地点示例，不请求图片服务、不写入地图资料。键盘可以通过地点列表完成浏览。</p>
</template></div></div></template>
<style>
#redesign-root .rd-hide-routes .rd-map-route{opacity:0}#redesign-root .rd-map-details{margin-top:22px}#redesign-root .rd-map-details .rd-field{margin-top:18px}#redesign-root .rd-map{isolation:isolate}#redesign-root .rd-map-marker{z-index:2}
</style>
