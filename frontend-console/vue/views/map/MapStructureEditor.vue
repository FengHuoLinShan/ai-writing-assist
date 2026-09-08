<template>
  <section class="map-editor" aria-label="空间地图编辑器">
    <header class="map-toolbar">
      <div><strong>空间示意</strong><span class="map-caption">不按比例</span></div>
      <div class="map-actions">
        <button class="btn btn-primary" :disabled="busy || readOnly || incompleteGeometry || (!dirty && revision)" @click="save">保存地图</button>
        <button class="btn btn-sm" :disabled="busy || readOnly || !undoStack.length" @click="undo">撤销</button>
        <button class="btn btn-sm" :disabled="busy || readOnly || !redoStack.length" @click="redo">重做</button>
        <button v-if="!readOnly" class="btn btn-sm" :aria-pressed="focused" @click="focused = !focused">{{ focused ? '展开编辑工具' : '专注看图' }}</button>
        <button v-if="hasReference" class="btn btn-sm" :aria-pressed="referenceOnly" @click="toggleReference">{{ referenceOnly ? '返回空间地图' : '查看图片参考' }}</button>
      </div>
    </header>
    <p role="status" class="map-save-status">{{ saveLabel }}</p>
    <p v-if="error" role="alert" class="map-error">{{ error }}</p>
    <div v-if="backupError && dirty" class="map-warning" role="alert">
      本机备份不可用。请保存到服务端，或下载备份并确认文件已保留后再离开。
      <button class="btn btn-sm" @click="downloadBackup">下载地图备份</button>
    </div>
    <div v-if="recovery" class="map-warning">
      发现未保存的本机编辑。
      <button class="btn btn-sm" @click="restoreBackup">恢复到编辑区</button>
      <button class="btn btn-sm" @click="discardBackup">放弃本机编辑</button>
    </div>
    <div v-if="conflict" class="map-warning">
      服务器已有更新，当前编辑已保留。请先查看差异，再决定使用哪一版。
      <ul><li v-for="line in conflictChanges" :key="line">{{ line }}</li></ul>
      <button class="btn btn-sm" @click="compareServer = !compareServer">{{ compareServer ? '回到我的编辑' : '查看服务器版' }}</button>
      <button class="btn btn-sm" @click="useServer">使用服务器版</button>
      <button class="btn btn-sm" @click="rebaseManually">用我的编辑创建新版</button>
    </div>
    <section v-if="candidates.length && !reader" class="map-candidates" aria-label="空间候选">
      <div v-for="candidate in candidates" :key="candidate.id">
        <span>{{ formatDate(candidate.created_at) }} · 空间候选</span>
        <button class="btn btn-sm" :disabled="busy" @click="viewCandidate(candidate)">查看</button>
        <button class="btn btn-sm" :disabled="busy || dirty" @click="review(candidate, 'adopt')">采用这版</button>
        <button class="btn btn-sm" :disabled="busy" @click="review(candidate, 'reject')">不使用</button>
      </div>
    </section>
    <section v-if="candidateView" class="map-warning" aria-label="候选地图差异">
      <strong>{{ compareCandidateCurrent ? '正在对照已保存地图' : '正在查看空间候选' }}</strong>
      <p>以下变化以当前已保存地图为基准；采用前会再次核对来源与版本。</p>
      <ul v-if="candidateChanges.length"><li v-for="(line, index) in candidateChanges" :key="index">{{ line }}</li></ul><p v-else>与当前地图没有内容变化。</p>
      <button class="btn btn-sm" @click="compareCandidateCurrent = !compareCandidateCurrent">{{ compareCandidateCurrent ? '查看候选地图' : '对照已保存地图' }}</button>
      <button class="btn btn-sm" @click="exitCandidate">返回当前地图</button>
    </section>
    <div class="map-reader">
      <label>阅读预览：进入第 <input v-model.number="readerChapter" aria-label="阅读预览章节" type="number" min="1" max="100000" /> 章时</label>
      <button class="btn btn-sm" :disabled="busy || !revision || dirty" @click="previewReader">{{ reader ? '更新阅读预览' : '预览读者所见' }}</button>
      <button v-if="reader" class="btn btn-sm" @click="exitReader">回到作者视图</button>
      <span v-if="reader">仅显示该章开始前可公开的内容，位置保持不变。</span>
    </div>
    <template v-if="!referenceOnly">
      <div class="map-canvas-controls">
        <label>缩放 <input v-model.number="zoom" aria-label="空间地图缩放" type="range" min="60" max="200" step="10" /></label>
        <button class="btn btn-sm" @click="zoom = 100">适合画布</button>
        <span>● 地点  ━ 河流  ┄ 道路  ▱ 区域</span>
      </div>
      <div class="map-locator">
        <label>查找地图内容<input v-model="mapQuery" class="form-input" type="search" placeholder="地点、道路或区域名称" /></label>
        <div v-if="mapQuery.trim()" class="map-actions"><button v-for="feature in matchingFeatures" :key="feature.id" class="btn btn-sm" @click="locateFeature(feature.id)">{{ feature.label }}{{ feature.points.length ? '' : '（待定位）' }}</button><span v-if="!matchingFeatures.length" role="status">当前地图没有匹配内容。</span></div>
        <p v-if="locatorMessage" role="status" class="map-caption">{{ locatorMessage }}</p>
      </div>
      <div class="map-scroll">
        <svg ref="canvas" class="map-canvas" :style="{ width: zoom + '%' }" :viewBox="[bounds.x, bounds.y, bounds.width, bounds.height].join(' ')" role="group" aria-label="空间地图画布" @click.self="placePoint" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag">
          <rect :x="bounds.x" :y="bounds.y" :width="bounds.width" :height="bounds.height" class="map-paper" @click="placePoint" />
          <image v-for="layer in backgrounds" :key="layer.page_id" :href="imageUrls[imageKey(layer.page_id)]" width="1" height="1" preserveAspectRatio="none" :transform="'matrix(' + layer.transform.join(' ') + ')'" :opacity="layer.opacity" pointer-events="none" />
          <g v-for="feature in paintedFeatures" :key="feature.id" :data-feature-id="feature.id" :class="['map-feature', 'map-kind-' + feature.kind, { selected: selectedId === feature.id }]" role="button" tabindex="0" :aria-label="feature.label" @click.stop="selectFeature(feature.id)" @keydown.enter.prevent="selectFeature(feature.id)" @keydown.space.prevent="selectFeature(feature.id)" @keydown="moveByKey($event, feature)">
            <polygon v-if="feature.kind === 'area'" :points="pointsAttribute(feature.points)" :fill-opacity="backgrounds.length ? 0.12 : 0.6" />
            <polyline v-else-if="['road', 'river'].includes(feature.kind)" :points="pointsAttribute(feature.points)" />
            <circle v-else :cx="feature.points[0].x" :cy="feature.points[0].y" :r="7 * mapUnit" @pointerdown.stop="startDrag($event, feature, 0)" />
            <circle v-if="['location', 'landmark'].includes(feature.kind)" :cx="feature.points[0].x" :cy="feature.points[0].y" :r="22 * mapUnit" class="map-hit" @pointerdown.stop="startDrag($event, feature, 0)" />
            <text v-if="labelPositions[feature.id]" :x="labelPositions[feature.id].x" :y="labelPositions[feature.id].y" :style="{ fontSize: 14 * mapUnit + 'px' }">{{ feature.label }}</text>
          </g>
          <g v-if="selectedFeature && !readOnly && !focused && !selectedFeature.locked">
            <circle v-for="(point, index) in selectedFeature.points" :key="index" :cx="point.x" :cy="point.y" r="7" class="map-handle" @pointerdown.stop="startDrag($event, selectedFeature, index)" @click.stop="selectedVertex = index" />
          </g>
        </svg>
      </div>
      <p v-if="!displayDocument.features.length" class="map-caption">{{ reader ? '这个阅读进度暂无可展示的地图内容。' : '先加入已有地点，或添加标记。已知道路和区域可以用折线与轮廓表示。' }}</p>
      <p v-if="placing && !readOnly" role="status">请点击画布{{ selectedFeature?.kind === 'location' || selectedFeature?.kind === 'landmark' ? '放置地点' : '依次添加控制点' }}。<button class="btn btn-sm" @click="finishDrawing">结束绘制</button></p>
    </template>
    <div v-if="!readOnly && !referenceOnly && !focused" class="map-edit-grid">
      <div>
        <details open>
          <summary>地点与绘制</summary>
          <form class="map-inline-form" @submit.prevent="searchLocations"><label>查找已采用地点<input v-model="searchQuery" class="form-input" placeholder="输入地点名称" /></label><button class="btn btn-sm" :disabled="busy">查找</button></form>
          <div class="map-location-list">
            <label v-for="location in locations" :key="location.id"><input v-model="selectedLocationIds" :value="location.id" type="checkbox" :disabled="busy || (!selectedLocationIds.includes(location.id) && selectedLocationIds.length >= 20)" />{{ location.name }}</label>
          </div>
          <div class="map-actions"><button class="btn btn-sm" :disabled="busy || !selectedLocationIds.length" @click="addLocations">加入地图</button><button class="btn btn-sm" :disabled="busy || taskRunning || !selectedLocationIds.length || dirty" @click="generate">{{ taskRunning ? '正在整理空间资料…' : '用这些地点生成空间关系' }}</button></div>
          <p v-if="taskStatus === 'failed'" role="alert">空间整理未完成。已保存的地图仍可使用，可以重新整理或手动编辑。</p>
          <p v-if="dirty" class="map-caption">生成前请先保存当前编辑。</p>
          <form class="map-inline-form" @submit.prevent="addFeature">
            <label>标记名称<input v-model="newLabel" class="form-input" maxlength="200" /></label>
            <label>类型<select v-model="newKind" class="form-select"><option value="location">地点</option><option value="landmark">地标</option><option value="road">道路</option><option value="river">河流</option><option value="area">区域轮廓</option></select></label>
            <button class="btn btn-sm" :disabled="busy || !newLabel.trim()">添加并绘制</button>
          </form>
          <label>选中内容<select :value="selectedId" class="form-select" @change="selectFeature($event.target.value)"><option value="">请选择</option><option v-for="feature in doc.features" :key="feature.id" :value="feature.id">{{ feature.label }}{{ feature.points.length ? '' : '（待定位）' }}</option></select></label>
          <button class="btn btn-sm" :disabled="busy || !doc.features.length" @click="autoLayout">布置尚未定位的地点</button>
        </details>
        <details>
          <summary>空间关系</summary>
          <form class="map-inline-form" @submit.prevent="addConstraint">
            <label>地点<select v-model="relation.subject" class="form-select"><option value="">请选择</option><option v-for="f in doc.features" :key="f.id" :value="f.id">{{ f.label }}</option></select></label>
            <label>关系<select v-model="relation.relation" class="form-select"><option v-for="(label, key) in relationLabels" :key="key" :value="key">{{ label }}</option></select></label>
            <label>另一地点<select v-model="relation.target" class="form-select"><option value="">请选择</option><option v-for="f in doc.features" :key="f.id" :value="f.id">{{ f.label }}</option></select></label>
            <button class="btn btn-sm" :disabled="busy || !relation.subject || !relation.target">添加关系</button>
          </form>
          <ul><li v-for="constraint in doc.constraints" :key="constraint.id">{{ featureLabel(constraint.subject) }} · {{ relationLabels[constraint.relation] }} · {{ featureLabel(constraint.target) }} <button class="btn btn-sm" @click="removeConstraint(constraint.id)">移出</button></li></ul>
        </details>
      </div>
      <aside v-if="selectedFeature" class="map-inspector" aria-label="地图内容详情">
        <label>显示名称<input :value="selectedFeature.label" class="form-input" maxlength="200" @input="changeFeature('label', $event.target.value)" /></label>
        <label><input :checked="selectedFeature.locked" type="checkbox" @change="changeFeature('locked', $event.target.checked)" />锁定位置</label>
        <div class="map-actions"><button class="btn btn-sm" :disabled="selectedFeature.locked" @click="placing = true">点击画布定位／添点</button><button class="btn btn-sm" :disabled="selectedFeature.locked || !selectedFeature.points.length" @click="removePoint">移出最后一个点</button></div>
        <p class="map-caption">可拖动控制点，或用下面的方向按钮微调；键盘方向键也可移动。</p>
        <label v-if="selectedFeature.points.length > 1">控制点<select v-model.number="selectedVertex" class="form-select"><option v-for="(_, index) in selectedFeature.points" :key="index" :value="index">{{ index + 1 }}</option></select></label>
        <div class="map-actions"><button class="btn btn-sm" aria-label="向左移动" @click="nudge(-10, 0)">←</button><button class="btn btn-sm" aria-label="向上移动" @click="nudge(0, -10)">↑</button><button class="btn btn-sm" aria-label="向下移动" @click="nudge(0, 10)">↓</button><button class="btn btn-sm" aria-label="向右移动" @click="nudge(10, 0)">→</button></div>
        <label>最早在第几章开始时展示<input :value="selectedFeature.reader_from_chapter || ''" type="number" min="1" max="100000" class="form-input" placeholder="留空：仅作者可见" @change="changeFeature('reader_from_chapter', $event.target.value ? Number($event.target.value) : null)" /></label>
        <label>补充说明<textarea :value="selectedFeature.note" class="form-textarea" maxlength="1000" @input="changeFeature('note', $event.target.value)" /></label>
        <label>打开子图<select :value="selectedFeature.target_node_id || ''" class="form-select" @change="changeFeature('target_node_id', $event.target.value || null)"><option value="">不跳转</option><option v-for="target in childChoices" :key="target.id" :value="target.id">{{ target.title }}</option></select></label>
        <div class="map-actions"><button v-if="selectedFeature.target_node_id" class="btn btn-sm" @click="emit('open-node', selectedFeature.target_node_id)">进入子图</button><button v-if="node.level === 'region' && selectedFeature.kind === 'location' && !selectedFeature.target_node_id" class="btn btn-sm" :disabled="busy" @click="createChild">为此地点创建城市图</button><button v-if="selectedFeature.entity_id" class="btn btn-sm" @click="openEntity">查看世界资料</button><button class="btn btn-sm" @click="removeFeature">移出地图</button></div>
        <p v-for="(source, index) in selectedFeature.sources" :key="index">{{ source.quote || '保留了已确认资料的引用' }}<button v-if="source.kind === 'source_range'" class="btn btn-sm" @click="openSourceChapter(source)">打开第 {{ source.source_ref.chapter_index }} 章</button></p>
        <img v-for="layer in selectedIllustrations" :key="layer.page_id" :src="imageUrls[imageKey(layer.page_id)]" alt="地点配图" class="map-detail-image" />
      </aside>
    </div>
    <aside v-if="(reader || focused || candidateView) && displayedFeature && !referenceOnly" class="map-inspector" :aria-label="reader ? '读者地点详情' : '地图地点详情'">
      <strong>{{ displayedFeature.label }}</strong>
      <template v-if="!reader"><p v-if="displayedFeature.note">{{ displayedFeature.note }}</p><p v-for="(source, index) in displayedFeature.sources" :key="index">{{ source.quote }}<button v-if="source.kind === 'source_range'" class="btn btn-sm" @click="openSourceChapter(source)">打开第 {{ source.source_ref.chapter_index }} 章</button></p><button v-if="!candidateView && displayedFeature.target_node_id" class="btn btn-sm" @click="emit('open-node', displayedFeature.target_node_id)">进入子图</button></template>
      <img v-for="layer in candidateView ? [] : selectedIllustrations" :key="layer.page_id" :src="imageUrls[imageKey(layer.page_id)]" class="map-detail-image" :alt="reader ? '可公开的地点配图' : '地点配图'" />
    </aside>
    <details v-if="!readOnly && !focused && images.length" class="map-image-controls">
      <summary>底图与地点配图</summary>
      <div class="map-inline-form">
        <label>已采用图片<select v-model="imageForm.page_id" class="form-select" @change="loadSelectedImage"><option value="">请选择</option><option v-for="page in images" :key="page.id" :value="page.id">{{ page.title }} · {{ formatDate(page.created_at) }}</option></select></label>
        <label>用途<select v-model="imageForm.role" class="form-select"><option value="illustration">地点配图</option><option value="background">地图底图</option></select></label>
        <label v-if="imageForm.role === 'illustration'">关联地点<select v-model="imageForm.feature_id" class="form-select"><option value="">整张地图</option><option v-for="feature in doc.features" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select></label>
      </div>
      <template v-if="imageForm.role === 'background' && imageForm.page_id">
        <p>依次选择三个不共线的地点，并点击图片中对应的位置。校准只调整图片，不改变地图地点。</p>
        <div class="map-inline-form"><label v-for="(anchor, index) in imageForm.anchors" :key="index">锚点 {{ index + 1 }}<select v-model="anchor.feature_id" class="form-select" @focus="anchorIndex = index"><option value="">请选择地点</option><option v-for="feature in anchorFeatures" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select><button class="btn btn-sm" :aria-pressed="anchorIndex === index" @click="anchorIndex = index">标记第 {{ index + 1 }} 点</button></label></div>
        <div class="map-calibration" @click="markImageAnchor">
          <img v-if="imageUrls[imageKey(imageForm.page_id)]" :src="imageUrls[imageKey(imageForm.page_id)]" alt="点击图片标记校准锚点" />
          <span v-for="(anchor, index) in imageForm.anchors" :key="index" :style="{ left: anchor.image_x * 100 + '%', top: anchor.image_y * 100 + '%' }">{{ index + 1 }}</span>
        </div>
        <div class="map-inline-form"><label v-for="(anchor, index) in imageForm.anchors" :key="index">锚点 {{ index + 1 }} 的图片位置（比例）<input v-model.number="anchor.image_x" type="number" min="0" max="1" step="0.01" :aria-label="'锚点' + (index + 1) + '横向比例'" /><input v-model.number="anchor.image_y" type="number" min="0" max="1" step="0.01" :aria-label="'锚点' + (index + 1) + '纵向比例'" /></label></div>
        <label>底图透明度<input v-model.number="imageForm.opacity" type="range" min="0.1" max="1" step="0.05" /></label>
      </template>
      <label>已人工核对整张图片，最早在第几章开始时展示<input v-model.number="imageForm.reader_from_chapter" type="number" min="1" max="100000" placeholder="未核对请留空" /></label>
      <button class="btn btn-sm" :disabled="busy || !imageForm.page_id" @click="applyImage">预览图片设置</button>
      <ul><li v-for="placement in doc.images" :key="placement.page_id">{{ imageTitle(placement.page_id) }} · {{ placement.role === 'background' ? '底图' : '配图' }} <strong v-if="imageState(placement) !== 'ready'">{{ imageState(placement) === 'stale' ? '待复核，已退出叠加' : '图片已移出，展示已关闭' }}</strong><button class="btn btn-sm" @click="editImage(placement)">调整／重新校准</button><button class="btn btn-sm" @click="removeImage(placement.page_id)">关闭此展示层</button></li></ul>
      <details v-if="annotations.length || doc.annotation_bindings.length"><summary>绑定原图片标注</summary><ul><li v-for="binding in doc.annotation_bindings" :key="binding.annotation_id">已绑定到 {{ featureLabel(binding.feature_id) }} <button class="btn btn-sm" @click="unbindAnnotation(binding.annotation_id)">解除绑定</button></li></ul><form class="map-inline-form" @submit.prevent="bindAnnotation"><label>原标注<select v-model="annotationId" class="form-select"><option value="">请选择</option><option v-for="annotation in annotations" :key="annotation.id" :value="annotation.id">{{ annotation.label }}</option></select></label><label>地图地点<select v-model="annotationFeatureId" class="form-select"><option value="">请选择</option><option v-for="feature in doc.features" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select></label><button class="btn btn-sm" :disabled="!annotationId || !annotationFeatureId">绑定</button></form></details>
    </details>
    <details v-if="problems.length && !reader" open class="map-warning"><summary>需要核对 {{ problems.length }} 项</summary><ul><li v-for="(problem, index) in problems" :key="index">{{ problem.message }}<button v-if="problem.feature_ids.length" class="btn btn-sm" @click="selectFeature(problem.feature_ids[0])">定位</button></li></ul></details>
    <details v-if="!reader"><summary @click="loadHistory">地图历史</summary><div v-for="item in history" :key="item.id" class="map-history"><span>{{ formatDate(item.created_at) }} · {{ item.status === 'saved' ? '已保存' : item.status === 'candidate' ? '候选' : '未使用' }}</span><button v-if="item.status === 'saved'" class="btn btn-sm" :disabled="busy || dirty || item.id === revision?.id" @click="review(item, 'restore')">恢复为新版本</button></div></details>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getConfirm, getRouter } from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { ACCOUNT_MARKER_KEY } from "../../../shared/accountStorage.js"
import { copyMap, emptyMap, geometrySignature, mapBounds, mapChanges, pointsAttribute, removeMapFeature } from "./mapStructureEditor.js"

const props = defineProps({ projectId: { type: String, required: true }, node: { type: Object, required: true }, images: { type: Array, default: () => [] }, knownNodes: { type: Array, default: () => [] }, hasReference: Boolean, reviewImageId: { type: String, default: "" } })
const emit = defineEmits(["saved", "open-node", "reference-visible", "state"])
const api = getApi(), confirm = getConfirm()
const doc = ref(emptyMap()), revision = ref(null), serverRevision = ref(null), baseline = ref(JSON.stringify(emptyMap()))
const candidates = ref([]), candidateView = ref(null), history = ref([]), imageLayers = ref([]), checkedGeometry = ref("")
const loading = ref(false), saving = ref(false), error = ref(""), problems = ref([]), initialized = ref(false)
const recovery = ref(null), backupError = ref(false), backedUp = ref(false), conflict = ref(false), compareServer = ref(false)
const undoStack = ref([]), redoStack = ref([]), selectedId = ref(""), selectedVertex = ref(0), placing = ref(false)
const canvas = ref(null), canvasWidth = ref(700), zoom = ref(100), referenceOnly = ref(false), dragBounds = ref(null)
const focused = ref(false), mapQuery = ref(""), locatorMessage = ref(""), compareCandidateCurrent = ref(false)
const searchQuery = ref(""), locations = ref([]), selectedLocationIds = ref([]), newLabel = ref(""), newKind = ref("location")
const taskId = ref(null), taskStatus = ref(null), reader = ref(null), readerChapter = ref(1)
const imageUrls = reactive({}), anchorIndex = ref(0), annotationId = ref(""), annotationFeatureId = ref("")
const imageForm = reactive({ page_id: "", role: "illustration", feature_id: "", opacity: 0.65, anchors: [{ feature_id: "", image_x: 0.1, image_y: 0.1 }, { feature_id: "", image_x: 0.8, image_y: 0.1 }, { feature_id: "", image_x: 0.1, image_y: 0.8 }], reader_from_chapter: "" })
const relation = reactive({ subject: "", relation: "north", target: "" })
const relationLabels = { inside: "位于区域内", north: "在北侧", south: "在南侧", east: "在东侧", west: "在西侧", northeast: "在东北", northwest: "在西北", southeast: "在东南", southwest: "在西南", adjacent: "相邻", connects: "有已知道路连接", passes_through: "路线经过" }
const imageRequests = new Map()
let resizeObserver = null
let epoch = 0, alive = true, installing = false, backupTimer = null, pollTimer = null, drag = null, downloaded = false
const dirty = computed(() => JSON.stringify(doc.value) !== baseline.value)
const busy = computed(() => loading.value || saving.value)
const taskRunning = computed(() => ["pending", "running"].includes(taskStatus.value))
const incompleteGeometry = computed(() => doc.value.features.some(feature => feature.points.length > 0 && feature.points.length < (feature.kind === 'area' ? 3 : ['road', 'river'].includes(feature.kind) ? 2 : 1)))
const readOnly = computed(() => Boolean(reader.value || candidateView.value || compareServer.value))
const displayDocument = computed(() => reader.value ? { features: reader.value.features } : candidateView.value ? (compareCandidateCurrent.value ? revision.value?.document || emptyMap() : candidateView.value.document) : (compareServer.value && serverRevision.value ? serverRevision.value.document : doc.value))
const displayedFeature = computed(() => displayDocument.value.features.find(feature => feature.id === selectedId.value))
const matchingFeatures = computed(() => displayDocument.value.features.filter(feature => feature.label.toLocaleLowerCase().includes(mapQuery.value.trim().toLocaleLowerCase())))
const candidateChanges = computed(() => candidateView.value ? mapChanges(revision.value?.document || emptyMap(), candidateView.value.document) : [])
const bounds = computed(() => dragBounds.value || mapBounds(displayDocument.value.features))
const paintRank = feature => feature.kind === 'area' ? 0 : ['road', 'river'].includes(feature.kind) ? 1 : 2
const paintedFeatures = computed(() => [...displayDocument.value.features].filter(f => f.points.length).sort((a, b) => paintRank(a) - paintRank(b)))
const mapUnit = computed(() => bounds.value.width / Math.max(320, canvasWidth.value))
const labelPositions = computed(() => {
  const placed = [], result = {}, unit = mapUnit.value
  for (const feature of [...paintedFeatures.value].sort((a, b) => paintRank(b) - paintRank(a))) {
    const point = ['road', 'river'].includes(feature.kind) ? feature.points[Math.floor(feature.points.length / 2)] : feature.points[0]
    const width = [...feature.label].length * 14 * unit, height = 20 * unit
    for (const [dx, dy] of [[14, -13], [14, 23], [-14, -13], [-14, 23]]) {
      const x = point.x + dx*unit - (dx < 0 ? width : 0), y = point.y + dy*unit
      const box = { x, y: y-height, width, height }
      if (placed.some(other => box.x < other.x+other.width && box.x+width > other.x && box.y < other.y+other.height && box.y+height > other.y)) continue
      result[feature.id] = { x, y }; placed.push(box); break
    }
  }
  return result
})
const selectedFeature = computed(() => doc.value.features.find(f => f.id === selectedId.value))
const anchorFeatures = computed(() => doc.value.features.filter(f => ["location", "landmark"].includes(f.kind) && f.points.length === 1))
const childChoices = computed(() => props.knownNodes.filter(node => node.id !== props.node.id && node.parent_id === props.node.id))
const annotations = computed(() => props.images.flatMap(page => page.annotations || []))
const conflictChanges = computed(() => serverRevision.value ? mapChanges(serverRevision.value.document, doc.value) : [])
const saveLabel = computed(() => saving.value ? "正在处理地图操作…" : dirty.value ? (backedUp.value ? "未保存到服务端 · 当前编辑已在本机备份" : "有未保存修改") : revision.value ? "已保存到服务端" : "空间结构尚未保存")
const backgrounds = computed(() => {
  if (candidateView.value || compareServer.value) return []
  const layers = reader.value ? reader.value.images : imageLayers.value
  return layers.filter(layer => layer.role === "background" && layer.transform && (reader.value || imageState(doc.value.images.find(i => i.page_id === layer.page_id)) === "ready")).map(layer => ({ ...layer, opacity: reader.value ? layer.opacity : doc.value.images.find(i => i.page_id === layer.page_id)?.opacity ?? layer.opacity }))
})
const selectedIllustrations = computed(() => (reader.value ? reader.value.images : imageLayers.value).filter(layer => layer.role === "illustration" && (!layer.feature_id || layer.feature_id === selectedId.value) && (reader.value || layer.state === "ready")))

function imageKey(pageId) { return (reader.value ? "reader:" + readerChapter.value + ":" : "author:") + pageId }
function imageTitle(pageId) { return props.images.find(page => page.id === pageId)?.title || "已有图片" }
function imageState(placement) {
  if (!placement) return "unavailable"
  if (placement.role === "background" && checkedGeometry.value !== geometrySignature(doc.value)) return "stale"
  return imageLayers.value.find(layer => layer.page_id === placement.page_id)?.state || "unavailable"
}
function featureLabel(id) { return doc.value.features.find(f => f.id === id)?.label || "待核对地点" }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "已有图片" }
let backupAccount = null
try { backupAccount = localStorage.getItem(ACCOUNT_MARKER_KEY) } catch { /* Saving remains available. */ }
function backupKey() {
  if (localStorage.getItem(ACCOUNT_MARKER_KEY) !== backupAccount) throw new Error('account changed')
  return "novel_map_draft:" + (backupAccount || "local") + ":" + props.projectId + ":" + props.node.id
}
function persistDraft() {
  clearTimeout(backupTimer)
  if (!dirty.value) return
  try {
    const value = JSON.stringify({ base_revision_id: revision.value?.id || null, document: doc.value })
    localStorage.setItem(backupKey(), value)
    if (localStorage.getItem(backupKey()) !== value) throw new Error("backup verification failed")
    backedUp.value = true; backupError.value = false
  } catch { backedUp.value = false; backupError.value = true }
}
function clearBackup() { try { localStorage.removeItem(backupKey()) } catch { /* Server save remains authoritative. */ } }
function install(value) {
  installing = true
  revision.value = value; doc.value = copyMap(value?.document || emptyMap())
  baseline.value = JSON.stringify(doc.value); checkedGeometry.value = geometrySignature(doc.value)
  problems.value = value?.problems || []; undoStack.value = []; redoStack.value = []
  selectedId.value = doc.value.features[0]?.id || ""; candidateView.value = null; reader.value = null
  installing = false
}
function mutate(change) {
  if (busy.value || readOnly.value || focused.value) return
  const previous = JSON.stringify(doc.value)
  change(doc.value)
  if (JSON.stringify(doc.value) === previous) return
  undoStack.value = [...undoStack.value.slice(-19), previous]; redoStack.value = []
}
function undo() { if (!undoStack.value.length) return; redoStack.value.push(JSON.stringify(doc.value)); doc.value = JSON.parse(undoStack.value.pop()) }
function redo() { if (!redoStack.value.length) return; undoStack.value.push(JSON.stringify(doc.value)); doc.value = JSON.parse(redoStack.value.pop()) }
function selectFeature(id) { selectedId.value = id; selectedVertex.value = 0 }
async function locateFeature(id) {
  selectFeature(id)
  locatorMessage.value = displayedFeature.value?.points.length ? '' : '这个地点尚未定位，可在编辑工具中放置。'
  await nextTick()
  const element = [...(canvas.value?.querySelectorAll('.map-feature') || [])].find(item => item.dataset.featureId === id)
  element?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  element?.focus?.({ preventScroll: true })
}
function changeFeature(key, value) { if (selectedFeature.value) mutate(() => { selectedFeature.value[key] = value }) }
function toggleReference() { referenceOnly.value = !referenceOnly.value; emit("reference-visible", referenceOnly.value) }
function pointFromEvent(event) {
  const svg = canvas.value, matrix = svg?.getScreenCTM()
  if (!matrix) return null
  const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY
  const mapped = point.matrixTransform(matrix.inverse())
  return { x: Math.round(Math.max(-99000, Math.min(99000, mapped.x))), y: Math.round(Math.max(-99000, Math.min(99000, mapped.y))) }
}
function placePoint(event) {
  if (!placing.value || !selectedFeature.value || selectedFeature.value.locked || readOnly.value) return
  const point = pointFromEvent(event); if (!point) return
  mutate(() => { if (["location", "landmark"].includes(selectedFeature.value.kind)) { selectedFeature.value.points = [point]; placing.value = false } else selectedFeature.value.points.push(point) })
}
function finishDrawing() {
  const feature = selectedFeature.value
  const minimum = feature?.kind === "area" ? 3 : ["road", "river"].includes(feature?.kind) ? 2 : 1
  if (feature && feature.points.length > 0 && feature.points.length < minimum) { error.value = "控制点不足，请继续绘制或移出该图元。"; return }
  placing.value = false
}
function startDrag(event, feature, index) {
  if (busy.value || readOnly.value || focused.value || feature.locked || event.button !== 0) return
  selectedId.value = feature.id; selectedVertex.value = index
  drag = { id: feature.id, index, before: JSON.stringify(doc.value) }; dragBounds.value = bounds.value
  event.target.setPointerCapture?.(event.pointerId)
}
function moveDrag(event) {
  if (!drag) return
  const point = pointFromEvent(event), feature = doc.value.features.find(f => f.id === drag.id)
  if (point && feature) feature.points[drag.index] = point
}
function endDrag() {
  if (!drag) return
  if (drag.before !== JSON.stringify(doc.value)) { undoStack.value = [...undoStack.value.slice(-19), drag.before]; redoStack.value = [] }
  drag = null; dragBounds.value = null
}
function nudge(x, y) {
  const feature = selectedFeature.value, point = feature?.points[selectedVertex.value]
  if (!point || feature.locked) return
  mutate(() => { point.x = Math.max(-99000, Math.min(99000, point.x + x)); point.y = Math.max(-99000, Math.min(99000, point.y + y)) })
}
function moveByKey(event, feature) {
  const delta = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] }[event.key]
  if (!delta || readOnly.value || focused.value) return
  event.preventDefault(); selectedId.value = feature.id; nudge(...delta)
}
function removePoint() {
  if (!selectedFeature.value || selectedFeature.value.locked) return
  mutate(() => { selectedFeature.value.points.pop(); placing.value = true })
}
function addFeature() {
  const id = "mark:" + crypto.randomUUID()
  mutate(document => document.features.push({ id, kind: newKind.value, label: newLabel.value.trim(), entity_id: null, target_node_id: null, points: [], locked: false, sources: [], depends_on: [], note: "", reader_from_chapter: null }))
  selectedId.value = id; newLabel.value = ""; placing.value = true
}
function removeFeature() {
  const feature = selectedFeature.value
  if (!feature || !confirm("从此地图移出“" + feature.label + "”及相关约束？关联图形需要重新定位，世界资料仍会保留。")) return
  mutate(document => removeMapFeature(document, feature.id)); selectedId.value = ""
}
function addConstraint() {
  mutate(document => document.constraints.push({ id: "relation:" + crypto.randomUUID(), subject: relation.subject, relation: relation.relation, target: relation.target, via: [], sources: [] }))
}
function removeConstraint(id) { mutate(document => { document.constraints = document.constraints.filter(c => c.id !== id) }) }
function unbindAnnotation(id) { mutate(document => { document.annotation_bindings = document.annotation_bindings.filter(binding => binding.annotation_id !== id) }) }
function bindAnnotation() {
  mutate(document => { document.annotation_bindings = document.annotation_bindings.filter(b => b.annotation_id !== annotationId.value); document.annotation_bindings.push({ annotation_id: annotationId.value, feature_id: annotationFeatureId.value }) })
}
async function searchLocations() {
  try {
    const result = await api.world.listEntities({ novel_id: props.projectId, entity_type: "location", status: "canonical", q: searchQuery.value, limit: 20 })
    if (!alive) return
    locations.value = (Array.isArray(result) ? result : result.items || []).filter(item => item.status === "canonical")
    selectedLocationIds.value = selectedLocationIds.value.filter(id => locations.value.some(item => item.id === id))
  } catch (err) { error.value = err.message || "地点读取失败，请重试" }
}
function addLocations() {
  mutate(document => { for (const location of locations.value.filter(item => selectedLocationIds.value.includes(item.id))) if (!document.features.some(f => f.entity_id === location.id)) document.features.push({ id: "loc:" + location.id, kind: "location", label: location.name, entity_id: location.id, target_node_id: null, points: [], locked: false, sources: [], depends_on: [], note: "", reader_from_chapter: null }) })
}
async function load(initial = false) {
  const token = ++epoch
  if (initial) loading.value = true
  try {
    const result = await api.world.getNodeMap(props.projectId, props.node.id)
    if (!alive || token !== epoch) return
    serverRevision.value = result.revision; candidates.value = result.candidates; imageLayers.value = result.image_layers || []
    taskId.value = result.task_id; taskStatus.value = result.task_status
    if (!initialized.value) {
      install(result.revision); initialized.value = true
      try { recovery.value = JSON.parse(localStorage.getItem(backupKey()) || "null") } catch { backupError.value = true }
      if (recovery.value && JSON.stringify(recovery.value.document) === baseline.value) recovery.value = null
    } else if (!dirty.value && !candidateView.value && revision.value?.id !== result.revision?.id) install(result.revision)
    if (taskRunning.value) { clearTimeout(pollTimer); pollTimer = setTimeout(() => load(), 2500) }
    await loadLayerImages()
  } catch (err) { if (alive && token === epoch) error.value = err.message || "地图读取失败" }
  finally { if (alive && token === epoch) loading.value = false }
}
async function save() {
  if (busy.value || readOnly.value) return
  persistDraft(); saving.value = true; error.value = ""
  const requestNode = props.node.id, requestProject = props.projectId
  try {
    const value = await api.world.saveMapRevision(props.projectId, props.node.id, { base_revision_id: revision.value?.id || null, document: copyMap(doc.value) })
    if (!alive || requestNode !== props.node.id || requestProject !== props.projectId) return
    install(value); serverRevision.value = value; clearBackup(); recovery.value = null; conflict.value = false
    emit("saved"); await load()
  } catch (err) {
    if (!alive) return
    error.value = err.message || "保存失败，当前编辑仍保留"
    persistDraft()
    if (err.status === 409 || err.statusCode === 409 || /更新|版本|409/.test(error.value)) { conflict.value = true; await load() }
  } finally { if (alive) saving.value = false }
}
async function autoLayout() {
  if (busy.value) return
  error.value = ""
  const original = JSON.stringify(doc.value)
  try {
    const result = await api.world.layoutMap(props.projectId, props.node.id, { base_revision_id: revision.value?.id || null, document: copyMap(doc.value) })
    if (!alive) return
    if (JSON.stringify(doc.value) !== original) { error.value = "返回预览时已有新编辑，请重新请求预览。"; return }
    mutate(() => { doc.value = result.document }); checkedGeometry.value = geometrySignature(doc.value)
    problems.value = result.problems; imageLayers.value = result.image_layers || []; await loadLayerImages()
  } catch (err) { error.value = err.message || "布局暂时无法完成，当前编辑仍保留" }
}
async function generate() {
  if (dirty.value || busy.value || taskRunning.value) return
  saving.value = true; error.value = ""
  try {
    const confirmation = await confirmAiReference({ novel_id: props.projectId, action: "world.map_atlas.structure", scope: "full", task: "整理地图空间关系", entity_ids: selectedLocationIds.value, include_pending_objects: false, budget_tokens: 12000 })
    if (!alive) return
    const result = await api.world.generateMapStructure(props.projectId, props.node.id, { operation_id: crypto.randomUUID(), base_revision_id: revision.value?.id || null, context_confirmation_id: confirmation.id, location_ids: [...selectedLocationIds.value] })
    if (!alive) return
    taskId.value = result.task_id; taskStatus.value = result.status; await load()
  } catch (err) { if (err.message !== "已取消 AI 参考资料确认") error.value = err.message || "空间整理暂时不可用" }
  finally { if (alive) saving.value = false }
}
function viewCandidate(value) { compareServer.value = false; if (dirty.value && !confirm("查看候选时会保留当前编辑，是否继续？")) return; candidateView.value = value; compareCandidateCurrent.value = false; reader.value = null; referenceOnly.value = false; emit("reference-visible", false); problems.value = value.problems }
function exitCandidate() { candidateView.value = null; compareCandidateCurrent.value = false; problems.value = revision.value?.problems || [] }
async function review(value, action) {
  if (busy.value || dirty.value) return
  if (action === "restore" && !confirm("将历史地图恢复为新版本？当前版本仍保留在历史中。")) return
  if (action === "reject" && !confirm("不使用这个空间候选？已保存地图不会受到影响。")) return
  saving.value = true
  try {
    const result = await api.world.reviewMapRevision(props.projectId, props.node.id, value.id, { base_revision_id: revision.value?.id || null, action })
    if (!alive) return
    if (action !== "reject") { install(result); serverRevision.value = result; clearBackup(); emit("saved") }
    candidateView.value = null; await load()
  } catch (err) { error.value = err.message || "版本操作失败，当前地图仍保留" }
  finally { if (alive) saving.value = false }
}
async function loadHistory() { try { history.value = await api.world.listMapRevisions(props.projectId, props.node.id) } catch (err) { error.value = err.message || "历史读取失败" } }
function restoreBackup() {
  if (!recovery.value) return
  if (!Array.isArray(recovery.value.document?.features) || !Array.isArray(recovery.value.document?.constraints) || !Array.isArray(recovery.value.document?.images)) { error.value = "本机备份格式已损坏，服务器版本仍然保留。"; return }
  doc.value = copyMap(recovery.value.document)
  if (recovery.value.base_revision_id !== (revision.value?.id || null)) {
    revision.value = { ...(revision.value || {}), id: recovery.value.base_revision_id }; conflict.value = true
  }
  recovery.value = null; persistDraft()
}
function discardBackup() { if (confirm("放弃这份未保存的本机编辑？")) { clearBackup(); recovery.value = null } }
function useServer() { if (confirm("使用服务器版？当前编辑将从工作区移出。")) { install(serverRevision.value); clearBackup(); conflict.value = false; compareServer.value = false } }
function rebaseManually() {
  if (!confirm("确认已比较服务器版，并用当前编辑创建一个新版？")) return
  revision.value = serverRevision.value; conflict.value = false; compareServer.value = false; persistDraft()
}
async function previewReader() {
  if (dirty.value || !revision.value) return
  try {
    const value = await api.world.previewReaderMap(props.projectId, props.node.id, readerChapter.value, revision.value.id)
    if (!alive) return
    for (const key of Object.keys(imageUrls).filter(key => key.startsWith("reader:"))) { URL.revokeObjectURL(imageUrls[key]); delete imageUrls[key] }
    reader.value = value; candidateView.value = null; referenceOnly.value = false; emit("reference-visible", false); await loadLayerImages()
  } catch (err) { error.value = err.message || "阅读预览暂不可用" }
}
function exitReader() { reader.value = null; loadLayerImages() }
async function loadImage(pageId) {
  const key = imageKey(pageId), isReader = Boolean(reader.value), chapter = readerChapter.value, revId = revision.value?.id
  if (imageUrls[key] || imageRequests.has(key)) return
  const token = {}; imageRequests.set(key, token)
  try {
    const blob = isReader ? await api.world.fetchReaderMapImage(props.projectId, props.node.id, pageId, chapter, revId) : await api.world.fetchMapAtlasImage(props.projectId, pageId)
    if (!alive || isReader !== Boolean(reader.value) || (isReader && chapter !== readerChapter.value)) return
    imageUrls[key] = URL.createObjectURL(blob)
  } catch (err) { if (alive) error.value = err.message || "图片读取失败，可重新选择图片重试" }
  finally { if (imageRequests.get(key) === token) imageRequests.delete(key) }
}
async function loadLayerImages() { await Promise.all((reader.value ? reader.value.images : imageLayers.value.filter(layer => layer.state === "ready")).map(layer => loadImage(layer.page_id))) }
async function loadSelectedImage() { if (imageForm.page_id) await loadImage(imageForm.page_id) }
function markImageAnchor(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  imageForm.anchors[anchorIndex.value].image_x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  imageForm.anchors[anchorIndex.value].image_y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
  anchorIndex.value = Math.min(2, anchorIndex.value + 1)
}
async function applyImage() {
  const original = JSON.stringify(doc.value)
  const page = props.images.find(item => item.id === imageForm.page_id)
  const placement = { page_id: imageForm.page_id, role: imageForm.role, feature_id: imageForm.role === "illustration" ? imageForm.feature_id || null : null, opacity: imageForm.opacity, anchors: imageForm.role === "background" ? copyMap(imageForm.anchors) : [], geometry_hash: null, reader_from_chapter: imageForm.reader_from_chapter || null, reader_image_hash: imageForm.reader_from_chapter ? page?.image_hash : null }
  const candidate = copyMap(doc.value)
  candidate.images = candidate.images.filter(item => item.page_id !== placement.page_id && !(placement.role === "background" && item.role === "background")); candidate.images.push(placement)
  try {
    const result = await api.world.layoutMap(props.projectId, props.node.id, { base_revision_id: revision.value?.id || null, document: candidate })
    if (!alive) return
    if (JSON.stringify(doc.value) !== original) { error.value = "返回预览时已有新编辑，请重新请求预览。"; return }
    mutate(() => { doc.value = result.document }); checkedGeometry.value = geometrySignature(doc.value)
    imageLayers.value = result.image_layers; problems.value = result.problems; await loadLayerImages()
  } catch (err) { error.value = err.message || "图片校准未完成，请检查三个锚点" }
}
function editImage(placement) { Object.assign(imageForm, copyMap(placement), { feature_id: placement.feature_id || "", reader_from_chapter: placement.reader_from_chapter || "", anchors: placement.anchors.length ? copyMap(placement.anchors) : [{ feature_id: "", image_x: 0.1, image_y: 0.1 }, { feature_id: "", image_x: 0.8, image_y: 0.1 }, { feature_id: "", image_x: 0.1, image_y: 0.8 }] }); loadSelectedImage() }
function removeImage(id) { mutate(document => { document.images = document.images.filter(image => image.page_id !== id) }) }
async function createChild() {
  if (busy.value) return
  const feature = selectedFeature.value
  saving.value = true
  try {
    const child = await api.world.createMapNode(props.projectId, { title: feature.label, level: "city", parent_id: props.node.id, location_entity_id: feature.entity_id || null })
    if (!alive) return
    saving.value = false
    mutate(() => { feature.target_node_id = child.id }); emit("saved")
  } catch (err) { error.value = err.message || "城市子图创建失败" }
  finally { if (alive) saving.value = false }
}
function openEntity() {
  if (selectedFeature.value?.entity_id) getRouter()?.navigate("world", "objects", true, new URLSearchParams({ novel_id: props.projectId, entity_id: selectedFeature.value.entity_id }))
}
function openSourceChapter(source) {
  if (source.source_ref?.chapter_index) getRouter()?.navigate("writing", null, true, new URLSearchParams({ novel_id: props.projectId, chapter_index: String(source.source_ref.chapter_index) }))
}
function downloadBackup() {
  const blob = new Blob([JSON.stringify({ base_revision_id: revision.value?.id || null, document: doc.value })], { type: "application/json" })
  const url = URL.createObjectURL(blob), link = document.createElement("a")
  link.href = url; link.download = "地图编辑备份.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); downloaded = true
}
function canLeave() {
  if (saving.value || drag) return false
  if (!dirty.value) return true
  persistDraft()
  if (!backedUp.value && !downloaded) { error.value = "当前编辑还未保存或备份，请先保存或下载备份。"; return false }
  return confirm(backedUp.value ? "地图有未保存修改，本机备份已保留。确定离开？" : "请确认已保留下载的地图备份，再离开当前编辑。")
}
function beforeUnload(event) { if (dirty.value || saving.value) { persistDraft(); event.preventDefault(); event.returnValue = "" } }
watch(doc, () => {
  if (installing || !initialized.value) return
  backedUp.value = false; clearTimeout(backupTimer); backupTimer = setTimeout(persistDraft, 200)
}, { deep: true, flush: "sync" })
watch(canvas, (element, previous) => { if (previous) resizeObserver?.unobserve(previous); if (element) resizeObserver?.observe(element) })
watch(() => props.reviewImageId, id => { if (!dirty.value) { referenceOnly.value = Boolean(id); emit("reference-visible", referenceOnly.value) } }, { immediate: true })
watch([dirty, revision, reader], () => emit("state", { dirty: dirty.value, revision: revision.value, reader: Boolean(reader.value) }), { immediate: true })
onMounted(() => {
  load(true); globalThis.addEventListener("beforeunload", beforeUnload)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(entries => { canvasWidth.value = entries[0]?.contentRect.width || 700 })
    if (canvas.value) resizeObserver.observe(canvas.value)
  }
})
onBeforeUnmount(() => { resizeObserver?.disconnect(); persistDraft(); alive = false; epoch += 1; clearTimeout(backupTimer); clearTimeout(pollTimer); globalThis.removeEventListener("beforeunload", beforeUnload); for (const url of Object.values(imageUrls)) URL.revokeObjectURL(url) })
defineExpose({ canLeave, save, dirty, revision })
</script>

<style scoped>
.map-editor{display:grid;gap:var(--space-3);min-width:0}.map-toolbar,.map-actions,.map-reader,.map-canvas-controls,.map-history,.map-candidates>div{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}.map-toolbar{justify-content:space-between}.map-caption,.map-save-status{color:var(--text-secondary);font-size:var(--text-sm)}.map-caption{display:block;margin-top:var(--space-1)}.map-toolbar .map-caption{display:inline;margin-left:var(--space-2)}.map-editor>p{margin:0}.map-editor .map-save-status{font-size:var(--text-xs)}.map-actions .btn,.map-editor summary{min-height:44px}.map-editor label{display:grid;gap:var(--space-1);min-width:0}.map-editor details{padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md);min-width:0}.map-editor summary{cursor:pointer;font-weight:600}.map-inline-form{display:flex;align-items:end;flex-wrap:wrap;gap:var(--space-2);margin-block:var(--space-2)}.map-inline-form>label{flex:1 1 140px}.map-editor input,.map-editor select,.map-editor textarea{max-width:100%;min-width:0}.map-editor input[type=number]{width:100px;min-height:36px}.map-reader>label{display:flex;align-items:center;flex-wrap:wrap}.map-edit-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,320px);gap:var(--space-3)}.map-inspector{display:grid;align-content:start;gap:var(--space-2);padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md)}.map-scroll{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-base)}.map-canvas{display:block;min-width:320px;min-height:300px;max-width:none;touch-action:pan-x pan-y}.map-paper{fill:var(--bg-base)}.map-feature{cursor:pointer;outline:none}.map-feature circle{fill:var(--accent);stroke:var(--bg-base);stroke-width:3}.map-feature polygon{fill:var(--bg-muted);stroke:var(--border);stroke-width:2}.map-feature polyline{fill:none;stroke:var(--text-secondary);stroke-width:3;stroke-dasharray:7 4}.map-kind-river polyline{stroke:var(--accent);stroke-width:5;stroke-dasharray:none}.map-feature text{fill:var(--text-primary);font-size:15px;paint-order:stroke;stroke:var(--bg-base);stroke-width:4;stroke-linejoin:round}.map-feature:focus circle,.map-feature.selected circle{stroke:var(--text-primary);stroke-width:4}.map-feature:focus polyline,.map-feature.selected polyline,.map-feature:focus polygon,.map-feature.selected polygon{stroke:var(--accent);stroke-width:4}.map-feature .map-hit{fill:transparent;stroke:none;cursor:move}.map-handle{fill:var(--bg-base);stroke:var(--accent);stroke-width:3;cursor:move;touch-action:none}.map-location-list{display:grid;gap:var(--space-1);max-height:220px;overflow:auto}.map-location-list label{display:flex;align-items:center;gap:var(--space-2);min-height:38px}.map-warning{padding:var(--space-3);background:var(--warning-soft);border:1px solid var(--warning);border-radius:var(--radius-md)}.map-error{color:var(--error)}.map-calibration{position:relative;max-width:500px;cursor:crosshair}.map-calibration img{display:block;width:100%;height:auto}.map-calibration span{position:absolute;transform:translate(-50%,-50%);background:var(--text-primary);color:var(--bg-base);border-radius:50%;width:24px;height:24px;text-align:center;pointer-events:none}.map-detail-image{max-width:100%;height:auto;border-radius:var(--radius-md)}.map-history{padding:var(--space-2);justify-content:space-between}
@media(max-width:900px){.map-edit-grid{grid-template-columns:minmax(0,1fr)}.map-toolbar{align-items:stretch;flex-direction:column}.map-reader{align-items:start}.map-editor .form-input,.map-editor .form-select{width:100%}.map-canvas-controls{justify-content:space-between}.map-candidates>div{align-items:start}.map-editor details{padding:var(--space-2)}}
</style>
