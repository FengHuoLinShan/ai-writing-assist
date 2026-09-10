<template>
  <section class="map-editor" :class="{ 'map-focused': focused }" aria-label="空间地图编辑器">
    <header class="map-toolbar">
      <div><strong>{{ focused ? node.title : '空间示意' }}</strong><span class="map-caption">不按比例</span></div>
      <div class="map-actions">
        <button v-if="!focused || dirty" class="btn btn-primary" :disabled="busy || readOnly || incompleteGeometry || (!dirty && revision)" @click="save">保存地图</button>
        <button v-if="!focused" class="btn btn-sm" :disabled="busy || readOnly || !undoStack.length" @click="undo">撤销</button>
        <button v-if="!focused" class="btn btn-sm" :disabled="busy || readOnly || !redoStack.length" @click="redo">重做</button>
        <button v-if="!readOnly" class="btn btn-sm" :aria-pressed="focused" @click="focused = !focused">{{ focused ? '展开编辑工具' : '专注看图' }}</button>
        <button v-if="hasReference" class="btn btn-sm" :aria-pressed="referenceOnly" @click="toggleReference">{{ referenceOnly ? '返回空间地图' : '查看图片参考' }}</button>
      </div>
    </header>
    <p v-if="!focused || dirty || busy" role="status" class="map-save-status">{{ saveLabel }}</p>
    <p v-if="error" role="alert" class="map-error">{{ error }}</p>
    <p v-if="reviewNotice" role="status" class="map-caption">{{ reviewNotice }}</p>
    <div v-if="backupError && dirty" class="map-warning" role="alert">
      本机备份不可用。请保存到服务端，或下载备份并确认文件已保留后再离开。
      <button class="btn btn-sm" @click="downloadBackup">下载地图备份</button>
    </div>
    <div v-if="recovery" class="map-warning map-recovery" aria-label="待处理的本机地图编辑">
      <p>{{ recoveryCorrupt ? '本机备份内容已损坏，无法直接恢复。可以先保留并离开，或明确放弃这份损坏备份后继续编辑。' : '发现未保存的本机编辑。可以继续浏览；恢复或放弃这份备份后，才能修改地图或采用其他版本。' }}</p>
      <div v-if="!discardBackupOpen" class="map-actions"><button class="btn btn-sm" :disabled="busy || recoveryCorrupt" @click="restoreBackup">恢复到编辑区</button><button ref="discardBackupTrigger" class="btn btn-sm" :disabled="busy" @click="discardBackup">放弃本机编辑</button></div>
      <div v-else class="map-recovery-confirm" role="group" aria-label="确认放弃本机编辑" @keydown.esc.prevent.stop="cancelDiscardBackup">
        <p id="map-discard-backup-question">确认放弃这份未保存的本机编辑？已保存的地图和历史版本会保留。</p>
        <div class="map-actions"><button ref="discardBackupConfirm" class="btn btn-sm" aria-describedby="map-discard-backup-question" @click="confirmDiscardBackup">确认放弃这份备份</button><button class="btn btn-sm" @click="cancelDiscardBackup">保留备份</button></div>
      </div>
    </div>
    <div v-if="conflict" class="map-warning">
      服务器已有更新，当前编辑已保留。请先查看差异，再决定使用哪一版。
      <MapChangeReview :changes="conflictChanges" @locate="locateChange" />
      <button class="btn btn-sm" @click="compareServer = !compareServer">{{ compareServer ? '回到我的编辑' : '查看服务器版' }}</button>
      <button class="btn btn-sm" :disabled="Boolean(recovery)" @click="useServer">使用服务器版</button>
      <button class="btn btn-sm" :disabled="Boolean(recovery)" @click="rebaseManually">用我的编辑创建新版</button>
    </div>
    <section v-if="candidates.length && !reader && !focused" class="map-candidates" aria-label="空间候选">
      <div v-for="candidate in candidates" :key="candidate.id">
        <span>{{ formatDate(candidate.created_at) }} · 空间候选</span>
        <button class="btn btn-sm" :disabled="busy" @click="viewCandidate(candidate)">查看</button>
        <button class="btn btn-sm" :disabled="busy || dirty || Boolean(recovery)" @click="viewCandidate(candidate)">比较后采用</button>
        <button class="btn btn-sm" :disabled="busy || Boolean(recovery)" @click="review(candidate, 'reject')">不使用</button>
      </div>
    </section>
    <section v-if="candidateView" class="map-warning" aria-label="候选地图差异">
      <strong>{{ compareCandidateCurrent ? '正在对照已保存地图' : candidateView.status === 'saved' ? '正在查看历史地图' : '正在查看空间候选' }}</strong>
      <p>与当前已保存地图比较；这些变化尚未应用。采用或恢复时会再次核对来源与版本。</p>
      <MapChangeReview v-model="selectedChangeKeys" :changes="candidateChanges" :selectable="candidateView.status === 'candidate' && !recovery" @locate="locateChange" />
      <p v-if="candidateView.status === 'candidate' && candidateView.base_revision_id !== revision?.id" role="alert">此候选基于较早地图，仅供比较；请重新整理需要更新的部分。</p>
      <button v-if="candidateView.status === 'candidate' && !adoptionPreview" class="btn btn-primary" :disabled="busy || previewing || dirty || Boolean(recovery) || !selectedChangeKeys.length || candidateView.base_revision_id !== revision?.id" @click="previewAdoption">{{ previewing ? '正在核对采用范围…' : '核对所选 ' + selectedChangeKeys.length + ' 项修改' }}</button>
      <div v-if="adoptionPreview" class="map-adoption-preview" aria-label="即将采用的修改">
        <strong>将采用 {{ adoptionPreview.applied_change_keys.length }} 项修改</strong>
        <p>请核对实际生效范围；标有“关联修改”的内容会一并采用，未列出的修改继续保留为候选。</p>
        <ul><li v-for="change in adoptionChanges" :key="change.key">{{ change.action }}：{{ change.label }}<strong v-if="adoptionPreview.expanded_change_keys.includes(change.key)">（关联修改）</strong></li></ul>
        <button class="btn btn-primary" :disabled="busy || dirty || Boolean(recovery)" @click="review(candidateView, 'adopt', selectedChangeKeys)">确认采用共 {{ adoptionPreview.applied_change_keys.length }} 项修改</button>
      </div>
      <button v-if="candidateView.status === 'saved'" class="btn btn-primary" :disabled="busy || dirty || Boolean(recovery) || candidateView.id === revision?.id" @click="review(candidateView, 'restore')">恢复为新版本</button>
      <button class="btn btn-sm" @click="compareCandidateCurrent = !compareCandidateCurrent">{{ compareCandidateCurrent ? '查看候选地图' : '对照已保存地图' }}</button>
      <button class="btn btn-sm" @click="exitCandidate">返回当前地图</button>
    </section>
    <div v-if="!focused" class="map-reader">
      <label>阅读预览：进入第 <input v-model.number="readerChapter" aria-label="阅读预览章节" type="number" min="1" max="100000" /> 章时</label>
      <button class="btn btn-sm" :disabled="busy || !revision || dirty" @click="previewReader">{{ reader ? '更新阅读预览' : '预览读者所见' }}</button>
      <button v-if="reader" class="btn btn-sm" @click="exitReader">回到作者视图</button>
      <span v-if="reader">仅显示该章开始前可公开的内容，位置保持不变。</span>
    </div>
    <FocusedEvidencePanel v-if="!readOnly && !focused"
      :project-id="projectId" consumer="map" :scope-key="node.id"
      :roots="evidenceRoots" :initial-name="selectedFeature?.label || node.title || ''"
      question="核对地点的方位、相邻区域、道路、河流和直接关联地点；只查原文明确依据"
      :selected-refs="evidenceRefs" select-label="加入本次地图资料"
      @select-source="emit('pin-evidence', $event)"
      @clear-selection="emit('clear-evidence')"
    />
    <template v-if="!referenceOnly">
      <div class="map-navigation">
        <div class="map-canvas-controls">
          <label>缩放 <input v-model.number="zoom" aria-label="空间地图缩放" type="range" min="60" max="200" step="10" /></label>
          <button class="btn btn-sm" @click="zoom = 100">适合画布</button>
          <span v-if="!focused">● 地点  ━ 河流  ┄ 道路  ▱ 区域</span>
        </div>
        <div class="map-locator">
          <label>查找地图内容<input v-model="mapQuery" class="form-input" type="search" placeholder="地点、道路或区域名称" /></label>
          <div v-if="mapQuery.trim()" class="map-actions"><button v-for="feature in matchingFeatures" :key="feature.id" class="btn btn-sm" @click="locateFeature(feature.id)">{{ feature.label }}{{ feature.points.length ? '' : '（待定位）' }}</button><span v-if="!matchingFeatures.length" role="status">当前地图没有匹配内容。</span></div>
          <p v-if="locatorMessage" role="status" class="map-caption">{{ locatorMessage }}</p>
        </div>
      </div>
      <div ref="scrollArea" class="map-scroll" :class="{ panning }" tabindex="0" role="region" aria-label="地图视口，方向键平移" @scroll="rememberView" @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan" @keydown.self="panByKey">
        <svg ref="canvas" class="map-canvas" :style="{ width: zoom + '%', '--map-zoom': zoom / 100 }" :viewBox="[bounds.x, bounds.y, bounds.width, bounds.height].join(' ')" role="group" aria-label="空间地图画布" @click.self="placePoint" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag">
          <rect :x="bounds.x" :y="bounds.y" :width="bounds.width" :height="bounds.height" class="map-paper" @click="placePoint" />
          <defs><marker :id="'map-face-' + node.id" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" class="map-facing-head" /></marker></defs>
          <image v-for="layer in backgrounds" :key="layer.page_id" :href="imageUrls[imageKey(layer.page_id)]" width="1" height="1" preserveAspectRatio="none" :transform="'matrix(' + layer.transform.join(' ') + ')'" :opacity="layer.opacity" pointer-events="none" />
          <polyline v-for="(leg, index) in rehearsal.legs" :key="'rehearsal:' + index" :points="pointsAttribute(leg.points)" class="map-rehearsal-line" pointer-events="none" />
          <polyline v-for="line in selectedFaces" :key="line.id" :points="pointsAttribute(line.points)" class="map-facing-line" :marker-end="'url(#map-face-' + node.id + ')'" pointer-events="none" />
          <g v-for="feature in paintedFeatures" :key="feature.id" :data-feature-id="feature.id" :class="['map-feature', 'map-kind-' + feature.kind, { selected: selectedId === feature.id, rehearsed: rehearsal.featureIds.includes(feature.id) }]" role="button" tabindex="0" :aria-label="feature.label" @click.stop="selectFeature(feature.id)" @keydown.enter.prevent="selectFeature(feature.id)" @keydown.space.prevent="selectFeature(feature.id)" @keydown="moveByKey($event, feature)">
            <polygon v-if="feature.kind === 'area'" :points="pointsAttribute(feature.points)" :fill-opacity="backgrounds.length ? 0.12 : 0.6" />
            <polyline v-else-if="['road', 'river'].includes(feature.kind)" :points="pointsAttribute(feature.points)" />
            <circle v-else :cx="feature.points[0].x" :cy="feature.points[0].y" :r="7 * mapUnit" @pointerdown.stop="startDrag($event, feature, 0)" />
            <circle v-if="['location', 'landmark'].includes(feature.kind)" :cx="feature.points[0].x" :cy="feature.points[0].y" :r="22 * mapUnit" class="map-hit" @pointerdown.stop="startDrag($event, feature, 0)" />
            <text v-if="labelPositions[feature.id]" :x="labelPositions[feature.id].x" :y="labelPositions[feature.id].y" :style="{ fontSize: 14 * mapUnit + 'px' }">{{ feature.label }}</text>
          </g>
          <g v-if="selectedFeature && !readOnly && !focused && !selectedFeature.locked">
            <line v-for="(segment, index) in selectedSegments" :key="'segment:' + index" :x1="segment[0].x" :y1="segment[0].y" :x2="segment[1].x" :y2="segment[1].y" class="map-segment" :class="{ selected: selectedSegment === index }" :style="{ strokeWidth: 12 * mapUnit }" @click.stop="selectedSegment = index" />
            <circle v-for="(point, index) in selectedFeature.points" :key="index" :cx="point.x" :cy="point.y" :r="7 * mapUnit" class="map-handle" :class="{ selected: selectedVertex === index }" @pointerdown.stop="startDrag($event, selectedFeature, index)" @click.stop="selectedVertex = index" />
          </g>
        </svg>
      </div>
      <p v-if="!displayDocument.features.length" class="map-caption">{{ reader ? '这个阅读进度暂无可展示的地图内容。' : '先加入已有地点，或添加标记。已知道路和区域可以用折线与轮廓表示。' }}</p>
      <p v-if="placing && !readOnly && !focused" role="status">请点击画布{{ selectedFeature?.kind === 'location' || selectedFeature?.kind === 'landmark' ? '放置地点' : '依次添加控制点' }}。<button class="btn btn-sm" @click="finishDrawing">结束绘制</button></p>
    </template>
    <section v-if="!readOnly && (taskRunning || generationSummary || ['failed', 'cancelled'].includes(taskStatus))" class="map-generation-feedback" aria-label="空间整理结果">
      <p role="status">{{ taskRunning ? '正在核对空间资料，结果会保留为候选，已保存地图不会被替换。' : generationSummary?.message || (taskStatus === 'cancelled' ? '本次整理已停止，已保存地图仍可使用。选择内容后可以重新整理。' : '空间整理未完成，已保存地图仍可使用。请检查来源，选择内容后重新整理。') }}</p>
      <button v-if="taskRunning" class="btn btn-sm" :disabled="busy || cancelling" @click="cancelGeneration">{{ cancelling ? '正在停止…' : '停止本次整理' }}</button>
      <button v-else-if="taskStatus !== 'done' || generationSummary?.outcome !== 'complete'" class="btn btn-sm" @click="showGenerationChoices">选择内容重新整理</button>
      <details v-if="generationSummary"><summary>查看整理详情</summary><dl><template v-for="item in generationCounters" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></template></dl><ul v-if="discardCounts.length"><li v-for="item in discardCounts" :key="item.label">{{ item.label }}：{{ item.value }} 条</li></ul></details>
    </section>
    <MapRehearsalPanel v-if="!readOnly && !referenceOnly" v-model:stops="rehearsalStops" :document="doc" :result="rehearsal" @open-source="openSourceChapter" />
    <div v-if="!readOnly && !referenceOnly && !focused" class="map-edit-grid">
      <div>
        <details ref="generationTools" open>
          <summary>地点与绘制</summary>
          <form class="map-inline-form" @submit.prevent="searchLocations"><label>查找已采用地点<input v-model="searchQuery" class="form-input" placeholder="输入地点名称" /></label><button class="btn btn-sm" :disabled="busy">查找</button></form>
          <div class="map-location-list map-world-locations">
            <label v-for="location in locations" :key="location.id"><input v-model="selectedLocationIds" :value="location.id" type="checkbox" :disabled="busy || (!selectedLocationIds.includes(location.id) && selectedLocationIds.length >= 20)" />{{ location.name }}</label>
          </div>
          <div class="map-actions"><button class="btn btn-sm" :disabled="busy || !selectedLocationIds.length" @click="addLocations">加入地图</button><button class="btn btn-sm" :disabled="busy || taskRunning || !selectedLocationIds.length || dirty" @click="generate">{{ taskRunning ? '正在整理空间资料…' : '用这些地点生成空间关系' }}</button></div>
          <details v-if="doc.features.length"><summary>整理地图中已有内容</summary><p>只整理选中的内容及其明确关系；手工位置保留，资料会在生成前供你检查。</p><div class="map-location-list"><label v-for="feature in doc.features" :key="feature.id"><input v-model="selectedFeatureIds" type="checkbox" :value="feature.id" :disabled="busy || (!selectedFeatureIds.includes(feature.id) && selectedFeatureIds.length >= 20)" />{{ feature.label }}</label></div><button class="btn btn-sm" :disabled="busy || taskRunning || dirty || !selectedFeatureIds.length" @click="generateExisting">整理所选内容的空间关系</button></details>
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
            <label>地点<select v-model="relation.subject" class="form-select"><option value="">请选择</option><option v-for="f in relationSubjects" :key="f.id" :value="f.id">{{ f.label }}</option></select></label>
            <label>关系<select v-model="relation.relation" class="form-select"><option v-for="(label, key) in relationLabels" :key="key" :value="key">{{ label }}</option></select></label>
            <label>{{ relation.relation === 'along_street' ? '所属道路' : '另一地点' }}<select v-model="relation.target" class="form-select"><option value="">请选择</option><option v-for="f in relationTargets" :key="f.id" :value="f.id">{{ f.label }}</option></select></label>
            <button class="btn btn-sm" :disabled="busy || !relation.subject || !relation.target">添加关系</button>
          </form>
          <ul><li v-for="constraint in doc.constraints" :key="constraint.id">{{ featureLabel(constraint.subject) }} · {{ relationLabels[constraint.relation] }} · {{ featureLabel(constraint.target) }} <button class="btn btn-sm" @click="removeConstraint(constraint.id)">移出</button></li></ul>
        </details>
      </div>
      <aside v-if="selectedFeature" class="map-inspector" aria-label="地图内容详情">
        <label>显示名称<input :value="selectedFeature.label" class="form-input" maxlength="200" @input="changeFeature('label', $event.target.value)" /></label>
        <label v-if="['location', 'landmark', 'area'].includes(selectedFeature.kind)">关联世界地点<select :value="selectedFeature.entity_id || ''" class="form-select" @change="bindEntity($event.target.value)"><option value="">独立地图标记</option><option v-if="selectedFeature.entity_id && !locations.some(item => item.id === selectedFeature.entity_id)" :value="selectedFeature.entity_id">当前已关联的世界地点</option><option v-for="location in locations" :key="location.id" :value="location.id">{{ location.name }}</option></select></label>
        <section class="map-feature-sources" aria-label="地点资料依据">
          <strong>资料依据（{{ selectedFeature.sources.length }}/8）</strong>
          <p v-if="!selectedFeature.sources.length" class="map-caption">尚未关联依据。可以查找正文里的位置描述，关联并保存后再整理空间关系。</p>
          <button type="button" class="btn btn-sm" :disabled="busy || selectedFeature.sources.length >= 8" @click="openSourcePicker()">添加正文依据</button>
          <p v-if="selectedFeature.sources.length >= 8" class="map-caption">最多关联 8 条依据，可先移出不需要的内容。</p>
          <article v-for="(source, index) in selectedFeature.sources" :key="index">
            <strong>{{ source.kind === 'source_range' ? '第 ' + (source.source_ref?.chapter_index || '—') + ' 章正文' : '已关联世界资料' }}</strong>
            <p>{{ source.quote || '保留了已确认资料的引用' }}</p>
            <div class="map-actions"><button v-if="source.kind === 'source_range'" type="button" class="btn btn-sm" @click="openSourcePicker(source)">查看正文</button><button v-if="source.kind === 'source_range' && source.source_ref?.chapter_index" class="btn btn-sm" @click="openSourceChapter(source)">打开章节</button><button type="button" class="btn btn-sm" :disabled="busy" :aria-label="'移出第 ' + (index + 1) + ' 条依据'" @click="removeSource(index)">移出依据</button></div>
          </article>
        </section>
        <label><input :checked="selectedFeature.locked" type="checkbox" @change="changeFeature('locked', $event.target.checked)" />锁定位置</label>
        <div class="map-actions"><button class="btn btn-sm" :disabled="selectedFeature.locked" @click="placing = true">点击画布定位／添点</button><button class="btn btn-sm" :disabled="selectedFeature.locked || !canRemovePoint" @click="removePoint">移出选中控制点</button></div>
        <p class="map-caption">可拖动控制点，或用下面的方向按钮微调；键盘方向键也可移动。</p>
        <label v-if="selectedFeature.points.length > 1">控制点<select v-model.number="selectedVertex" class="form-select"><option v-for="(_, index) in selectedFeature.points" :key="index" :value="index">{{ index + 1 }}</option></select></label>
        <div v-if="selectedSegments.length" class="map-inline-form"><label>插入位置<select v-model.number="selectedSegment" class="form-select"><option v-for="(_, index) in selectedSegments" :key="index" :value="index">第 {{ index + 1 }} 点到第 {{ (index + 1) % selectedFeature.points.length + 1 }} 点</option></select></label><button class="btn btn-sm" :disabled="selectedFeature.locked || selectedFeature.points.length >= 128" @click="insertPoint">在线段中点插入</button></div>
        <div class="map-actions"><button class="btn btn-sm" aria-label="向左移动" @click="nudge(-10, 0)">←</button><button class="btn btn-sm" aria-label="向上移动" @click="nudge(0, -10)">↑</button><button class="btn btn-sm" aria-label="向下移动" @click="nudge(0, 10)">↓</button><button class="btn btn-sm" aria-label="向右移动" @click="nudge(10, 0)">→</button></div>
        <label>最早在第几章开始时展示<input :value="selectedFeature.reader_from_chapter || ''" type="number" min="1" max="100000" class="form-input" placeholder="留空：仅作者可见" @change="changeFeature('reader_from_chapter', $event.target.value ? Number($event.target.value) : null)" /></label>
        <label>补充说明<textarea :value="selectedFeature.note" class="form-textarea" maxlength="1000" @input="changeFeature('note', $event.target.value)" /></label>
        <label>打开子图<select :value="selectedFeature.target_node_id || ''" class="form-select" @change="changeFeature('target_node_id', $event.target.value || null)"><option value="">不跳转</option><option v-for="target in childChoices" :key="target.id" :value="target.id">{{ target.title }}</option></select></label>
        <div class="map-actions"><button v-if="selectedFeature.target_node_id" class="btn btn-sm" @click="emit('open-node', selectedFeature.target_node_id)">进入子图</button><button v-if="childLevel && ['location', 'landmark', 'area'].includes(selectedFeature.kind) && !selectedFeature.target_node_id" class="btn btn-sm" :disabled="busy" @click="createChild">为此地点创建{{ childLevel.label }}图</button><button v-if="selectedFeature.entity_id" class="btn btn-sm" @click="openEntity">查看世界资料</button><button class="btn btn-sm" @click="removeFeature">移出地图</button></div>
        <ul v-if="selectedRelations.length"><li v-for="item in selectedRelations" :key="item.id">{{ featureLabel(item.subject) }} · {{ relationLabels[item.relation] }} · {{ featureLabel(item.target) }}<button class="btn btn-sm" @click="locateFeature(item.subject === selectedId ? item.target : item.subject)">查看关联位置</button></li></ul>
        <img v-for="layer in selectedIllustrations" :key="layer.page_id" :src="imageUrls[imageKey(layer.page_id)]" alt="地点配图" class="map-detail-image" />
      </aside>
    </div>
    <aside v-if="(recovery || reader || focused || candidateView) && displayedFeature && !referenceOnly" class="map-inspector" :aria-label="reader ? '读者地点详情' : '地图地点详情'">
      <strong>{{ displayedFeature.label }}</strong>
      <template v-if="!reader"><p v-if="displayedFeature.note">{{ displayedFeature.note }}</p><p v-for="(source, index) in displayedFeature.sources" :key="index">{{ source.quote }}<button v-if="source.kind === 'source_range'" class="btn btn-sm" @click="openSourceChapter(source)">打开第 {{ source.source_ref.chapter_index }} 章</button></p><button v-if="!candidateView && displayedFeature.target_node_id" class="btn btn-sm" @click="emit('open-node', displayedFeature.target_node_id)">进入子图</button></template>
      <img v-for="layer in selectedIllustrations" :key="layer.page_id" :src="imageUrls[imageKey(layer.page_id)]" class="map-detail-image" :alt="reader ? '可公开的地点配图' : '地点配图'" />
    </aside>
    <details v-if="!readOnly && !focused && images.length" class="map-image-controls">
      <summary>底图与地点配图</summary>
      <div class="map-inline-form">
        <label>已采用图片<select v-model="imageForm.page_id" class="form-select" @change="loadSelectedImage"><option value="">请选择</option><option v-for="page in images" :key="page.id" :value="page.id">{{ imageChoiceLabel(page) }}</option></select></label>
        <label>用途<select v-model="imageForm.role" class="form-select"><option value="illustration">地点配图</option><option value="background">地图底图</option></select></label>
        <label v-if="imageForm.role === 'illustration'">关联地点<select v-model="imageForm.feature_id" class="form-select"><option value="">整张地图</option><option v-for="feature in doc.features" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select></label>
      </div>
      <img v-if="imageForm.role === 'illustration' && imageUrls[imageKey(imageForm.page_id)]" :src="imageUrls[imageKey(imageForm.page_id)]" alt="待关联配图预览" class="map-illustration-preview" />
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
      <p v-if="imageForm.page_id" role="status" class="map-image-baseline-status">{{ imageBaselineMessage }}</p>
      <div v-if="imageForm.page_id && imageImpact.content.length" class="map-warning"><strong>图片需要复核</strong><p>{{ imageImpact.anchors.length ? '校准点发生变化：' + imageImpact.anchors.join('、') : '三个校准点没有位置变化，但空间内容发生变化。' }}</p><ul><li v-for="(line, index) in imageImpact.content" :key="index">{{ line }}</li></ul><p>请检查图片是否仍符合地图；系统不会自动付费重画。</p></div>
      <button v-if="selectedImageRevision" class="btn btn-sm" :disabled="busy" @click="compareImageRevision(selectedImageRevision)">对照图片生成时的地图</button>
      <button v-if="selectedCalibrationRevision" class="btn btn-sm" :disabled="busy" @click="compareImageRevision(selectedCalibrationRevision)">对照上次校准时的地图</button>
      <button class="btn btn-sm" :disabled="busy || !imageForm.page_id" @click="applyImage">预览图片设置</button>
      <ul><li v-for="placement in doc.images" :key="placement.page_id">{{ imageTitle(placement.page_id) }} · {{ placement.role === 'background' ? '底图' : '配图' }} <strong v-if="imageState(placement) !== 'ready'">{{ imageState(placement) === 'stale' ? '待复核，已退出叠加' : '图片已移出，展示已关闭' }}</strong><button class="btn btn-sm" @click="editImage(placement)">调整／重新校准</button><button class="btn btn-sm" @click="removeImage(placement.page_id)">关闭此展示层</button></li></ul>
      <details v-if="annotations.length || doc.annotation_bindings.length"><summary>绑定原图片标注</summary><ul><li v-for="binding in doc.annotation_bindings" :key="binding.annotation_id">已绑定到 {{ featureLabel(binding.feature_id) }} <button class="btn btn-sm" @click="unbindAnnotation(binding.annotation_id)">解除绑定</button></li></ul><form class="map-inline-form" @submit.prevent="bindAnnotation"><label>原标注<select v-model="annotationId" class="form-select"><option value="">请选择</option><option v-for="annotation in annotations" :key="annotation.id" :value="annotation.id">{{ annotation.label }}</option></select></label><label>地图地点<select v-model="annotationFeatureId" class="form-select"><option value="">请选择</option><option v-for="feature in doc.features" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select></label><button class="btn btn-sm" :disabled="!annotationId || !annotationFeatureId">绑定</button></form></details>
    </details>
    <details v-if="problems.length && !reader" open class="map-warning"><summary>需要核对 {{ problems.length }} 项</summary><ul><li v-for="(problem, index) in problems" :key="index">{{ problem.message }}<button v-if="problem.feature_ids.length" class="btn btn-sm" @click="selectFeature(problem.feature_ids[0])">定位</button></li></ul></details>
    <details v-if="!reader && !focused"><summary @click="loadHistory">地图历史</summary><div v-for="item in history" :key="item.id" class="map-history"><span>{{ formatDate(item.created_at) }} · {{ item.status === 'saved' ? '已保存' : item.status === 'candidate' ? '候选' : '已处理候选' }}</span><button class="btn btn-sm" :disabled="busy" @click="viewCandidate(item)">查看并比较</button><button v-if="item.status === 'saved'" class="btn btn-sm" :disabled="busy || dirty || Boolean(recovery) || item.id === revision?.id" @click="review(item, 'restore')">恢复为新版本</button></div></details>
    <MapSourcePicker v-if="selectedFeature" :key="node.id + ':' + selectedId" :open="sourcePickerOpen" :project-id="projectId" :feature="selectedFeature" :initial-source="sourcePickerInitial" @close="sourcePickerOpen = false" @add="addSource" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getConfirm, getRouter } from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { ACCOUNT_MARKER_KEY } from "../../../shared/accountStorage.js"
import { copyMap, emptyMap, geometrySignature, mapBounds, mapChangeDetails, mapFeatureCenter, mapImageChanges, mapRelationLabels, mapSourceRangeKey, mapSourceSelections, pointsAttribute, rehearseMapRoute, removeMapFeature } from "./mapStructureEditor.js"
import FocusedEvidencePanel from "../../components/FocusedEvidencePanel.vue"
import MapChangeReview from './MapChangeReview.vue'
import MapRehearsalPanel from './MapRehearsalPanel.vue'
import MapSourcePicker from './MapSourcePicker.vue'

const props = defineProps({ projectId: { type: String, required: true }, node: { type: Object, required: true }, images: { type: Array, default: () => [] }, knownNodes: { type: Array, default: () => [] }, hasReference: Boolean, reviewImageId: { type: String, default: "" }, initialFeatureId: { type: String, default: '' }, initialRevisionId: { type: String, default: '' }, evidenceRefs: { type: Array, default: () => [] } })
const emit = defineEmits(["saved", "open-node", "reference-visible", "state", "select-feature", "pin-evidence", "clear-evidence"])
const api = getApi(), confirm = getConfirm()
const doc = ref(emptyMap()), revision = ref(null), serverRevision = ref(null), baseline = ref(JSON.stringify(emptyMap()))
const candidates = ref([]), candidateView = ref(null), history = ref([]), imageLayers = ref([]), checkedGeometry = ref("")
const loading = ref(false), saving = ref(false), error = ref(""), problems = ref([]), initialized = ref(false)
const recovery = ref(null), backupError = ref(false), backedUp = ref(false), conflict = ref(false), compareServer = ref(false)
const discardBackupOpen = ref(false), discardBackupTrigger = ref(null), discardBackupConfirm = ref(null), recoveryCorrupt = ref(false)
const undoStack = ref([]), redoStack = ref([]), selectedId = ref(""), selectedVertex = ref(0), selectedSegment = ref(0), placing = ref(false)
const canvas = ref(null), canvasWidth = ref(700), canvasHeight = ref(0), zoom = ref(100), referenceOnly = ref(false), dragBounds = ref(null)
const focused = ref(false), mapQuery = ref(""), locatorMessage = ref(""), compareCandidateCurrent = ref(false)
const selectedChangeKeys = ref([]), selectedFeatureIds = ref([]), comparisonLayers = ref([]), reviewNotice = ref(''), rehearsalStops = ref([]), scrollArea = ref(null)
const adoptionPreview = ref(null), previewing = ref(false), imageBaseline = ref(null), imageBaselineStatus = ref('unknown'), panning = ref(false)
const generationSummary = ref(null), cancelling = ref(false), generationTools = ref(null)
const searchQuery = ref(""), locations = ref([]), selectedLocationIds = ref([]), newLabel = ref(""), newKind = ref("location")
const taskId = ref(null), taskStatus = ref(null), reader = ref(null), readerChapter = ref(1)
const imageUrls = reactive({}), anchorIndex = ref(0), annotationId = ref(""), annotationFeatureId = ref("")
const imageForm = reactive({ page_id: "", role: "illustration", feature_id: "", opacity: 0.65, anchors: [{ feature_id: "", image_x: 0.1, image_y: 0.1 }, { feature_id: "", image_x: 0.8, image_y: 0.1 }, { feature_id: "", image_x: 0.1, image_y: 0.8 }], reader_from_chapter: "" })
const relation = reactive({ subject: "", relation: "north", target: "" })
const relationLabels = mapRelationLabels
const sourcePickerOpen = ref(false), sourcePickerInitial = ref(null)
const imageRequests = new Map()
let resizeObserver = null
let epoch = 0, alive = true, installing = false, backupTimer = null, pollTimer = null, drag = null, downloaded = false, reviewEpoch = 0, imageBaselineEpoch = 0, comparisonEpoch = 0, lastLoadError = '', pan = null
const dirty = computed(() => JSON.stringify(doc.value) !== baseline.value)
const busy = computed(() => loading.value || saving.value)
const taskRunning = computed(() => ["pending", "running"].includes(taskStatus.value))
const generationCounters = computed(() => {
  const summary = generationSummary.value
  if (!summary) return []
  return [['地点或图元', 'targets'], ['资料片段', 'sources'], ['处理字符数', 'input_characters'], ['资料批次', 'batches'], ['未完成批次', 'failed_batches'], ['超出容量的批次', 'truncated_batches'], ['收到的关系', 'received_relations'], ['保留的关系', 'accepted_relations'], ['未通过检查的关系', 'discarded_relations'], ['生成尝试次数', 'structured_attempts'], ['格式修正次数', 'format_retries']].map(([label, key]) => ({ label, value: summary[key] ?? '未记录' }))
})
const discardCounts = computed(() => {
  const labels = { unknown_feature: '无法对应地图内容', outside_selection: '超出所选内容范围', unknown_source: '来源未进入确认', quote_mismatch: '引文与来源不符', path_label_mismatch: '路线名称缺少依据', source_changed: '来源已经变化', invalid_geometry: '空间关系不符合地图约束', invalid_schema: '内容格式不符合要求' }
  return Object.entries(generationSummary.value?.discard_reasons || {}).filter(([key, count]) => labels[key] && count > 0).map(([key, value]) => ({ label: labels[key], value }))
})
const incompleteGeometry = computed(() => doc.value.features.some(feature => feature.points.length > 0 && feature.points.length < (feature.kind === 'area' ? 3 : ['road', 'river'].includes(feature.kind) ? 2 : 1)))
const readOnly = computed(() => Boolean(recovery.value || reader.value || candidateView.value || compareServer.value))
const displayDocument = computed(() => reader.value ? { features: reader.value.features } : candidateView.value ? (compareCandidateCurrent.value ? revision.value?.document || emptyMap() : candidateView.value.document) : (compareServer.value && serverRevision.value ? serverRevision.value.document : doc.value))
const displayedFeature = computed(() => displayDocument.value.features.find(feature => feature.id === selectedId.value))
const matchingFeatures = computed(() => displayDocument.value.features.filter(feature => feature.label.toLocaleLowerCase().includes(mapQuery.value.trim().toLocaleLowerCase())))
const candidateChanges = computed(() => candidateView.value ? mapChangeDetails(revision.value?.document || emptyMap(), candidateView.value.document) : [])
const adoptionChanges = computed(() => candidateChanges.value.filter(change => adoptionPreview.value?.applied_change_keys.includes(change.key)))
const rehearsal = computed(() => readOnly.value ? { message: '', legs: [], featureIds: [] } : rehearseMapRoute(doc.value, rehearsalStops.value, problems.value.flatMap(problem => problem.feature_ids)))
const selectedRelations = computed(() => doc.value.constraints.filter(item => [item.subject, item.target].includes(selectedId.value)))
const selectedFaces = computed(() => (displayDocument.value.constraints || []).filter(item => item.relation === 'faces' && item.subject === selectedId.value).map(item => ({ id: item.id, points: [item.subject, item.target].map(id => mapFeatureCenter(displayDocument.value.features.find(feature => feature.id === id))) })).filter(item => item.points.every(Boolean)))
const childLevel = computed(() => ({ region: { value: 'city', label: '城市' }, city: { value: 'district', label: '街区' }, district: { value: 'street', label: '街道' } })[props.node.level])
const relationSubjects = computed(() => doc.value.features.filter(item => !['along_street', 'entrance_to', 'faces'].includes(relation.relation) || ['location', 'landmark'].includes(item.kind)))
const relationTargets = computed(() => doc.value.features.filter(item => item.id !== relation.subject && (relation.relation === 'along_street' ? item.kind === 'road' : ['entrance_to', 'faces'].includes(relation.relation) ? ['location', 'landmark', 'area'].includes(item.kind) : true)))
const imageImpact = computed(() => imageBaseline.value ? mapImageChanges(doc.value.images.find(item => item.page_id === imageForm.page_id) || { anchors: [] }, imageBaseline.value.document, doc.value) : { anchors: [], content: [] })
const selectedImageRevision = computed(() => props.images.find(item => item.id === imageForm.page_id)?.source_map_revision_id)
const selectedImageLayer = computed(() => imageLayers.value.find(item => item.page_id === imageForm.page_id))
const selectedCalibrationRevision = computed(() => selectedImageLayer.value?.role === 'background' && selectedImageLayer.value.calibration_lookup_status === 'found' ? selectedImageLayer.value.calibration_revision_id : null)
const imageBaselineRevision = computed(() => selectedImageRevision.value || selectedCalibrationRevision.value)
const imageBaselineKind = computed(() => selectedImageRevision.value ? 'generation' : 'calibration')
const imageBaselineMessage = computed(() => {
  const purpose = imageBaselineKind.value === 'generation' ? '图片生成时' : '上次校准时'
  if (imageBaselineStatus.value === 'loading') return `正在读取${purpose}的地图…`
  if (imageBaselineStatus.value === 'error') return `${purpose}的地图暂时无法读取，当前不能判断变化。请重新选择图片重试。`
  if (imageBaselineStatus.value === 'ready') return imageBaselineKind.value === 'generation' ? '变化依据：图片生成时绑定的地图版本。' : '变化依据：已保存的底图校准版本，只用于对照空间与锚点，不表示图片由该版本生成。'
  if (selectedImageLayer.value?.calibration_lookup_status === 'truncated') return '校准历史较多，本次未查到可确认的基准，无法自动判断空间变化。请人工核对，或重新校准后保存。'
  if (selectedImageLayer.value?.role === 'background') return '未找到与此底图校准配置匹配的已保存版本，无法自动判断空间变化。请人工核对，或重新校准后保存。'
  return '此图片没有绑定生成时的地图版本，无法自动判断空间变化。请人工检查图片与校准点。'
})
const bounds = computed(() => dragBounds.value || mapBounds(displayDocument.value.features))
const paintRank = feature => feature.kind === 'area' ? 0 : ['road', 'river'].includes(feature.kind) ? 1 : 2
const paintedFeatures = computed(() => [...displayDocument.value.features].filter(f => f.points.length).sort((a, b) => paintRank(a) - paintRank(b)))
const mapUnit = computed(() => Math.max(bounds.value.width / Math.max(1, canvasWidth.value), canvasHeight.value ? bounds.value.height / canvasHeight.value : 0))
const labelPositions = computed(() => {
  const placed = [], result = {}, unit = mapUnit.value
  for (const feature of [...paintedFeatures.value].sort((a, b) => Number(b.id === selectedId.value) - Number(a.id === selectedId.value) || paintRank(b) - paintRank(a))) {
    const point = ['road', 'river'].includes(feature.kind) ? feature.points[Math.floor(feature.points.length / 2)] : feature.points[0]
    const width = [...feature.label].length * 14 * unit, height = 20 * unit
    for (const [dx, dy] of [[14, -13], [14, 23], [-14, -13], [-14, 23]]) {
      const x = point.x + dx*unit - (dx < 0 ? width : 0), y = point.y + dy*unit
      const box = { x, y: y-height, width, height }
      if (width < bounds.value.width && (box.x < bounds.value.x || box.x + width > bounds.value.x + bounds.value.width)) continue
      if (placed.some(other => box.x < other.x+other.width && box.x+width > other.x && box.y < other.y+other.height && box.y+height > other.y)) continue
      result[feature.id] = { x, y }; placed.push(box); break
    }
    if (feature.id === selectedId.value && !result[feature.id]) result[feature.id] = { x: Math.max(bounds.value.x, Math.min(point.x + 14 * unit, bounds.value.x + bounds.value.width - width)), y: point.y - 13 * unit }
  }
  return result
})
const selectedFeature = computed(() => doc.value.features.find(f => f.id === selectedId.value))
const evidenceRoots = computed(() => {
  const ids = selectedFeature.value?.entity_id ? [selectedFeature.value.entity_id] : selectedLocationIds.value.length ? selectedLocationIds.value : props.node.location_entity_id ? [props.node.location_entity_id] : []
  return ids.map(id => ({ target_ref: { target_type: "core_entity", target_id: id, target_path: "" } }))
})
const selectedSegments = computed(() => {
  const feature = selectedFeature.value
  if (!feature || feature.points.length < 2 || !['road', 'river', 'area'].includes(feature.kind)) return []
  return feature.points.slice(0, feature.kind === 'area' ? undefined : -1).map((point, index) => [point, feature.points[(index + 1) % feature.points.length]])
})
const canRemovePoint = computed(() => selectedFeature.value?.points.length > (selectedFeature.value.kind === 'area' ? 3 : ['road', 'river'].includes(selectedFeature.value.kind) ? 2 : 0))
const anchorFeatures = computed(() => doc.value.features.filter(f => ["location", "landmark"].includes(f.kind) && f.points.length === 1))
const childChoices = computed(() => props.knownNodes.filter(node => node.id !== props.node.id && node.parent_id === props.node.id))
const annotations = computed(() => props.images.flatMap(page => page.annotations || []))
const conflictChanges = computed(() => serverRevision.value ? mapChangeDetails(serverRevision.value.document, doc.value) : [])
const saveLabel = computed(() => saving.value ? "正在处理地图操作…" : recovery.value ? "当前浏览已保存地图，本机编辑尚待处理" : dirty.value ? (backedUp.value ? "未保存到服务端 · 当前编辑已在本机备份" : "有未保存修改") : revision.value ? "已保存到服务端" : "空间结构尚未保存")
const backgrounds = computed(() => {
  if (candidateView.value && !compareCandidateCurrent.value) return comparisonLayers.value.filter(layer => layer.role === 'background' && layer.state === 'ready' && layer.transform)
  if (candidateView.value) return imageLayers.value.filter(layer => layer.role === 'background' && layer.state === 'ready' && layer.transform)
  if (compareServer.value) return []
  const layers = reader.value ? reader.value.images : imageLayers.value
  return layers.filter(layer => layer.role === "background" && layer.transform && (reader.value || imageState(doc.value.images.find(i => i.page_id === layer.page_id)) === "ready")).map(layer => ({ ...layer, opacity: reader.value ? layer.opacity : doc.value.images.find(i => i.page_id === layer.page_id)?.opacity ?? layer.opacity }))
})
const selectedIllustrations = computed(() => (reader.value ? reader.value.images : candidateView.value && !compareCandidateCurrent.value ? comparisonLayers.value : imageLayers.value).filter(layer => layer.role === "illustration" && (!layer.feature_id || layer.feature_id === selectedId.value) && (reader.value || layer.state === "ready")))

function imageKey(pageId) { return (reader.value ? "reader:" + readerChapter.value + ":" : "author:") + pageId }
function imageTitle(pageId) { return props.images.find(page => page.id === pageId)?.title || "已有图片" }
function imageChoiceLabel(page) {
  const placement = doc.value.images.find(item => item.page_id === page.id)
  const usage = placement ? (placement.role === 'background' ? '底图' : placement.feature_id ? featureLabel(placement.feature_id) + '配图' : '整图配图') : ''
  return [page.title, usage, formatDate(page.created_at)].filter(Boolean).join(' · ')
}
function imageState(placement) {
  if (!placement) return "unavailable"
  if (placement.role === "background" && checkedGeometry.value !== geometrySignature(doc.value)) return "stale"
  return imageLayers.value.find(layer => layer.page_id === placement.page_id)?.state || "unavailable"
}
function featureLabel(id) { return doc.value.features.find(f => f.id === id)?.label || "待核对地点" }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "已有图片" }
let backupAccount = null
let knownBackup
try { backupAccount = localStorage.getItem(ACCOUNT_MARKER_KEY) } catch { /* Saving remains available. */ }
function backupKey() {
  if (localStorage.getItem(ACCOUNT_MARKER_KEY) !== backupAccount) throw new Error('account changed')
  return "novel_map_draft:" + (backupAccount || "local") + ":" + props.projectId + ":" + props.node.id
}
function persistDraft() {
  clearTimeout(backupTimer)
  if (recovery.value) return
  if (!dirty.value) {
    if (initialized.value && knownBackup !== undefined && !recovery.value) clearBackup(knownBackup)
    return
  }
  try {
    const value = JSON.stringify({ base_revision_id: revision.value?.id || null, document: doc.value })
    localStorage.setItem(backupKey(), value)
    if (localStorage.getItem(backupKey()) !== value) throw new Error("backup verification failed")
    knownBackup = value
    backedUp.value = true; backupError.value = false
  } catch { backedUp.value = false; backupError.value = true }
}
function clearBackup(expectedValue = knownBackup) {
  try {
    const key = backupKey()
    if (expectedValue === undefined || localStorage.getItem(key) !== expectedValue) return false
    localStorage.removeItem(key); knownBackup = null
    return true
  } catch { return false }
}
function readRecoveryValue(raw) {
  try {
    const value = raw === null ? null : JSON.parse(raw)
    if (raw !== null && !['features', 'constraints', 'images'].every(key => Array.isArray(value?.document?.[key]))) throw new Error('invalid backup')
    recovery.value = value; recoveryCorrupt.value = false
  } catch { recovery.value = {}; recoveryCorrupt.value = true }
  knownBackup = raw
}
function install(value) {
  installing = true
  revision.value = value; doc.value = copyMap(value?.document || emptyMap())
  baseline.value = JSON.stringify(doc.value); checkedGeometry.value = geometrySignature(doc.value)
  problems.value = value?.problems || []; undoStack.value = []; redoStack.value = []
  selectedId.value = doc.value.features.some(feature => feature.id === selectedId.value) ? selectedId.value : doc.value.features[0]?.id || ""; candidateView.value = null; reader.value = null
  installing = false
}
function mutate(change) {
  if (busy.value || readOnly.value || focused.value) return
  const previous = JSON.stringify(doc.value)
  change(doc.value)
  if (JSON.stringify(doc.value) === previous) return
  undoStack.value = [...undoStack.value.slice(-19), previous]; redoStack.value = []
}
function undo() { if (readOnly.value || !undoStack.value.length) return; redoStack.value.push(JSON.stringify(doc.value)); doc.value = JSON.parse(undoStack.value.pop()) }
function redo() { if (readOnly.value || !redoStack.value.length) return; undoStack.value.push(JSON.stringify(doc.value)); doc.value = JSON.parse(redoStack.value.pop()) }
function selectFeature(id) { selectedId.value = id; selectedVertex.value = 0; selectedSegment.value = 0; if (!readOnly.value) emit('select-feature', id) }
function locateChange(ids) {
  const id = ids.find(value => displayDocument.value.features.some(feature => feature.id === value))
  if (id) return locateFeature(id)
  if (candidateView.value) { compareCandidateCurrent.value = !compareCandidateCurrent.value; nextTick(() => locateFeature(ids[0])) }
}
function rememberView() {
  if (!initialized.value || !alive || readOnly.value) return
  try {
    const key = backupKey().replace('novel_map_draft:', 'novel_map_view:')
    localStorage.setItem(key, JSON.stringify({ selectedId: selectedId.value, zoom: zoom.value, focused: focused.value, left: scrollArea.value?.scrollLeft || 0, top: scrollArea.value?.scrollTop || 0, stops: rehearsalStops.value }))
  } catch { /* View preferences are optional; document saving retains its own protection. */ }
}
async function restoreView() {
  try {
    const value = JSON.parse(localStorage.getItem(backupKey().replace('novel_map_draft:', 'novel_map_view:')) || '{}')
    if (Number.isFinite(value.zoom)) zoom.value = Math.max(60, Math.min(200, value.zoom))
    focused.value = value.focused === true
    const id = props.initialFeatureId || value.selectedId
    if (doc.value.features.some(feature => feature.id === id)) selectedId.value = id
    rehearsalStops.value = Array.isArray(value.stops) ? value.stops.filter(id => typeof id === 'string').slice(0, 20) : []
    await nextTick()
    if (!alive) return
    if (scrollArea.value) { scrollArea.value.scrollLeft = Math.max(0, Number(value.left) || 0); scrollArea.value.scrollTop = Math.max(0, Number(value.top) || 0) }
    if (props.initialFeatureId) { focused.value = true; await locateFeature(props.initialFeatureId) }
  } catch { /* A broken view preference never replaces the saved map. */ }
}
function bindEntity(id) {
  const duplicate = doc.value.features.find(feature => feature.id !== selectedId.value && feature.entity_id && feature.entity_id === id)
  if (duplicate) { reviewNotice.value = `“${duplicate.label}”已关联这个世界地点，请使用现有标记，避免重复。`; return locateFeature(duplicate.id) }
  changeFeature('entity_id', id || null)
}
async function locateFeature(id) {
  selectFeature(id)
  locatorMessage.value = displayedFeature.value?.points.length ? '' : '这个地点尚未定位，可在编辑工具中放置。'
  await nextTick()
  const element = [...(canvas.value?.querySelectorAll('.map-feature') || [])].find(item => item.dataset.featureId === id)
  element?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  element?.focus?.({ preventScroll: true })
}
function changeFeature(key, value) { if (selectedFeature.value) mutate(() => { selectedFeature.value[key] = value }) }
function openSourcePicker(source = null) { sourcePickerInitial.value = source; sourcePickerOpen.value = true }
function addSource(source) {
  const feature = selectedFeature.value, key = mapSourceRangeKey(source.source_ref)
  if (!feature || !key || feature.sources.length >= 8 || feature.sources.some(item => item.kind === 'source_range' && mapSourceRangeKey(item.source_ref) === key)) return
  mutate(() => { feature.sources.push(copyMap(source)) })
}
function removeSource(index) { if (selectedFeature.value) mutate(() => { selectedFeature.value.sources.splice(index, 1) }) }
function toggleReference() { referenceOnly.value = !referenceOnly.value; emit("reference-visible", referenceOnly.value) }
function startPan(event) {
  if (event.button !== 0 || event.pointerType === 'touch' || placing.value || drag || !scrollArea.value || !(event.target === canvas.value || event.target.classList?.contains('map-paper') || event.target.localName === 'polygon')) return
  pan = { x: event.clientX, y: event.clientY, left: scrollArea.value.scrollLeft, top: scrollArea.value.scrollTop, pointerId: event.pointerId, featureId: event.target.closest('.map-feature')?.dataset.featureId, moved: false }
  panning.value = true; event.preventDefault(); scrollArea.value.setPointerCapture?.(event.pointerId)
}
function movePan(event) {
  if (!pan || pan.pointerId !== event.pointerId) return
  if (Math.hypot(pan.x - event.clientX, pan.y - event.clientY) > 4) pan.moved = true
  scrollArea.value.scrollLeft = pan.left + pan.x - event.clientX
  scrollArea.value.scrollTop = pan.top + pan.y - event.clientY
}
function endPan(event) { if (pan?.featureId && !pan.moved && event?.type !== 'pointercancel') selectFeature(pan.featureId); pan = null; panning.value = false; rememberView() }
function panByKey(event) {
  const delta = { ArrowLeft: [-80, 0], ArrowRight: [80, 0], ArrowUp: [0, -80], ArrowDown: [0, 80] }[event.key]
  if (!delta) return
  event.preventDefault(); scrollArea.value.scrollLeft += delta[0]; scrollArea.value.scrollTop += delta[1]; rememberView()
}
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
  if (event.pointerType === 'touch' && !event.target.classList?.contains('map-handle')) return
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
  if (!selectedFeature.value || selectedFeature.value.locked || !canRemovePoint.value) return
  mutate(() => { selectedFeature.value.points.splice(selectedVertex.value, 1) })
  selectedVertex.value = Math.max(0, Math.min(selectedVertex.value, selectedFeature.value.points.length - 1))
  selectedSegment.value = Math.max(0, Math.min(selectedSegment.value, selectedSegments.value.length - 1))
}
function insertPoint() {
  const feature = selectedFeature.value, segment = selectedSegments.value[selectedSegment.value]
  if (!segment || feature.locked || feature.points.length >= 128) return
  const index = selectedSegment.value + 1
  mutate(() => feature.points.splice(index, 0, { x: (segment[0].x + segment[1].x) / 2, y: (segment[0].y + segment[1].y) / 2 }))
  selectedVertex.value = index
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
    if (error.value === lastLoadError) error.value = ''
    lastLoadError = ''
    serverRevision.value = result.revision; candidates.value = result.candidates; imageLayers.value = result.image_layers || []
    taskId.value = result.task_id; taskStatus.value = result.task_status; generationSummary.value = result.generation_summary || null
    if (!initialized.value) {
      install(result.revision); initialized.value = true; await restoreView()
      try { readRecoveryValue(localStorage.getItem(backupKey())) } catch { backupError.value = true }
      if (recovery.value && JSON.stringify(recovery.value.document) === baseline.value) recovery.value = null
    } else if (!dirty.value && !candidateView.value && revision.value?.id !== result.revision?.id) install(result.revision)
    else if (!dirty.value && !candidateView.value) problems.value = result.revision?.problems || []
    await loadLayerImages()
    if (initial && props.initialRevisionId && props.initialRevisionId !== result.revision?.id) {
      const preview = await api.world.previewMapRevision(props.projectId, props.node.id, props.initialRevisionId)
      if (!alive || token !== epoch) return
      await viewCandidate({ ...preview, id: props.initialRevisionId, status: 'saved' }, preview)
    }
  } catch (err) { if (alive && token === epoch) error.value = lastLoadError = err.message || "地图读取失败" }
  finally { if (alive && token === epoch) { loading.value = false; if (taskRunning.value) { clearTimeout(pollTimer); pollTimer = setTimeout(() => load(), 2500) } } }
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
  if (busy.value || readOnly.value) return
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
async function generate() { return generateSelection([...selectedLocationIds.value], []) }
async function generateExisting() { return generateSelection([], [...selectedFeatureIds.value]) }
async function cancelGeneration() {
  const id = taskId.value
  if (!id || !taskRunning.value || busy.value || cancelling.value) return
  cancelling.value = true; error.value = ''
  try {
    const result = await api.tasks.cancel(id, props.projectId)
    if (!alive || taskId.value !== id) return
    taskStatus.value = result.status; generationSummary.value = null
    await load()
  } catch (err) { if (alive && taskId.value === id) error.value = err.message || '停止整理失败，请重试。已保存地图仍保留。' }
  finally { if (alive) cancelling.value = false }
}
async function showGenerationChoices() {
  focused.value = false; referenceOnly.value = false; emit('reference-visible', false); await nextTick()
  if (!generationTools.value) return
  generationTools.value.open = true; generationTools.value.scrollIntoView?.({ block: 'start' }); generationTools.value.querySelector('input')?.focus()
}
async function generateSelection(locationIds, featureIds) {
  if (dirty.value || busy.value || taskRunning.value || recovery.value) return
  saving.value = true; error.value = ""
  try {
    const selected = (revision.value?.document.features || []).filter(feature => featureIds.includes(feature.id))
    const confirmation = await confirmAiReference({ novel_id: props.projectId, action: "world.map_atlas.structure", scope: "full", task: "整理地图空间关系", entity_ids: [...new Set([...locationIds, ...selected.map(feature => feature.entity_id).filter(Boolean)])], pinned_refs: [...props.evidenceRefs, ...mapSourceSelections(selected)], include_pending_objects: false, budget_tokens: 12000 })
    if (!alive) return
    const result = await api.world.generateMapStructure(props.projectId, props.node.id, { operation_id: crypto.randomUUID(), base_revision_id: revision.value?.id || null, context_confirmation_id: confirmation.id, location_ids: locationIds, feature_ids: featureIds })
    if (!alive) return
    taskId.value = result.task_id; taskStatus.value = result.status; generationSummary.value = null; await load()
  } catch (err) { if (err.message !== "已取消 AI 参考资料确认") error.value = err.message || "空间整理暂时不可用" }
  finally { if (alive) saving.value = false }
}
async function viewCandidate(value, existingPreview = null) {
  const token = ++comparisonEpoch
  if (dirty.value && !confirm('比较地图版本时会保留当前编辑，是否继续？')) return
  compareServer.value = false; candidateView.value = value; compareCandidateCurrent.value = false; reader.value = null; referenceOnly.value = false; focused.value = false; emit('reference-visible', false); problems.value = value.problems || []
  selectedChangeKeys.value = candidateChanges.value.map(change => change.key); comparisonLayers.value = []
  try {
    const preview = existingPreview || await api.world.previewMapRevision(props.projectId, props.node.id, value.id)
    if (!alive || token !== comparisonEpoch || candidateView.value?.id !== value.id) return
    comparisonLayers.value = preview.image_layers || []; problems.value = preview.problems || []
    await Promise.all(comparisonLayers.value.filter(layer => layer.state === 'ready').map(layer => loadImage(layer.page_id)))
  } catch (err) { if (alive && token === comparisonEpoch && candidateView.value?.id === value.id) error.value = err.message || '版本图片读取失败，结构仍可比较' }
}
function exitCandidate() { ++comparisonEpoch; candidateView.value = null; compareCandidateCurrent.value = false; problems.value = serverRevision.value?.problems || revision.value?.problems || [] }
async function previewAdoption() {
  const value = candidateView.value, baseId = revision.value?.id || null, keys = [...selectedChangeKeys.value]
  if (!value || value.status !== 'candidate' || value.base_revision_id !== baseId || busy.value || dirty.value || recovery.value || !keys.length) return
  const token = ++reviewEpoch
  adoptionPreview.value = null; previewing.value = true; error.value = ''; reviewNotice.value = ''
  try {
    const result = await api.world.previewMapReview(props.projectId, props.node.id, value.id, { base_revision_id: baseId, action: 'adopt', change_keys: keys })
    if (!alive || token !== reviewEpoch) return
    if (result.candidate_revision_id !== value.id || result.base_revision_id !== baseId || !Array.isArray(result.applied_change_keys) || !Array.isArray(result.expanded_change_keys) || !result.applied_change_keys.length || result.applied_change_keys.some(key => !candidateChanges.value.some(change => change.key === key))) throw new Error('采用范围与当前候选不一致，请重新核对。')
    adoptionPreview.value = result
  } catch (err) {
    if (!alive || token !== reviewEpoch) return
    error.value = err.message || '采用范围暂时无法核对，请重试。'
    explainRequiredChanges(err)
  } finally { if (alive && token === reviewEpoch) previewing.value = false }
}
function explainRequiredChanges(err) {
  const required = err.body?.context?.required_change_keys || err.body?.detail?.context?.required_change_keys || []
  if (required.length) reviewNotice.value = '请明确勾选关联修改后再采用：' + candidateChanges.value.filter(change => required.includes(change.key)).map(change => change.label).join('、')
}
async function review(value, action, changeKeys = null) {
  if (busy.value || dirty.value || recovery.value) return
  if (action === 'adopt' && (!adoptionPreview.value || adoptionPreview.value.candidate_revision_id !== value.id || adoptionPreview.value.base_revision_id !== (revision.value?.id || null))) return
  if (action === "restore" && !confirm("将历史地图恢复为新版本？当前版本仍保留在历史中。")) return
  if (action === "reject" && !confirm("不使用这个空间候选？已保存地图不会受到影响。")) return
  saving.value = true
  try {
    const result = await api.world.reviewMapRevision(props.projectId, props.node.id, value.id, { base_revision_id: revision.value?.id || null, action, ...(changeKeys ? { change_keys: changeKeys } : {}) })
    if (!alive) return
    if (action !== "reject") { install(result); serverRevision.value = result; clearBackup(); emit("saved") }
    reviewNotice.value = action === 'adopt' ? `已采用 ${result.applied_change_keys?.length || changeKeys?.length || '全部'} 项修改${result.expanded_change_keys?.length ? '，并一并处理 ' + result.expanded_change_keys.length + ' 项依赖' : ''}。${result.remaining_candidate_id ? '其余修改仍待确认。' : ''}` : action === 'restore' ? '历史地图已恢复为新版本，原有历史仍保留。' : '候选已移入历史。'
    candidateView.value = null; await load()
  } catch (err) {
    error.value = err.message || "版本操作失败，当前地图仍保留"
    adoptionPreview.value = null; explainRequiredChanges(err)
  }
  finally { if (alive) saving.value = false }
}
async function loadHistory() { try { history.value = await api.world.listMapRevisions(props.projectId, props.node.id) } catch (err) { error.value = err.message || "历史读取失败" } }
async function compareImageRevision(id) {
  if (!id) return
  const token = ++comparisonEpoch
  try {
    const preview = await api.world.previewMapRevision(props.projectId, props.node.id, id)
    if (!alive || token !== comparisonEpoch || ![selectedImageRevision.value, selectedCalibrationRevision.value].includes(id)) return
    await viewCandidate({ id, status: 'saved', document: preview.document, problems: preview.problems }, preview)
  } catch (err) { if (alive && token === comparisonEpoch) error.value = err.message || '图片来源地图暂时无法读取，请重试。' }
}
async function loadImageBaseline() {
  const id = imageBaselineRevision.value, token = ++imageBaselineEpoch
  imageBaseline.value = null; imageBaselineStatus.value = id ? 'loading' : 'unknown'
  if (!id) return
  try {
    const preview = await api.world.previewMapRevision(props.projectId, props.node.id, id)
    if (!alive || token !== imageBaselineEpoch) return
    imageBaseline.value = preview; imageBaselineStatus.value = 'ready'
  } catch { if (alive && token === imageBaselineEpoch) imageBaselineStatus.value = 'error' }
}
function restoreBackup() {
  if (!recovery.value || recoveryCorrupt.value || busy.value || !recoveryIsCurrent()) return
  if (!Array.isArray(recovery.value.document?.features) || !Array.isArray(recovery.value.document?.constraints) || !Array.isArray(recovery.value.document?.images)) { error.value = "本机备份格式已损坏，服务器版本仍然保留。"; return }
  doc.value = copyMap(recovery.value.document)
  if (recovery.value.base_revision_id !== (revision.value?.id || null)) {
    revision.value = { ...(revision.value || {}), id: recovery.value.base_revision_id }; conflict.value = true
  }
  recovery.value = null; discardBackupOpen.value = false; reader.value = null; exitCandidate(); compareServer.value = false; persistDraft(); nextTick(() => scrollArea.value?.focus())
}
function recoveryIsCurrent() {
  try {
    const raw = localStorage.getItem(backupKey())
    if (raw === knownBackup) return true
    readRecoveryValue(raw); discardBackupOpen.value = false
    reviewNotice.value = '本机备份已在另一处变化，未替换或放弃任何编辑。请核对后重新选择。'
  } catch { reviewNotice.value = '本机备份暂时无法核对，仍保留原内容。请稍后再试。' }
  return false
}
function discardBackup() { discardBackupOpen.value = true; nextTick(() => discardBackupConfirm.value?.focus()) }
function cancelDiscardBackup() { discardBackupOpen.value = false; nextTick(() => discardBackupTrigger.value?.focus()) }
function confirmDiscardBackup() {
  if (!recovery.value || busy.value || !recoveryIsCurrent()) return
  if (!clearBackup()) { reviewNotice.value = '本机备份暂时无法清理，未放弃任何编辑。请重新核对后再试。'; return }
  recovery.value = null; recoveryCorrupt.value = false; discardBackupOpen.value = false; reviewNotice.value = '已放弃这份本机编辑，已保存地图和历史仍保留。'; nextTick(() => scrollArea.value?.focus())
}
function useServer() { if (!recovery.value && confirm("使用服务器版？当前编辑将从工作区移出。")) { install(serverRevision.value); clearBackup(); conflict.value = false; compareServer.value = false } }
function rebaseManually() {
  if (recovery.value) return
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
async function loadSelectedImage() { if (imageForm.page_id) await loadImage(imageForm.page_id); if (imageBaselineStatus.value === 'error') await loadImageBaseline() }
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
    const child = await api.world.createMapNode(props.projectId, { title: feature.label, level: childLevel.value.value, parent_id: props.node.id, location_entity_id: feature.entity_id || null })
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
function beforeUnload(event) { persistDraft(); if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = "" } }
watch(doc, () => {
  if (installing || !initialized.value) return
  backedUp.value = false; clearTimeout(backupTimer); backupTimer = setTimeout(persistDraft, 200)
}, { deep: true, flush: "sync" })
watch(canvas, (element, previous) => { if (previous) resizeObserver?.unobserve(previous); if (element) resizeObserver?.observe(element) })
watch(() => props.reviewImageId, id => { if (!dirty.value) { referenceOnly.value = Boolean(id); emit("reference-visible", referenceOnly.value) } }, { immediate: true })
watch([dirty, revision, reader, focused], () => emit("state", { dirty: dirty.value, revision: revision.value, reader: Boolean(reader.value), focused: focused.value }), { immediate: true })
watch([selectedId, zoom, focused, rehearsalStops], rememberView, { deep: true })
watch([selectedId, busy, focused, readOnly], () => { sourcePickerOpen.value = false }, { flush: 'sync' })
watch([candidateView, () => revision.value?.id, () => serverRevision.value?.id, selectedChangeKeys], () => { ++reviewEpoch; adoptionPreview.value = null; previewing.value = false }, { deep: true, flush: 'sync' })
watch([() => imageForm.page_id, imageBaselineRevision, imageBaselineKind], loadImageBaseline)
watch([() => imageForm.page_id, selectedImageRevision, selectedCalibrationRevision], () => { ++comparisonEpoch }, { flush: 'sync' })
watch(reader, value => { if (value) ++comparisonEpoch }, { flush: 'sync' })
watch(() => relation.relation, () => { if (!relationSubjects.value.some(item => item.id === relation.subject)) relation.subject = ''; if (!relationTargets.value.some(item => item.id === relation.target)) relation.target = '' })
onMounted(() => {
  load(true); globalThis.addEventListener("beforeunload", beforeUnload)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(entries => { canvasWidth.value = entries[0]?.contentRect.width || 700; canvasHeight.value = entries[0]?.contentRect.height || 0 })
    if (canvas.value) resizeObserver.observe(canvas.value)
  }
})
onBeforeUnmount(() => { rememberView(); resizeObserver?.disconnect(); persistDraft(); alive = false; epoch += 1; clearTimeout(backupTimer); clearTimeout(pollTimer); globalThis.removeEventListener("beforeunload", beforeUnload); for (const url of Object.values(imageUrls)) URL.revokeObjectURL(url) })
defineExpose({ canLeave, save, dirty, revision })
</script>

<style scoped>
.map-recovery button{min-height:44px}.map-recovery-confirm{padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md)}
.map-feature-sources{display:grid;gap:var(--space-2);padding-block:var(--space-3);border-block:1px solid var(--border)}.map-feature-sources article>p{max-height:8rem;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}.map-feature-sources button{min-height:44px}
.map-editor{display:grid;gap:var(--space-3);min-width:0}.map-toolbar,.map-actions,.map-reader,.map-canvas-controls,.map-history,.map-candidates>div{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}.map-toolbar{justify-content:space-between}.map-caption,.map-save-status{color:var(--text-secondary);font-size:var(--text-sm)}.map-caption{display:block;margin-top:var(--space-1)}.map-toolbar .map-caption{display:inline;margin-left:var(--space-2)}.map-editor>p{margin:0}.map-editor .map-save-status{font-size:var(--text-xs)}.map-actions .btn,.map-editor summary{min-height:44px}.map-editor label{display:grid;gap:var(--space-1);min-width:0}.map-editor details{padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md);min-width:0}.map-editor summary{cursor:pointer;font-weight:600}.map-inline-form{display:flex;align-items:end;flex-wrap:wrap;gap:var(--space-2);margin-block:var(--space-2)}.map-inline-form>label{flex:1 1 140px}.map-editor input,.map-editor select,.map-editor textarea{max-width:100%;min-width:0}.map-editor input[type=number]{width:100px;min-height:36px}.map-reader>label{display:flex;align-items:center;flex-wrap:wrap}.map-edit-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,320px);gap:var(--space-3)}.map-inspector{display:grid;align-content:start;gap:var(--space-2);padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md)}.map-scroll{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-base)}.map-canvas{display:block;min-width:320px;min-height:300px;max-width:none;touch-action:pan-x pan-y pinch-zoom}.map-paper{fill:var(--bg-base)}.map-feature{cursor:pointer;outline:none}.map-feature circle{fill:var(--accent);stroke:var(--bg-base);stroke-width:3}.map-feature polygon{fill:var(--bg-muted);stroke:var(--border);stroke-width:2}.map-feature polyline{fill:none;stroke:var(--text-secondary);stroke-width:3;stroke-dasharray:7 4}.map-kind-river polyline{stroke:var(--accent);stroke-width:5;stroke-dasharray:none}.map-feature text{fill:var(--text-primary);font-size:15px;paint-order:stroke;stroke:var(--bg-base);stroke-width:4;stroke-linejoin:round}.map-feature:focus circle,.map-feature.selected circle{stroke:var(--text-primary);stroke-width:4}.map-feature:focus polyline,.map-feature.selected polyline,.map-feature:focus polygon,.map-feature.selected polygon{stroke:var(--accent);stroke-width:4}.map-feature .map-hit{fill:transparent;stroke:none;cursor:move}.map-handle{fill:var(--bg-base);stroke:var(--accent);stroke-width:3;cursor:move;touch-action:none}.map-location-list{display:grid;gap:var(--space-1);max-height:220px;overflow:auto}.map-location-list label{display:flex;align-items:center;gap:var(--space-2);min-height:38px}.map-warning{padding:var(--space-3);background:var(--warning-soft);border:1px solid var(--warning);border-radius:var(--radius-md)}.map-error{color:var(--error)}.map-calibration{position:relative;max-width:500px;cursor:crosshair}.map-calibration img{display:block;width:100%;height:auto}.map-calibration span{position:absolute;transform:translate(-50%,-50%);background:var(--text-primary);color:var(--bg-base);border-radius:50%;width:24px;height:24px;text-align:center;pointer-events:none}.map-detail-image{max-width:100%;height:auto;border-radius:var(--radius-md)}.map-history{padding:var(--space-2);justify-content:space-between}
@media(max-width:900px){.map-edit-grid{grid-template-columns:minmax(0,1fr)}.map-toolbar{align-items:stretch;flex-direction:column}.map-reader{align-items:start}.map-editor .form-input,.map-editor .form-select{width:100%}.map-canvas-controls{justify-content:space-between}.map-candidates>div{align-items:start}.map-editor details{padding:var(--space-2)}}
.map-illustration-preview{display:block;max-width:100%;width:280px;max-height:210px;object-fit:contain;border-radius:var(--radius-md)}
.map-rehearsal-line{fill:none;stroke:var(--accent);stroke-width:7;stroke-opacity:.45;stroke-dasharray:12 6}.map-feature.rehearsed circle:not(.map-hit){stroke:var(--accent);stroke-width:5}.map-facing-line{fill:none;stroke:var(--accent);stroke-width:3;stroke-dasharray:4 5}.map-facing-head{fill:var(--accent)}
.map-navigation{display:grid;gap:var(--space-2)}.map-locator{min-width:0}.map-locator .map-actions{max-height:132px;overflow:auto}.map-focused{gap:var(--space-2)}.map-focused .map-toolbar{flex-direction:row;align-items:center}.map-focused .map-toolbar>div:first-child{min-width:0;overflow-wrap:anywhere}.map-focused .map-navigation{display:flex;align-items:start;flex-wrap:wrap}.map-focused .map-canvas-controls{flex:0 1 auto;min-height:44px}.map-focused .map-canvas-controls label{display:flex;align-items:center;gap:var(--space-2)}.map-focused .map-locator{flex:1 1 200px}.map-focused .map-locator>label{display:flex;align-items:center;gap:var(--space-2);font-size:var(--text-sm);white-space:nowrap}.map-focused .map-locator input{flex:1;min-width:0;width:100px}.map-focused .map-scroll{max-height:max(300px,calc(100dvh - 240px))}.map-focused .map-canvas{min-width:0;height:calc(var(--map-zoom, 1) * max(300px,100dvh - 240px))}.map-focused .map-hit{cursor:pointer}
@media(max-width:900px){.map-focused .map-canvas{height:auto}}
.map-scroll{touch-action:pan-x pan-y pinch-zoom}.map-scroll.panning{cursor:grabbing;user-select:none}.map-paper{cursor:grab}.map-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.map-segment{stroke:transparent;cursor:pointer}.map-segment.selected{stroke:var(--accent);stroke-opacity:.2}.map-handle.selected{fill:var(--accent)}.map-feature.selected text{font-weight:700}.map-adoption-preview{padding:var(--space-3);border:1px solid var(--border);border-radius:var(--radius-md)}
.map-generation-feedback{display:grid;gap:var(--space-2);padding:var(--space-2);border:1px solid var(--border);border-radius:var(--radius-md)}.map-generation-feedback>p{margin:0}.map-generation-feedback>.btn{justify-self:start}.map-generation-feedback dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--space-1) var(--space-3)}.map-generation-feedback dd{margin:0}.map-generation-feedback summary{font-size:var(--text-sm)}
</style>
