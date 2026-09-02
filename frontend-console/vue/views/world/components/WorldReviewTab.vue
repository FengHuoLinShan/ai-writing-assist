<!--
  WorldReviewTab — world review（待处理）三队列：review-objects / review-aliases /
  review-relations（vanilla _renderReviewQueue 及各工作区的 Vue 化）。
  筛选变更一律 navigate 写 query；草稿/错误/批量选择落 worldSession；
  候选乐观更新走本地镜像（props 只读），钩子注册进 worldEntityOps。
-->
<template>
  <div class="world-review-view">
    <div class="subnav subnav-secondary world-review-tabs">
      <button type="button" class="subnav-item" :class="{ active: tab === 'all' }" :aria-current="tab === 'all' ? 'page' : undefined" data-action="nav-review-all" @click="navigateKind('all')">全部</button>
      <button type="button" class="subnav-item" :class="{ active: tab === 'objects' }" :aria-current="tab === 'objects' ? 'page' : undefined" data-action="nav-review-objects" @click="navigateKind('objects')">对象 ({{ reviewCounts.objects || 0 }})</button>
      <button type="button" class="subnav-item" :class="{ active: tab === 'aliases' }" :aria-current="tab === 'aliases' ? 'page' : undefined" data-action="nav-review-aliases" @click="navigateKind('aliases')">别名 ({{ reviewCounts.aliases || 0 }})</button>
      <button type="button" class="subnav-item" :class="{ active: tab === 'relations' }" :aria-current="tab === 'relations' ? 'page' : undefined" data-action="nav-review-relations" @click="navigateKind('relations')">关系 ({{ reviewCounts.relations || 0 }})</button>
    </div>

    <p v-if="tab === 'all' && currentReviewCount" class="world-list-description" data-author-action="needs_decision">
      <span class="pill pill-warning">需要决定</span>
      这里只列当前仍有效、尚未采用的候选；已采用、忽略或过期内容不计入当前待办。
    </p>

    <section v-if="tab === 'all'" class="world-review-overview" aria-labelledby="review-overview-title">
      <div class="world-review-next">
        <span class="pill pill-warning">推荐下一项</span>
        <h2 id="review-overview-title">{{ recommendedKind.label }}</h2>
        <p>{{ recommendedKind.description }}</p>
        <button v-if="recommendedKind.kind" type="button" class="btn btn-primary world-review-touch-target" data-action="open-recommended-review" @click="navigateKind(recommendedKind.kind)">开始处理</button>
      </div>
      <div class="world-review-overview__cards">
        <button v-for="item in overviewKinds" :key="item.kind" type="button" class="world-review-overview-card" :disabled="!item.count" @click="navigateKind(item.kind)">
          <span>{{ item.label }}</span><strong>{{ item.count }}</strong><small>{{ item.hint }}</small>
        </button>
      </div>
    </section>

    <div v-else class="world-review-workbench" :class="{ 'is-detail-open': mobileDetailOpen }">
      <section class="world-review-queue" aria-label="待决定队列">
    <!-- ==================== review-objects ==================== -->
    <template v-if="tab === 'objects'">
      <p class="world-list-description">确认尚未采用的人物与设定是否进入长期资料；可先搜索名称、别名或描述。</p>
      <div class="review-search-bar">
        <input id="review-candidate-q" v-model="candidateForm.q" class="form-input" placeholder="搜索对象、别名或描述" aria-label="搜索待处理对象" @keyup.enter="applyCandidateFilters" />
        <button class="btn btn-sm" data-action="apply-candidate-review-filters" @click="applyCandidateFilters">搜索</button>
        <button v-if="candidateForm.q" type="button" class="btn btn-sm" data-action="clear-candidate-review-search" @click="clearReviewKeyword('candidate')">清除搜索</button>
      </div>
      <div class="world-review-quick-row">
        <span id="review-candidate-quick-label" class="world-review-quick-label">快速查看</span>
        <div class="review-quick-filters" role="group" aria-labelledby="review-candidate-quick-label">
          <button v-for="task in candidateTasks" :key="task.value" type="button" class="btn btn-sm" :class="{ 'is-active': candidateFilters.suggested_action === task.value }" data-action="set-candidate-task-filter" :data-filter-value="task.value" :aria-pressed="candidateFilters.suggested_action === task.value" @click="setCandidateTaskFilter(task.value, candidateFilters)">{{ task.label }}</button>
        </div>
      </div>
      <div v-if="candidateActiveFilterCount" class="world-review-active-filters"><span>已启用 {{ candidateActiveFilterCount }} 个条件</span><WorldReviewFilterChips kind="candidate" :filters="candidateFilters" /><button type="button" class="btn btn-sm" data-action="reset-candidate-review-filters" @click="resetCandidateReviewFilters">清除全部条件</button></div>
      <WorldFilterPanel panel-key="review-objects" :has-active-filters="candidateHasActiveFilters" :project-id="projectId" toggle-label="更多筛选" collapse-label="收起更多筛选">
        <div class="filter-bar world-review-filters">
          <label class="form-group"><span>对象类型</span><select id="review-candidate-entity-type" v-model="candidateForm.entity_type" class="form-select" aria-label="对象类型筛选"><option value="">全部类型</option><option v-for="type in entityTypes" :key="type.value" :value="type.value">{{ type.label }}</option></select></label>
          <label class="form-group"><span>建议动作</span><select id="review-candidate-action" v-model="candidateForm.suggested_action" class="form-select" aria-label="建议动作筛选"><option value="">全部建议</option><option v-for="action in candidateActionOptions" :key="action.value" :value="action.value">{{ action.label }}</option></select></label>
          <label class="form-group"><span>场景序号</span><input id="review-candidate-scene" v-model="candidateForm.scene_index" class="form-input" inputmode="numeric" aria-label="场景序号筛选" /></label>
          <label class="form-group"><span>章节序号</span><input id="review-candidate-chapter" v-model="candidateForm.source_chapter_index" class="form-input" inputmode="numeric" aria-label="章节筛选" /></label>
          <label class="form-group"><span>最低置信度</span><input id="review-candidate-confidence-min" v-model="candidateForm.confidence_min" class="form-input" inputmode="decimal" aria-label="最低置信度" /></label>
          <label class="form-group"><span>最高置信度</span><input id="review-candidate-confidence-max" v-model="candidateForm.confidence_max" class="form-input" inputmode="decimal" aria-label="最高置信度" /></label>
          <button class="btn btn-sm" data-action="apply-candidate-review-filters" @click="applyCandidateFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-candidate-review-filters" @click="resetCandidateReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>
      <p class="world-review-result-summary" role="status">当前结果：{{ candidateTotal }} 条对象</p>
      <WorldBulkToolbar
        v-if="!candidateLoadError"
        scope="world-candidates"
        :actions="[
          { action: 'accept-candidates', label: '批量采用', className: 'btn-primary' },
          { action: 'ignore-candidates', label: '批量忽略/设为临时', className: 'btn-danger' },
        ]"
        noun="待处理项"
        hint="合并项仍需逐条选择目标对象"
        :select-all-ids="localCandidates.map(entityIdOf)"
        select-all-label="全选当前页"
        @run="(action) => runReviewBulkAction('world-candidates', action, localCandidates)"
      />

      <template v-if="candidateLoadError && localCandidates.length === 0">
        <div class="empty-state" role="alert" data-author-action="must_fix">
          <strong>待决定对象没有加载出来</strong>
          <p>原有资料没有变化，可以重新加载。</p>
          <button class="btn btn-primary world-review-touch-target" data-action="retry-candidate-load" @click="retryLoad">重新加载</button>
          <details class="review-error-details"><summary>诊断信息</summary><p>{{ candidateLoadError }}</p></details>
        </div>
      </template>
      <template v-else-if="localCandidates.length === 0 && initialReviewItem">
        <div class="empty-state">
          <strong>这条建议已不在待处理队列</strong>
          <p>它可能已经采用、忽略或被新版本替代；当前世界资料没有被自动修改。</p>
          <div class="row-actions">
            <button type="button" class="btn btn-primary world-review-touch-target" @click="navigateKind('objects')">查看其他待处理对象</button>
            <button v-if="returnToWorldAi" type="button" class="btn world-review-touch-target" data-action="return-to-world-ai" @click="returnToAiWorkspace">返回设定共创</button>
          </div>
        </div>
      </template>
      <template v-else-if="localCandidates.length === 0">
        <div class="empty-state">
          <p>没有待处理对象。</p>
          <p>AI 或导入提出、尚未采用的对象会出现在这里，你可以决定如何处置。</p>
        </div>
      </template>
      <template v-else>
        <!-- 建议设为别名分组（vanilla _renderTargetedAliasCandidateGroups） -->
        <div v-if="targetedAliasGroups.length" class="world-candidate-alias-groups" aria-label="建议设为别名的待处理对象">
          <section v-for="group in targetedAliasGroups" :key="group.targetId || `name:${group.targetName}`" class="world-candidate-alias-group" :data-target-id="group.targetId">
            <header class="world-candidate-alias-group__header">
              <div>
                <div class="world-candidate-alias-group__target">
                  <span class="badge badge-canonical">已有对象</span>
                  <strong>{{ group.targetLabel }}</strong>
                </div>
                <p>以下 {{ group.candidates.length }} 个候选建议作为{{ group.targetLabel }}别名</p>
              </div>
              <span class="world-candidate-alias-group__select-all">
                <WorldSelectionInput mode="all" scope="world-candidates" :ids="group.ids" :label="`全选建议并入 ${group.targetLabel} 的条目`" />
                <span>全选本组</span>
              </span>
            </header>
            <div class="world-candidate-alias-group__items">
              <WorldCandidateGroupItem v-for="candidate in group.candidates" :key="entityIdOf(candidate)" :candidate="candidate" badge-label="建议别名" :active="activeKey === entityIdOf(candidate)" @select="selectReviewItem" />
            </div>
          </section>
        </div>

        <!-- 名称相似分组（vanilla _renderSimilarNameCandidateGroups） -->
        <div v-if="similarNameGroups.length" class="world-candidate-alias-groups" aria-label="名称相似的待处理对象">
          <section v-for="(group, index) in similarNameGroups" :key="index" class="world-candidate-alias-group world-candidate-similar-group">
            <header class="world-candidate-alias-group__header">
              <div>
                <div class="world-candidate-alias-group__target">
                  <span class="badge badge-draft">名称相似</span>
                  <strong>{{ similarGroupTypeLabel(group) }}</strong>
                </div>
                <p>以下 {{ group.length }} 个待处理对象合并展示，请逐条决定采用、设为别名、合并或忽略</p>
              </div>
              <span class="world-candidate-alias-group__select-all">
                <WorldSelectionInput mode="all" scope="world-candidates" :ids="group.map(entityIdOf)" label="全选本组相似名称条目" />
                <span>全选本组</span>
              </span>
            </header>
            <div class="world-candidate-alias-group__items">
              <WorldCandidateGroupItem v-for="candidate in group" :key="entityIdOf(candidate)" :candidate="candidate" badge-label="相似名称" :active="activeKey === entityIdOf(candidate)" @select="selectReviewItem" />
            </div>
          </section>
        </div>

        <!-- 普通候选表（vanilla _renderCandidatesList 1930-1976） -->
        <table v-if="regularCandidates.length" class="data-table table-card-list">
          <thead>
            <tr>
              <th class="selection-cell"><WorldSelectionInput mode="all" scope="world-candidates" :ids="regularCandidates.map(entityIdOf)" label="全选普通待处理项" /></th>
              <th>待处理对象</th>
              <th>AI 建议</th>
              <th>来源</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="candidate in regularCandidates" :key="entityIdOf(candidate)" :data-id="entityIdOf(candidate)" :class="{ 'is-active': activeKey === entityIdOf(candidate) }" tabindex="0" @click="selectReviewItem(entityIdOf(candidate), $event)" @keydown.enter.self="selectReviewItem(entityIdOf(candidate), $event)" @keydown.space.prevent.self="selectReviewItem(entityIdOf(candidate), $event)">
              <td class="selection-cell"><WorldSelectionInput mode="one" scope="world-candidates" :id="entityIdOf(candidate)" :label="`选择 ${candidate.name || '待处理项'}`" /></td>
              <td data-label="待处理对象" class="world-review-candidate-cell">
                <strong>{{ candidate.name || "未命名对象" }}</strong>
                <span>{{ entityTypeLabel(candidate.entity_type) }}<template v-if="candidateImportanceText(candidate)"> · {{ candidateImportanceText(candidate) }}</template></span>
                <p v-if="candidateSummary(candidate)">{{ candidateSummary(candidate) }}</p>
              </td>
              <td data-label="AI 建议"><span class="candidate-action-badge" :class="`candidate-action-badge--${actionLabelOf(candidate).action}`">{{ actionLabelOf(candidate).label }}</span></td>
              <td data-label="来源" class="world-review-evidence-cell"><WorldInlineEvidence v-if="candidateEvidence(candidate).length" :pairs="candidateEvidence(candidate)" /><span v-else>未附来源</span></td>
              <td data-label="操作"><button type="button" class="btn btn-sm world-review-queue-action" data-action="prepare-candidate-review" :data-id="entityIdOf(candidate)" @click.stop="selectReviewItem(entityIdOf(candidate), $event)">查看并决定</button></td>
            </tr>
          </tbody>
        </table>

        <WorldPager
          :total="candidateTotal"
          :skip="candidateFilters.skip"
          :limit="candidateFilters.limit"
          prev-action="prev-candidates-page"
          next-action="next-candidates-page"
          @change="(delta) => changeReviewPage('candidates', delta, candidateFilters, candidateTotal)"
        />
      </template>
    </template>

    <!-- ==================== review-aliases ==================== -->
    <template v-else-if="tab === 'aliases'">
      <p class="world-list-description">确认尚未采用的名称应归属到哪个对象；别名不会独立创建对象。</p>
      <div class="review-search-bar">
        <input id="review-alias-q" v-model="aliasForm.q" class="form-input" placeholder="搜索别名、对象或引用" aria-label="搜索待处理别名" @keyup.enter="applyAliasFilters" />
        <button class="btn btn-sm" data-action="apply-alias-review-filters" @click="applyAliasFilters">搜索</button>
        <button v-if="aliasForm.q" type="button" class="btn btn-sm" data-action="clear-alias-review-search" @click="clearReviewKeyword('alias')">清除搜索</button>
      </div>
      <div class="world-review-quick-row">
        <span id="review-alias-quick-label" class="world-review-quick-label">快速查看</span>
        <div class="review-quick-filters" role="group" aria-labelledby="review-alias-quick-label">
          <button v-for="task in aliasTasks" :key="task.key" type="button" class="btn btn-sm" :class="{ 'is-active': String(aliasReviewFilters[task.key] || '') === task.value }" data-action="set-alias-quick-filter" :data-filter-key="task.key" :data-filter-value="task.value" :aria-pressed="String(aliasReviewFilters[task.key] || '') === task.value" @click="setReviewQuickFilter('alias', task.key, task.value, aliasReviewFilters)">{{ task.label }}</button>
        </div>
      </div>
      <div v-if="aliasActiveFilterCount" class="world-review-active-filters"><span>已启用 {{ aliasActiveFilterCount }} 个条件</span><WorldReviewFilterChips kind="alias" :filters="aliasReviewFilters" :review-type-catalog="reviewTypeCatalog" /><button type="button" class="btn btn-sm" data-action="reset-alias-review-filters" @click="resetAliasReviewFilters">清除全部条件</button></div>
      <WorldFilterPanel panel-key="review-aliases" :has-active-filters="aliasHasActiveFilters" :project-id="projectId" toggle-label="更多筛选" collapse-label="收起更多筛选">
        <div class="filter-bar world-review-filters">
          <label class="form-group"><span>场景序号</span><input id="review-alias-scene" v-model="aliasForm.scene_index" class="form-input" inputmode="numeric" aria-label="按场景序号筛选待处理别名" /></label>
          <label class="form-group"><span>章节序号</span><input id="review-alias-chapter" v-model="aliasForm.source_chapter_index" class="form-input" inputmode="numeric" aria-label="按章节序号筛选待处理别名" /></label>
          <label class="form-group"><span>最低置信度</span><input id="review-alias-confidence-min" v-model="aliasForm.confidence_min" class="form-input" inputmode="decimal" aria-label="待处理别名最低置信度" /></label>
          <label class="form-group"><span>最高置信度</span><input id="review-alias-confidence-max" v-model="aliasForm.confidence_max" class="form-input" inputmode="decimal" aria-label="待处理别名最高置信度" /></label>
          <label class="form-group"><span>别名分类</span><select id="review-alias-kind" v-model="aliasForm.alias_kind" class="form-select" aria-label="待处理别名分类"><option value="">全部分类</option><option v-for="item in aliasKindOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label class="form-group"><span>详细类型范围</span><select id="review-alias-type-kind" v-model="aliasForm.type_kind" class="form-select" aria-label="待处理别名详细类型范围"><option value="">全部类型</option><option value="recommended">推荐类型</option><option value="custom">自定义类型</option></select></label>
          <label class="form-group"><span>引用证据</span><select id="review-alias-evidence" v-model="aliasForm.has_quote" class="form-select" aria-label="待处理别名引用证据"><option value="">全部证据</option><option value="true">有引用</option><option value="false">缺少引用</option></select></label>
          <button class="btn btn-sm" data-action="apply-alias-review-filters" @click="applyAliasFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-alias-review-filters" @click="resetAliasReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>
      <div class="world-review-result-row"><p class="world-review-result-summary" role="status">当前结果：{{ aliasGroupTotal }} 组 / {{ aliasItemTotal }} 条别名</p><label><span>每页</span><select id="review-alias-page-size" v-model.number="aliasForm.limit" class="form-select" aria-label="待处理别名每页数量" @change="applyAliasFilters"><option :value="20">20 组</option><option :value="50">50 组</option></select></label></div>
      <WorldBulkToolbar
        v-if="!aliasReviewLoadError"
        scope="world-aliases"
        :actions="[
          { action: 'review-aliases-batch', label: '应用已准备决策', className: 'btn-primary' },
          { action: 'ignore-aliases-batch', label: '批量忽略', className: 'btn-danger' },
        ]"
        noun="别名"
        hint="采用前先逐条确认归属与分类；忽略可直接批量处理"
        :select-all-ids="aliasSelectableIds"
        select-all-label="全选当前页"
        @run="(action) => runReviewBulkAction('world-aliases', action, flatAliases)"
      />

      <div v-if="aliasReviewLoadError" class="empty-state" role="alert" data-author-action="must_fix">
        <strong>待决定别名没有加载出来</strong>
        <p>原有资料没有变化，可以重新加载。</p>
        <button class="btn btn-primary world-review-touch-target" data-action="retry-alias-review-load" @click="retryLoad">重新加载</button>
        <details class="review-error-details"><summary>诊断信息</summary><p>{{ aliasReviewLoadError }}</p></details>
      </div>
      <div v-else-if="!flatAliases.length" class="empty-state">
        <p>没有待处理别名。</p>
        <p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p>
      </div>
      <template v-else>
        <div class="review-group-list">
          <section v-for="group in aliasGroups" :key="group.group_id" class="review-group-card" :class="{ 'is-active': groupHasActiveAlias(group) }" :data-group-id="group.group_id">
            <header class="review-group-card__header">
              <div class="review-group-card__title">
                <strong>{{ group.entity_name || "未命名对象" }}</strong>
                <span>{{ group.member_count }} 个待处理别名</span>
              </div>
              <label class="review-group-select-all">
                <WorldSelectionInput mode="all" scope="world-aliases" :ids="groupSelectableIds(group)" :label="`全选 ${group.entity_name || '对象'} 的别名`" />
                <span>全选本组</span>
              </label>
            </header>
            <div class="review-group-card__members">
              <article v-for="item in group.members || []" :key="aliasKeyOf(item)" class="review-member-row review-member-row--selectable" :class="{ 'is-active': activeKey === aliasKeyOf(item) }" tabindex="0" @click="selectReviewItem(aliasKeyOf(item), $event)" @keydown.enter.self="selectReviewItem(aliasKeyOf(item), $event)" @keydown.space.prevent.self="selectReviewItem(aliasKeyOf(item), $event)">
                <div class="selection-cell">
                  <WorldSelectionInput v-if="!item.managed_by_suggestion" mode="one" scope="world-aliases" :id="aliasKeyOf(item)" :label="`选择别名 ${item.alias}`" />
                </div>
                <div class="review-member-row__main">
                  <div>
                    <strong>{{ item.alias }}</strong>
                    <span class="badge" :class="item.alias_kind ? 'badge-canonical' : 'badge-candidate'">{{ reviewKindLabel('alias', item.alias_kind) }}</span>
                    <span>{{ reviewTypeLabel('alias', item.alias_type) }}</span>
                    <span v-if="item.type_kind === 'custom'" class="badge badge-draft">自定义</span>
                    <span v-if="session.aliasReviewDrafts[aliasKeyOf(item)]" class="badge badge-canonical">已编辑</span>
                  </div>
                  <div v-if="item.suggested_alias_type && item.suggested_alias_type !== item.alias_type" class="review-suggestion">建议类型：{{ reviewTypeLabel('alias', item.suggested_alias_type) }}（仅点击采用后才会修改）</div>
                  <WorldEvidenceSummary :item="item" kind="alias" :numeric-value="item.confidence" />
                  <div v-if="session.aliasReviewErrors[aliasKeyOf(item)]" class="review-item-error" role="alert">{{ session.aliasReviewErrors[aliasKeyOf(item)] }}</div>
                </div>
                <span v-if="item.managed_by_suggestion" class="world-text-dim">随对象建议处理</span>
                <button v-else class="btn btn-sm world-review-queue-action" data-action="prepare-alias-review" :data-entity-id="item.entity_id" :data-alias="item.alias" @click.stop="selectReviewItem(aliasKeyOf(item), $event)">查看并决定</button>
              </article>
            </div>
          </section>
        </div>
        <WorldPager
          :total="aliasGroupTotal"
          :skip="aliasReviewFilters.skip"
          :limit="aliasReviewFilters.limit"
          prev-action="prev-aliases-page"
          next-action="next-aliases-page"
          @change="(delta) => changeReviewPage('alias', delta, aliasReviewFilters, aliasGroupTotal)"
        />
      </template>
    </template>

    <!-- ==================== review-relations ==================== -->
    <template v-else-if="tab === 'relations'">
      <p class="world-list-description">核对尚未采用的对象关系与证据，再决定采用、归并或保留待定。</p>
      <div class="review-search-bar">
        <input id="review-relation-q" v-model="relationForm.q" class="form-input" placeholder="搜索对象、关系类型或描述" aria-label="搜索待处理关系" @keyup.enter="applyRelationFilters" />
        <button class="btn btn-sm" data-action="apply-relation-review-filters" @click="applyRelationFilters">搜索</button>
        <button v-if="relationForm.q" type="button" class="btn btn-sm" data-action="clear-relation-review-search" @click="clearReviewKeyword('relation')">清除搜索</button>
      </div>
      <div class="world-review-quick-row">
        <span id="review-relation-quick-label" class="world-review-quick-label">快速查看</span>
        <div class="review-quick-filters" role="group" aria-labelledby="review-relation-quick-label">
          <button v-for="task in relationTasks" :key="task.key" type="button" class="btn btn-sm" :class="{ 'is-active': String(relationReviewFilters[task.key] || '') === task.value }" data-action="set-relation-quick-filter" :data-filter-key="task.key" :data-filter-value="task.value" :aria-pressed="String(relationReviewFilters[task.key] || '') === task.value" @click="setReviewQuickFilter('relation', task.key, task.value, relationReviewFilters)">{{ task.label }}</button>
        </div>
      </div>
      <div v-if="relationActiveFilterCount" class="world-review-active-filters"><span>已启用 {{ relationActiveFilterCount }} 个条件</span><WorldReviewFilterChips kind="relation" :filters="relationReviewFilters" :review-type-catalog="reviewTypeCatalog" /><button type="button" class="btn btn-sm" data-action="reset-relation-review-filters" @click="resetRelationReviewFilters">清除全部条件</button></div>
      <WorldFilterPanel panel-key="review-relations" :has-active-filters="relationHasActiveFilters" :project-id="projectId" toggle-label="更多筛选" collapse-label="收起更多筛选">
        <div class="filter-bar world-review-filters">
          <label class="form-group"><span>关系分类</span><select id="review-relation-kind" v-model="relationForm.relation_kind" class="form-select" aria-label="按关系分类筛选待处理关系"><option value="">全部分类</option><option v-for="item in relationKindOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label class="form-group"><span>详细类型</span><select id="review-relation-type" v-model="relationForm.relation_type" class="form-select" aria-label="按详细类型筛选待处理关系"><option value="">全部详细类型</option><option v-for="item in relationFilterTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label class="form-group"><span>场景序号</span><input id="review-relation-scene" v-model="relationForm.scene_index" class="form-input" inputmode="numeric" aria-label="按场景序号筛选待处理关系" /></label>
          <label class="form-group"><span>章节序号</span><input id="review-relation-source-chapter" v-model="relationForm.source_chapter_index" class="form-input" inputmode="numeric" aria-label="按章节序号筛选待处理关系" /></label>
          <label class="form-group"><span>最低强度</span><input id="review-relation-strength-min" v-model="relationForm.strength_min" class="form-input" inputmode="decimal" aria-label="待处理关系最低强度" /></label>
          <label class="form-group"><span>最高强度</span><input id="review-relation-strength-max" v-model="relationForm.strength_max" class="form-input" inputmode="decimal" aria-label="待处理关系最高强度" /></label>
          <label class="form-group"><span>引用证据</span><select id="review-relation-evidence" v-model="relationForm.has_quote" class="form-select" aria-label="待处理关系引用证据"><option value="">全部证据</option><option value="true">有引用</option><option value="false">缺少引用</option></select></label>
          <button class="btn btn-sm" data-action="apply-relation-review-filters" @click="applyRelationFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-relation-review-filters" @click="resetRelationReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>
      <div class="world-review-result-row"><p class="world-review-result-summary" role="status">当前结果：{{ relationGroupTotal }} 组 / {{ relationItemTotal }} 条关系</p><label><span>每页</span><select id="review-relation-page-size" v-model.number="relationForm.limit" class="form-select" aria-label="待处理关系每页数量" @change="applyRelationFilters"><option :value="20">20 组</option><option :value="50">50 组</option></select></label></div>
      <WorldBulkToolbar
        v-if="!relationReviewLoadError"
        scope="world-relation-groups"
        :actions="[
          { action: 'apply-relation-decisions', label: '应用已准备决策', className: 'btn-primary' },
          { action: 'ignore-relation-groups', label: '整组忽略', className: 'btn-danger' },
        ]"
        noun="关系组"
        hint="先为选中项准备采用或归并决策"
        :select-all-ids="relationGroups.map((group) => group.group_id)"
        select-all-label="全选当前页"
        @run="(action) => runReviewBulkAction('world-relation-groups', action, relationGroups)"
      />

      <div v-if="relationReviewLoadError" class="empty-state" role="alert" data-author-action="must_fix">
        <strong>待决定关系没有加载出来</strong>
        <p>原有资料没有变化，可以重新加载。</p>
        <button class="btn btn-primary world-review-touch-target" data-action="retry-relation-review-load" @click="retryLoad">重新加载</button>
        <details class="review-error-details"><summary>诊断信息</summary><p>{{ relationReviewLoadError }}</p></details>
      </div>
      <div v-else-if="!relationGroups.length" class="empty-state">
        <p>没有待处理关系。</p>
        <p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p>
      </div>
      <template v-else>
        <div class="review-group-list">
          <section v-for="group in relationGroups" :key="group.group_id" class="review-group-card" :class="{ 'is-active': activeKey === group.group_id }" :data-group-id="group.group_id" tabindex="0" @click="selectReviewItem(group.group_id, $event)" @keydown.enter.self="selectReviewItem(group.group_id, $event)" @keydown.space.prevent.self="selectReviewItem(group.group_id, $event)">
            <header class="review-group-card__header">
              <div class="review-group-card__select"><WorldSelectionInput mode="one" scope="world-relation-groups" :id="group.group_id" :label="`选择 ${group.source_name || '源对象'} 到 ${group.target_name || '目标对象'}`" /></div>
              <div class="review-group-card__title">
                <strong>{{ group.source_name || "未命名对象" }} → {{ group.target_name || "未命名对象" }}</strong>
                <span>{{ group.member_count }} 条候选 · {{ group.evidence_count || 0 }} 条证据</span>
              </div>
              <span class="badge" :class="reviewStatusClass(group.group_id)">{{ reviewStatusLabel(group.group_id) }}</span>
            </header>
            <div class="review-group-card__meta">
              <span>类型：<code v-for="value in group.type_variants || []" :key="value">{{ reviewTypeLabel('relation', value) }}</code></span>
              <span v-if="(group.scene_indices || []).length">场景 {{ (group.scene_indices || []).join("、") }}</span>
              <span v-if="(group.source_chapter_indices || []).length">章节 {{ (group.source_chapter_indices || []).join("、") }}</span>
              <span v-if="(group.canonical_relations || []).length" class="review-warning">已有正式关系：{{ canonicalTypeLabels(group) }}</span>
            </div>
            <div v-if="group.reverse_candidate_count || (group.reverse_canonical_relations || []).length" class="review-reverse-hint">
              反向关联提示：{{ group.target_name || "目标对象" }} → {{ group.source_name || "源对象" }}，
              {{ group.reverse_candidate_count || 0 }} 条候选{{ (group.reverse_type_variants || []).length ? `（${(group.reverse_type_variants || []).map((value) => reviewTypeLabel('relation', value)).join("、")}）` : "" }}，
              {{ (group.reverse_canonical_relations || []).length }} 条正式关系。反向记录不会自动归并。
            </div>
            <div v-if="session.relationReviewErrors[group.group_id]" class="review-item-error" role="alert">{{ session.relationReviewErrors[group.group_id] }}</div>
            <div class="review-group-card__members">
              <article v-for="member in group.members || []" :key="member.id" class="review-member-row">
                <div><span class="badge" :class="member.relation_kind ? 'badge-canonical' : 'badge-candidate'">{{ reviewKindLabel('relation', member.relation_kind) }}</span> <strong>{{ reviewTypeLabel('relation', member.relation_type) }}</strong><span v-if="member.type_kind === 'custom'" class="badge badge-draft">自定义</span></div>
                <div class="review-member-row__description">{{ member.description || "暂无描述" }}</div>
                <WorldEvidenceSummary :item="member.evidence_summary || member" kind="relation" :numeric-value="member.strength" />
              </article>
            </div>
            <footer class="review-group-card__actions">
              <button class="btn btn-sm world-review-queue-action" data-action="prepare-relation-review" :data-group-id="group.group_id" @click.stop="selectReviewItem(group.group_id, $event)">查看并决定</button>
            </footer>
          </section>
        </div>
        <WorldPager
          :total="relationGroupTotal"
          :skip="relationReviewFilters.skip"
          :limit="relationReviewFilters.limit"
          prev-action="prev-relations-page"
          next-action="next-relations-page"
          @change="(delta) => changeReviewPage('relation', delta, relationReviewFilters, relationGroupTotal)"
        />
      </template>
    </template>
      </section>

      <aside ref="decisionEl" class="world-review-decision" aria-labelledby="world-review-decision-title" tabindex="-1">
        <button ref="mobileBackEl" type="button" class="btn btn-sm world-review-mobile-back" @click="returnToQueue">返回队列</button>
        <div v-if="returnToWorldAi" class="world-review-origin">
          <span>来自设定共创</span>
          <button type="button" class="btn btn-sm" data-action="return-to-world-ai" @click="returnToAiWorkspace">返回继续完善</button>
        </div>
        <h2 id="world-review-decision-title" class="world-review-decision__title">{{ decisionTitle }}</h2>
        <template v-if="activeItem">
          <div class="world-review-decision__status"><span class="pill pill-warning">{{ activeStatusLabel }}</span></div>
          <template v-if="tab === 'objects'">
            <p class="world-review-candidate-meta">{{ entityTypeLabel(activeItem.entity_type) }}<template v-if="candidateImportanceText(activeItem)"> · {{ candidateImportanceText(activeItem) }}</template></p>
            <p v-if="candidateSummary(activeItem)" class="world-review-candidate-summary">{{ candidateSummary(activeItem) }}</p>
            <p><strong>AI 建议：</strong>{{ actionLabelOf(activeItem).label }}</p>
            <details v-if="activeCandidateEvidence.length" class="world-review-candidate-evidence">
              <summary>查看来源依据</summary>
              <WorldInlineEvidence :pairs="activeCandidateEvidence" />
            </details>
            <p v-else class="world-text-dim">这条建议没有附带可复核来源，请谨慎判断。</p>
            <div class="world-review-decision__actions"><WorldCandidateActions :candidate="activeItem" :action-options="{ allowAlias: true, allowMerge: true }" /></div>
          </template>
          <template v-else-if="tab === 'aliases'">
            <template v-if="activeAlias?.managed_by_suggestion">
              <p class="review-warning">需先处理对象建议，完成后会返回此项。</p>
              <button type="button" class="btn btn-primary world-review-touch-target" @click="openBlockingObject(activeAlias.entity_id)">先处理对象</button>
            </template>
            <template v-else-if="activeAlias">
              <div class="world-alias-decision">
                <div class="form-group world-alias-decision__target">
                  <span class="form-label">归属对象</span>
                  <div id="alias-inline-target-picker"></div>
                  <input id="alias-inline-target-id" type="hidden" :value="aliasDecisionForm.target_entity_id" />
                </div>

                <div class="world-alias-decision__direction" aria-label="把待处理名称作为上方对象的别名">
                  <span aria-hidden="true">↑</span>
                  <strong>加入上方对象的别名</strong>
                </div>

                <div class="world-alias-decision__merge-row">
                  <label class="form-group">
                    <span>待采用名称</span>
                    <input id="alias-inline-text" v-model="aliasDecisionForm.alias" class="form-input" maxlength="200" @input="persistActiveAliasDecision" />
                  </label>
                  <div class="world-alias-decision__types">
                    <label class="form-group">
                      <span>名称用途</span>
                      <select id="alias-inline-kind" v-model="aliasDecisionForm.alias_kind" class="form-select" aria-describedby="alias-inline-kind-help" @change="markAliasKindExplicit">
                        <option value="">请选择名称用途</option>
                        <option v-for="item in aliasKindOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                      </select>
                      <small id="alias-inline-kind-help" class="form-help">{{ activeAliasKindHelp }}</small>
                    </label>
                    <label class="form-group">
                      <span>具体称呼</span>
                      <select id="alias-inline-type" v-model="aliasTypeChoice" class="form-select" @change="changeAliasType">
                        <option v-for="item in aliasTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                        <option :value="CUSTOM_DETAIL_TYPE_VALUE">自定义称呼类型…</option>
                      </select>
                    </label>
                    <label v-if="aliasTypeChoice === CUSTOM_DETAIL_TYPE_VALUE" class="form-group">
                      <span>自定义称呼类型</span>
                      <input id="alias-inline-type-custom" v-model="aliasCustomType" class="form-input" maxlength="20" @input="changeAliasCustomType" />
                    </label>
                    <button v-if="activeAlias.suggested_alias_type && activeAlias.suggested_alias_type !== aliasDecisionForm.alias_type" type="button" class="btn btn-sm" data-action="use-alias-type-suggestion" @click="useAliasTypeSuggestion">使用建议：{{ reviewTypeLabel('alias', activeAlias.suggested_alias_type) }}</button>
                  </div>
                </div>

                <section class="world-alias-decision__evidence" aria-label="证据">
                  <strong>证据</strong>
                  <WorldEvidenceSummary :item="activeAlias" kind="alias" :numeric-value="activeAlias.confidence" />
                </section>
                <p v-if="aliasDecisionStale" class="review-warning">旧草稿对应的内容已变化，已按当前内容重新载入，请重新确认。</p>
                <p v-if="session.aliasReviewErrors[aliasKeyOf(activeAlias)]" class="review-item-error" role="alert">{{ session.aliasReviewErrors[aliasKeyOf(activeAlias)] }}</p>
                <div class="world-alias-decision__actions">
                  <button type="button" class="btn btn-primary world-review-touch-target" data-action="confirm-alias-merge" :disabled="aliasDecisionProcessing" @click="confirmActiveAliasDecision">{{ nextAliasKey ? '采用并查看下一条' : '采用别名' }}</button>
                  <button type="button" class="btn btn-danger world-review-touch-target" data-action="ignore-current-alias" :disabled="aliasDecisionProcessing" @click="applyAliasReviewBatch([activeAlias], 'ignore')">忽略此别名</button>
                  <button type="button" class="btn world-review-touch-target" data-action="cancel-alias-decision" :disabled="aliasDecisionProcessing" @click="cancelAliasDecision">稍后再决定</button>
                </div>
              </div>
            </template>
          </template>
          <template v-else>
            <p>{{ activeItem.member_count || (activeItem.members || []).length }} 条候选 · {{ activeItem.evidence_count || 0 }} 条证据</p>
            <p v-if="dependencyState.loading" class="world-text-dim">正在检查对象状态…</p>
            <div v-else-if="dependencyState.error" class="review-warning" role="alert"><p>无法核对关系端点的对象状态。</p><button type="button" class="btn btn-sm" @click="retryLoad">刷新后重试</button></div>
            <p v-else-if="dependencyState.blocker" class="review-warning">需先决定“{{ dependencyState.blocker.name }}”，才能安心采用这条关系。</p>
            <button v-if="dependencyState.blocker" type="button" class="btn btn-primary world-review-touch-target" @click="openBlockingObject(dependencyState.blocker.id)">先处理对象</button>
            <div v-else-if="!dependencyState.error" class="world-relation-decision">
              <p class="world-text-dim">拖动任意一张人物卡到空槽；另一张会自动补入另一侧，每组只需拖一次。</p>
              <div class="world-relation-decision__people" role="group" aria-label="待配对人物">
                <button
                  v-for="person in relationPeople"
                  :key="person.id"
                  type="button"
                  class="world-relation-person-card"
                  :class="{ 'is-selected': selectedRelationPersonId === person.id }"
                  draggable="true"
                  data-action="relation-person-card"
                  :data-person-id="person.id"
                  :aria-pressed="selectedRelationPersonId === person.id"
                  @dragstart="startRelationDrag(person.id, $event)"
                  @click="selectRelationPerson(person.id)"
                >
                  <span class="world-relation-person-card__avatar" aria-hidden="true">{{ person.name.slice(0, 1) }}</span>
                  <strong>{{ person.name }}</strong>
                  <small>拖到下方空槽</small>
                </button>
              </div>

              <div class="world-relation-decision__pairing" :class="{ 'is-complete': relationPairingComplete }">
                <button type="button" class="world-relation-slot" data-relation-slot="source" :class="{ 'is-filled': relationDecisionForm.source_id }" @dragover.prevent @drop.prevent="dropRelationPerson('source', $event)" @click="placeSelectedRelationPerson('source')">
                  <span>关系发起方</span>
                  <strong>{{ relationEndpointName(relationDecisionForm.source_id) || "拖入人物" }}</strong>
                </button>
                <div class="world-relation-decision__direction" aria-label="关系方向">
                  <strong>{{ reviewTypeLabel('relation', relationDecisionForm.relation_type) }}</strong>
                  <span aria-hidden="true">→</span>
                </div>
                <button type="button" class="world-relation-slot" data-relation-slot="target" :class="{ 'is-filled': relationDecisionForm.target_id }" @dragover.prevent @drop.prevent="dropRelationPerson('target', $event)" @click="placeSelectedRelationPerson('target')">
                  <span>关系承接方</span>
                  <strong>{{ relationEndpointName(relationDecisionForm.target_id) || "拖入人物" }}</strong>
                </button>
              </div>
              <p v-if="selectedRelationPersonId && !relationPairingComplete" class="world-text-dim" role="status">已选择“{{ relationEndpointName(selectedRelationPersonId) }}”，再点一个空槽即可。</p>

              <div class="world-relation-decision__fields">
                <label class="form-group">
                  <span>关系分类</span>
                  <select id="relation-inline-kind" v-model="relationDecisionForm.relation_kind" class="form-select" aria-describedby="relation-inline-kind-help" @change="markRelationKindExplicit">
                    <option value="">请选择分类</option>
                    <option v-for="item in relationKindOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                  </select>
                  <small id="relation-inline-kind-help" class="form-help">{{ activeRelationKindHelp }}</small>
                </label>
                <label class="form-group">
                  <span>详细类型</span>
                  <select id="relation-inline-type" v-model="relationTypeChoice" class="form-select" @change="changeRelationType">
                    <option v-for="item in relationDecisionTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                    <option :value="CUSTOM_DETAIL_TYPE_VALUE">自定义详细类型…</option>
                  </select>
                </label>
                <label v-if="relationTypeChoice === CUSTOM_DETAIL_TYPE_VALUE" class="form-group">
                  <span>自定义详细类型</span>
                  <input id="relation-inline-type-custom" v-model="relationCustomType" class="form-input" maxlength="50" @input="changeRelationCustomType" />
                </label>
                <button v-if="activeRelationSuggestedType && activeRelationSuggestedType !== relationDecisionForm.relation_type" type="button" class="btn btn-sm" data-action="use-relation-type-suggestion" @click="useRelationTypeSuggestion">使用建议：{{ reviewTypeLabel('relation', activeRelationSuggestedType) }}</button>
                <label class="form-group world-relation-decision__description">
                  <span>关系说明</span>
                  <textarea id="relation-inline-description" v-model="relationDecisionForm.description" class="form-textarea" rows="3" maxlength="1000" @input="persistActiveRelationDecision"></textarea>
                </label>
                <label class="form-group">
                  <span>关系强度</span>
                  <input id="relation-inline-strength" v-model.number="relationDecisionForm.strength" class="form-input" type="number" min="0" max="1" step="0.01" @input="persistActiveRelationDecision" />
                </label>
              </div>

              <section class="world-relation-decision__evidence" aria-label="证据">
                <strong>证据</strong>
                <WorldEvidenceSummary v-for="member in activeRelationEvidenceMembers" :key="member.id" :item="member.evidence_summary || member" kind="relation" :numeric-value="member.strength" />
                <span class="world-text-dim">本次处理 {{ activeRelationEvidenceMembers.length }} 条候选，其余 {{ activeRelationRemaining }} 条继续待定。</span>
              </section>
              <p v-if="relationDecisionStale" class="review-warning">旧草稿对应的内容已变化，已按当前内容重新载入，请重新确认。</p>
              <p v-if="session.relationReviewErrors[activeItem.group_id]" class="review-item-error" role="alert">{{ session.relationReviewErrors[activeItem.group_id] }}</p>
              <div class="world-relation-decision__actions">
                <button type="button" class="btn btn-primary world-review-touch-target" data-action="confirm-relation-decision" :disabled="relationDecisionProcessing" @click="confirmActiveRelationDecision">采用关系</button>
                <button type="button" class="btn btn-danger world-review-touch-target" data-action="ignore-current-relation" :disabled="relationDecisionProcessing" @click="applyRelationReviewBatch([activeItem], true)">忽略本组</button>
                <button type="button" class="btn world-review-touch-target" data-action="cancel-relation-decision" :disabled="relationDecisionProcessing" @click="cancelRelationDecision">稍后再决定</button>
              </div>
            </div>
          </template>
        </template>
        <div v-else class="empty-state world-review-decision__empty"><p>从左侧队列选择一项，这里会显示证据和可用操作。</p></div>
        <div v-if="session.reviewReceipt" class="world-review-receipt" role="status">
          <strong>{{ session.reviewReceipt.title }}</strong><p>{{ session.reviewReceipt.detail }}</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch, onBeforeUnmount, onMounted, nextTick } from "vue"
import { getApi, getAppState, getRouteQuery, getRouter } from "../../../bridge/index.js"
import { worldSession as session } from "../worldSession.js"
import { WORLD_CANDIDATE_QUERY_KEYS } from "../logic/worldQuery.js"
import { reconcileBulkSelection } from "../logic/worldBulkSelection.js"
import { candidateMeta, entityId } from "../logic/worldEntityHelpers.js"
import { destroyWorldEntityPickers, mountEntityReferencePickerForReview, registerCandidateListHooks, syncWorldListRegistry } from "../logic/worldEntityOps.js"
import {
  aliasKey,
  acceptAliasReviewDecision,
  acceptRelationReviewDecision,
  applyAliasReviewBatch,
  applyRelationReviewBatch,
  applyCandidateReviewFilters,
  applyAliasReviewFilters,
  applyRelationReviewFilters,
  resetCandidateReviewFilters,
  resetAliasReviewFilters,
  resetRelationReviewFilters,
  candidateActionLabel,
  changeReviewPage,
  groupTargetedAliasCandidates,
  inlineEvidencePairs,
  persistAliasReviewDecision,
  persistRelationReviewDecision,
  prepareAliasReviewDecision,
  prepareRelationReviewDecision,
  reviewTypeLabel,
  reviewKindLabel,
  recommendedRelationDecision,
  runReviewBulkAction,
  setReviewQuickFilter,
  setCandidateTaskFilter,
  splitCandidateGroups,
  syncReviewRegistry,
} from "../logic/useWorldReview.js"
import { CUSTOM_DETAIL_TYPE_VALUE, catalogKindItems, catalogTypeItems, defaultKindForType, detailTypeLabel } from "../logic/worldTypeCatalog.js"
import WorldBulkToolbar from "./WorldBulkToolbar.vue"
import WorldCandidateActions from "./WorldCandidateActions.vue"
import WorldCandidateGroupItem from "./WorldCandidateGroupItem.vue"
import WorldEvidenceSummary from "./WorldEvidenceSummary.vue"
import WorldFilterPanel from "./WorldFilterPanel.vue"
import WorldInlineEvidence from "./WorldInlineEvidence.vue"
import WorldPager from "./WorldPager.vue"
import WorldReviewFilterChips from "./WorldReviewFilterChips.vue"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  reviewSubView: { type: String, default: "review" },
  reviewKind: { type: String, default: "all" },
  reviewCounts: { type: Object, default: () => ({ objects: 0, aliases: 0, relations: 0 }) },
  entityTypes: { type: Array, default: () => [] },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
  candidateFilters: { type: Object, default: () => ({ skip: 0, limit: 20 }) },
  candidates: { type: Array, default: () => [] },
  candidateTotal: { type: Number, default: 0 },
  candidateLoadError: { type: String, default: null },
  aliasReviewFilters: { type: Object, default: () => ({ skip: 0, limit: 20 }) },
  aliasGroups: { type: Array, default: () => [] },
  aliasGroupTotal: { type: Number, default: 0 },
  aliasItemTotal: { type: Number, default: 0 },
  aliasReviewLoadError: { type: String, default: null },
  relationReviewFilters: { type: Object, default: () => ({ skip: 0, limit: 20 }) },
  relationGroups: { type: Array, default: () => [] },
  relationGroupTotal: { type: Number, default: 0 },
  relationItemTotal: { type: Number, default: 0 },
  relationReviewLoadError: { type: String, default: null },
})

const tab = computed(() => {
  if (["objects", "aliases", "relations"].includes(props.reviewKind)) return props.reviewKind
  return {
    "review-objects": "objects",
    "review-aliases": "aliases",
    "review-relations": "relations",
  }[props.reviewSubView] || "all"
})
const currentReviewCount = computed(() => {
  if (tab.value === "aliases") return props.aliasItemTotal
  if (tab.value === "relations") return props.relationItemTotal
  return props.candidateTotal
})
const candidateTasks = [
  { value: "create_new", label: "可作为新对象" },
  { value: "alias", label: "建议设为别名" },
  { value: "merge_with_existing", label: "建议合并" },
  { value: "needs_user_decision", label: "需我判断" },
]
const candidateActionOptions = [
  ...candidateTasks,
  { value: "temporary_only", label: "建议设为临时" },
  { value: "ignore", label: "建议忽略" },
]
const aliasTasks = [
  { key: "multi_alias_only", value: "true", label: "同对象多别名" },
  { key: "type_kind", value: "custom", label: "自定义类型" },
  { key: "has_quote", value: "false", label: "缺少引用" },
  { key: "confidence_min", value: "0.95", label: "高置信度" },
]
const relationTasks = [
  { key: "multi_type_only", value: "true", label: "同对象对多类型" },
  { key: "has_reverse_candidates", value: "true", label: "有反向候选" },
  { key: "has_canonical_relation", value: "true", label: "已有正式关系" },
  { key: "has_quote", value: "false", label: "缺少引用" },
  { key: "strength_max", value: "0.69", label: "低强度" },
]
const entityIdOf = entityId
const aliasKeyOf = aliasKey
const localCandidates = ref([])
const aliasKindOptions = computed(() => catalogKindItems(props.reviewTypeCatalog, "alias"))
const aliasTypeOptions = computed(() => catalogTypeItems(props.reviewTypeCatalog, "alias"))
const relationKindOptions = computed(() => catalogKindItems(props.reviewTypeCatalog, "relation"))
const relationFilterTypeOptions = computed(() => {
  const items = [...catalogTypeItems(props.reviewTypeCatalog, "relation")]
  const selected = relationForm.relation_type
  if (selected && !items.some((item) => item.value === selected)) {
    items.unshift({ value: selected, label: detailTypeLabel(props.reviewTypeCatalog, "relation", selected) })
  }
  return items
})

const overviewKinds = computed(() => [
  { kind: "objects", label: "对象", count: Number(props.reviewCounts.objects || 0), hint: "人物、地点与设定" },
  { kind: "aliases", label: "别名", count: Number(props.reviewCounts.aliases || 0), hint: "名称应归属到哪个对象" },
  { kind: "relations", label: "关系", count: Number(props.reviewCounts.relations || 0), hint: "对象之间的联系与证据" },
])
const recommendedKind = computed(() => {
  const next = overviewKinds.value.find((item) => item.count > 0)
  return next
    ? { ...next, description: next.kind === "objects" ? "先处理对象，可以避免别名和关系因端点未确定而阻塞。" : `当前最适合继续处理${next.label}。` }
    : { kind: "", label: "已全部处理完成", description: "目前没有需要你决定的世界资料。" }
})

function navigateKind(kind) {
  const query = new URLSearchParams()
  if (kind !== "all") query.set("kind", kind)
  getRouter()?.navigate("world", "review", true, query)
}

function retryLoad() {
  getRouter()?.refresh?.()
}

const REVIEW_ITEM_QUERY_KEY = "review_item"
const initialQuery = getRouteQuery()
const initialReviewItem = initialQuery.get(REVIEW_ITEM_QUERY_KEY) || ""
const returnToWorldAi = initialQuery.get("return_to") === "world_ai"
const returnSubview = initialQuery.get("return_subview") || "objects"
const activeKey = ref(initialReviewItem)
const mobileDetailOpen = ref(Boolean(initialReviewItem))
const mobileBackEl = ref(null)
const decisionEl = ref(null)
let lastSelectionEl = null
let disposed = false
const activeItem = computed(() => {
  if (!activeKey.value) return null
  if (tab.value === "objects") return localCandidates.value.find((item) => entityId(item) === activeKey.value) || null
  if (tab.value === "aliases") return props.aliasGroups.find((group) => (group.members || []).some((item) => aliasKey(item) === activeKey.value)) || null
  return props.relationGroups.find((item) => item.group_id === activeKey.value) || null
})
const activeAlias = computed(() => activeItem.value?.members?.find((item) => aliasKey(item) === activeKey.value) || null)
const nextAliasKey = computed(() => {
  const aliases = props.aliasGroups.flatMap((group) => group.members || []).filter((item) => !item.managed_by_suggestion)
  const index = aliases.findIndex((item) => aliasKey(item) === activeKey.value)
  const next = index >= 0 ? aliases[index + 1] || aliases[index - 1] : null
  return next ? aliasKey(next) : ""
})
const activeRelationGroup = computed(() => tab.value === "relations" ? activeItem.value : null)
const activeCandidateEvidence = computed(() => tab.value === "objects" && activeItem.value ? candidateEvidence(activeItem.value) : [])
const decisionTitle = computed(() => {
  if (!activeItem.value) return "选择一项开始"
  if (tab.value === "objects") return `决定是否采用“${activeItem.value.name || "未命名对象"}”`
  if (tab.value === "aliases") return `决定“${activeAlias.value?.alias || "这个名称"}”的归属`
  return `确定“${activeItem.value.source_name || "源对象"} → ${activeItem.value.target_name || "目标对象"}”的关系`
})
const aliasDecisionForm = reactive({ target_entity_id: "", target_entity_name: "", alias: "", alias_kind: "", alias_type: "", _kind_explicit: false })
const aliasTypeChoice = ref("")
const aliasCustomType = ref("")
const aliasDecisionStale = ref(false)
const aliasDecisionProcessing = computed(() => Boolean(session.processingReviewIds?.[aliasKey(activeAlias.value)]))
const activeAliasKindHelp = computed(() => (
  aliasKindOptions.value.find((item) => item.value === aliasDecisionForm.alias_kind)?.description
  || "先选择用于 AI 检索的通用分类。"
))
const relationDecisionForm = reactive({ source_id: "", target_id: "", relation_kind: "", relation_type: "", description: "", strength: 0.5, _kind_explicit: false })
const relationTypeChoice = ref("")
const relationCustomType = ref("")
const relationDecisionStale = ref(false)
const selectedRelationPersonId = ref("")
let draggedRelationPersonId = ""
const activeRelationDecision = computed(() => tab.value === "relations" ? recommendedRelationDecision(activeItem.value) : null)
const relationPeople = computed(() => {
  if (!activeItem.value) return []
  return [
    { id: activeItem.value.source_id, name: activeItem.value.source_name || "未命名对象" },
    { id: activeItem.value.target_id, name: activeItem.value.target_name || "未命名对象" },
  ].filter((person, index, items) => person.id && items.findIndex((item) => item.id === person.id) === index)
})
const relationDecisionTypeOptions = computed(() => catalogTypeItems(props.reviewTypeCatalog, "relation"))
const activeRelationEvidenceMembers = computed(() => {
  const selected = new Set(activeRelationDecision.value?.member_relation_ids || [])
  return (activeItem.value?.members || []).filter((item) => selected.has(item.id))
})
const activeRelationSuggestedType = computed(() => (
  activeRelationEvidenceMembers.value.find((item) => item.suggested_relation_type)?.suggested_relation_type || ""
))
const activeRelationRemaining = computed(() => Math.max(0, (activeItem.value?.members || []).length - (activeRelationDecision.value?.member_relation_ids?.length || 0)))
const relationPairingComplete = computed(() => Boolean(relationDecisionForm.source_id && relationDecisionForm.target_id))
const relationDecisionProcessing = computed(() => Boolean(session.processingReviewIds?.[activeItem.value?.group_id]))
const activeRelationKindHelp = computed(() => (
  relationKindOptions.value.find((item) => item.value === relationDecisionForm.relation_kind)?.description
  || "先选择用于 AI 检索的通用分类。"
))
const activeStatusKey = computed(() => tab.value === "aliases" ? aliasKey(activeAlias.value || {}) : (activeKey.value || activeItem.value?.group_id || entityId(activeItem.value)))

function isNarrowReviewViewport() {
  return typeof globalThis.matchMedia === "function" && globalThis.matchMedia("(max-width: 760px)").matches
}

function syncReviewSelection(key) {
  const router = getRouter()
  const query = getRouteQuery()
  if (key) query.set(REVIEW_ITEM_QUERY_KEY, key)
  else query.delete(REVIEW_ITEM_QUERY_KEY)
  return router?.commitCurrentQuery?.(query) === true
}

function selectReviewItem(key, event) {
  activeKey.value = key || ""
  mobileDetailOpen.value = true
  lastSelectionEl = event?.currentTarget || lastSelectionEl
  syncReviewSelection(activeKey.value)
  void nextTick(() => (isNarrowReviewViewport() ? mobileBackEl.value : decisionEl.value)?.focus())
}

function returnToQueue() {
  mobileDetailOpen.value = false
  syncReviewSelection("")
  void nextTick(() => lastSelectionEl?.focus?.())
}

function groupHasActiveAlias(group) {
  return (group.members || []).some((item) => aliasKey(item) === activeKey.value)
}

function entityTypeLabel(value) {
  return props.entityTypes.find((item) => item.value === value)?.label || value || "未分类"
}

function candidateSummary(candidate) {
  const content = candidate?.content_json || {}
  return candidate?.summary || candidate?.public_info || content.summary || content.public_info || ""
}

function candidateImportanceText(candidate) {
  const value = candidate?.importance_level ?? candidate?.importance ?? candidate?.importance_score
  if (value == null || value === "") return ""
  const labels = { core: "核心设定", important: "重要设定", normal: "一般设定", temporary: "临时资料" }
  if (labels[value]) return labels[value]
  if (typeof value === "number" && Number.isFinite(value)) return `重要程度 ${Math.round(value * 100)}%`
  return String(value)
}

function candidateEvidence(candidate) {
  return inlineEvidencePairs(candidateMeta(candidate))
}

function returnToAiWorkspace() {
  const subView = ["objects", "relations", "bible"].includes(returnSubview) ? returnSubview : "objects"
  getRouter()?.navigate("world", subView, true, new URLSearchParams({ owner_ai: "1", owner_ai_mode: "world" }))
}

function reviewStatusLabel(key) {
  if (session.processingReviewIds?.[key]) return "处理中"
  const error = session.relationReviewErrors[key] || session.aliasReviewErrors[key]
  if (error) return String(error).includes("过期") || String(error).includes("变化") ? "内容已变化" : "处理失败"
  if (session.reviewReceipt?.targetKey === key) return "已完成"
  return "待处理"
}

function reviewStatusClass(key) {
  const label = reviewStatusLabel(key)
  if (label === "已完成") return "badge-canonical"
  if (label === "处理失败" || label === "内容已变化") return "badge-draft"
  return "badge-candidate"
}

const dependencyState = reactive({ loading: false, blocker: null, error: false })
const activeStatusLabel = computed(() => (
  dependencyState.error
    ? "处理失败"
    : activeAlias.value?.managed_by_suggestion || dependencyState.blocker
      ? "需先处理对象"
      : reviewStatusLabel(activeStatusKey.value)
))
let dependencyGeneration = 0
watch([tab, activeItem], async ([kind, item]) => {
  const generation = ++dependencyGeneration
  dependencyState.loading = false
  dependencyState.blocker = null
  dependencyState.error = false
  if (kind !== "relations" || !item?.source_id || !item?.target_id) return
  dependencyState.loading = true
  try {
    const api = getApi()
    const projectId = getAppState()?.currentProjectId
    const entities = await Promise.all([
      api.world.getEntity(item.source_id, projectId),
      api.world.getEntity(item.target_id, projectId),
    ])
    if (generation !== dependencyGeneration) return
    const blocker = entities.find((entity) => entity?.status === "candidate")
    dependencyState.blocker = blocker ? { id: entityId(blocker), name: blocker.name || "待处理对象" } : null
  } catch {
    if (generation === dependencyGeneration) dependencyState.error = true
  } finally {
    if (generation === dependencyGeneration) dependencyState.loading = false
  }
}, { immediate: true })

function openBlockingObject(entityIdParam) {
  if (!entityIdParam) return
  const query = new URLSearchParams({
    kind: "objects",
    entity_id: entityIdParam,
    return_kind: tab.value,
  })
  if (activeItem.value?.group_id) query.set("return_group_id", activeItem.value.group_id)
  getRouter()?.navigate("world", "review", true, query)
}

// ---- 注册表同步（决策区/批量按 id 查找） ----
watch(() => [props.candidates, props.aliasGroups, props.relationGroups, props.entityTypes, props.reviewTypeCatalog, props.aliasReviewFilters, props.relationReviewFilters, props.aliasGroupTotal, props.relationGroupTotal], () => {
  syncReviewRegistry({
    candidates: props.candidates,
    aliases: props.aliasGroups.flatMap((group) => group.members || []),
    relationGroups: props.relationGroups,
    relations: props.relationGroups.flatMap((group) => group.members || []),
    entityTypes: props.entityTypes,
    reviewTypeCatalog: props.reviewTypeCatalog,
    aliasFilters: props.aliasReviewFilters,
    relationFilters: props.relationReviewFilters,
    aliasGroupTotal: props.aliasGroupTotal,
    relationGroupTotal: props.relationGroupTotal,
  })
  syncWorldListRegistry({ candidates: props.candidates, entityTypes: props.entityTypes, reviewTypeCatalog: props.reviewTypeCatalog })
}, { immediate: true, deep: true })

function setAliasTypeControl(value) {
  const known = aliasTypeOptions.value.some((item) => item.value === value)
  aliasTypeChoice.value = known ? value : CUSTOM_DETAIL_TYPE_VALUE
  aliasCustomType.value = known ? "" : value
}

function persistActiveAliasDecision() {
  if (!activeAlias.value) return
  persistAliasReviewDecision(activeAlias.value, aliasDecisionForm)
}

function syncDefaultAliasKind() {
  if (aliasDecisionForm._kind_explicit) return
  aliasDecisionForm.alias_kind = aliasTypeChoice.value === CUSTOM_DETAIL_TYPE_VALUE
    ? ""
    : defaultKindForType(props.reviewTypeCatalog, "alias", aliasDecisionForm.alias_type)
}

function markAliasKindExplicit() {
  aliasDecisionForm._kind_explicit = true
  persistActiveAliasDecision()
}

function changeAliasType() {
  aliasDecisionForm.alias_type = aliasTypeChoice.value === CUSTOM_DETAIL_TYPE_VALUE
    ? aliasCustomType.value
    : aliasTypeChoice.value
  syncDefaultAliasKind()
  persistActiveAliasDecision()
}

function changeAliasCustomType() {
  aliasDecisionForm.alias_type = aliasCustomType.value
  persistActiveAliasDecision()
}

function useAliasTypeSuggestion() {
  const value = activeAlias.value?.suggested_alias_type || ""
  setAliasTypeControl(value)
  aliasDecisionForm.alias_type = value
  syncDefaultAliasKind()
  persistActiveAliasDecision()
}

async function confirmActiveAliasDecision() {
  const item = activeAlias.value
  if (!item) return
  const nextKey = nextAliasKey.value
  const accepted = await acceptAliasReviewDecision(item, aliasDecisionForm, { refresh: false })
  if (!accepted || disposed) return
  activeKey.value = nextKey
  mobileDetailOpen.value = Boolean(nextKey)
  syncReviewSelection(nextKey)
  await nextTick()
  const focusTarget = nextKey
    ? (isNarrowReviewViewport() ? mobileBackEl.value : decisionEl.value)
    : document.getElementById("review-alias-q")
  focusTarget?.focus?.()
  await getRouter()?.refresh?.()
}

function cancelAliasDecision() {
  activeKey.value = ""
  mobileDetailOpen.value = false
  syncReviewSelection("")
  void nextTick(() => lastSelectionEl?.focus?.())
}

watch(activeAlias, async (item) => {
  destroyWorldEntityPickers()
  aliasDecisionStale.value = false
  if (!item || item.managed_by_suggestion) return
  const prepared = prepareAliasReviewDecision(item)
  Object.assign(aliasDecisionForm, prepared.draft, {
    target_entity_name: prepared.draft.target_entity_id === item.entity_id
      ? (item.entity_name || activeItem.value?.entity_name || "当前对象")
      : "选定对象",
  })
  aliasDecisionStale.value = prepared.stale
  setAliasTypeControl(aliasDecisionForm.alias_type)
  await nextTick()
  if (activeAlias.value !== item) return
  mountEntityReferencePickerForReview({
    rootId: "alias-inline-target-picker",
    inputId: "alias-inline-target-id",
    selectedId: aliasDecisionForm.target_entity_id,
    selectedName: aliasDecisionForm.target_entity_id === item.entity_id ? aliasDecisionForm.target_entity_name : "",
    onChange: (items, refs) => {
      aliasDecisionForm.target_entity_id = refs[0]?.id || ""
      aliasDecisionForm.target_entity_name = items[0]?.label || "选定对象"
      persistActiveAliasDecision()
    },
  })
}, { immediate: true })

onMounted(() => {
  if (tab.value !== "aliases" || !activeKey.value) return
  void nextTick(() => (isNarrowReviewViewport() ? mobileBackEl.value : decisionEl.value)?.focus?.())
})

function setRelationTypeControl(value) {
  const known = relationDecisionTypeOptions.value.some((item) => item.value === value)
  relationTypeChoice.value = known ? value : CUSTOM_DETAIL_TYPE_VALUE
  relationCustomType.value = known ? "" : value
}

function persistActiveRelationDecision() {
  if (!activeRelationGroup.value) return
  persistRelationReviewDecision(activeRelationGroup.value, relationDecisionForm)
}

function syncDefaultRelationKind() {
  if (relationDecisionForm._kind_explicit) return
  relationDecisionForm.relation_kind = relationTypeChoice.value === CUSTOM_DETAIL_TYPE_VALUE
    ? ""
    : defaultKindForType(props.reviewTypeCatalog, "relation", relationDecisionForm.relation_type)
}

function markRelationKindExplicit() {
  relationDecisionForm._kind_explicit = true
  persistActiveRelationDecision()
}

function changeRelationType() {
  relationDecisionForm.relation_type = relationTypeChoice.value === CUSTOM_DETAIL_TYPE_VALUE
    ? relationCustomType.value
    : relationTypeChoice.value
  syncDefaultRelationKind()
  persistActiveRelationDecision()
}

function changeRelationCustomType() {
  relationDecisionForm.relation_type = relationCustomType.value
  persistActiveRelationDecision()
}

function useRelationTypeSuggestion() {
  const value = activeRelationSuggestedType.value
  setRelationTypeControl(value)
  relationDecisionForm.relation_type = value
  syncDefaultRelationKind()
  persistActiveRelationDecision()
}

function relationEndpointName(id) {
  return relationPeople.value.find((person) => person.id === id)?.name || ""
}

function selectRelationPerson(id) {
  selectedRelationPersonId.value = id
}

function startRelationDrag(id, event) {
  draggedRelationPersonId = id
  event.dataTransfer?.setData("text/plain", id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move"
}

function assignRelationPerson(id, side) {
  const selected = relationPeople.value.find((person) => person.id === id)
  const other = relationPeople.value.find((person) => person.id !== id)
  if (!selected || !other) return
  relationDecisionForm.source_id = side === "source" ? selected.id : other.id
  relationDecisionForm.target_id = side === "target" ? selected.id : other.id
  selectedRelationPersonId.value = ""
  persistActiveRelationDecision()
}

function dropRelationPerson(side, event) {
  const id = event.dataTransfer?.getData("text/plain") || draggedRelationPersonId
  draggedRelationPersonId = ""
  assignRelationPerson(id, side)
}

function placeSelectedRelationPerson(side) {
  if (selectedRelationPersonId.value) assignRelationPerson(selectedRelationPersonId.value, side)
}

async function confirmActiveRelationDecision() {
  const group = activeRelationGroup.value
  if (!group) return
  const accepted = await acceptRelationReviewDecision(group, relationDecisionForm)
  if (accepted) {
    activeKey.value = ""
    mobileDetailOpen.value = false
    syncReviewSelection("")
  }
}

function cancelRelationDecision() {
  activeKey.value = ""
  mobileDetailOpen.value = false
  syncReviewSelection("")
  void nextTick(() => lastSelectionEl?.focus?.())
}

watch(activeRelationGroup, (group) => {
  selectedRelationPersonId.value = ""
  draggedRelationPersonId = ""
  relationDecisionStale.value = false
  if (!group) return
  const prepared = prepareRelationReviewDecision(group)
  if (!prepared.draft) return
  Object.assign(relationDecisionForm, prepared.draft)
  relationDecisionStale.value = prepared.stale
  setRelationTypeControl(relationDecisionForm.relation_type)
}, { immediate: true })

// ---- 候选乐观镜像（vanilla _removeCandidateOptimistically/_restoreCandidateSnapshot） ----
watch(() => props.candidates, (next) => {
  localCandidates.value = [...next]
  reconcileBulkSelection("world-candidates", next.map((item) => entityId(item)).filter(Boolean))
}, { immediate: true, deep: true })

async function removeOptimistically(id) {
  const snapshot = { candidates: [...localCandidates.value] }
  const before = localCandidates.value.length
  localCandidates.value = localCandidates.value.filter((item) => entityId(item) !== id)
  if (localCandidates.value.length === before) return null
  return snapshot
}

async function restoreSnapshot(snapshot) {
  if (!snapshot) return
  localCandidates.value = snapshot.candidates
}

registerCandidateListHooks({ removeOptimistically, restoreSnapshot })
onBeforeUnmount(() => {
  disposed = true
  registerCandidateListHooks({})
  destroyWorldEntityPickers()
})

// ---- 候选分组 ----
const candidateSplit = computed(() => splitCandidateGroups(localCandidates.value))
const regularCandidates = computed(() => candidateSplit.value.regularCandidates)
const similarNameGroups = computed(() => candidateSplit.value.similarNameGroups)
const targetedAliasGroups = computed(() => (
  groupTargetedAliasCandidates(candidateSplit.value.targetedAliasCandidates).map((group) => ({
    ...group,
    targetLabel: group.targetName || (group.targetId ? `${String(group.targetId).slice(0, 8)}...` : "未知对象"),
    ids: group.candidates.map((item) => entityId(item)),
  }))
))

function similarGroupTypeLabel(group) {
  return props.entityTypes.find((item) => item.value === group[0]?.entity_type)?.label || group[0]?.entity_type || "对象"
}

function actionLabelOf(candidate) {
  return candidateActionLabel(candidate)
}

// ---- 筛选表单（本地副本，应用时 navigate；重挂载由 props 重播种） ----
const candidateForm = reactive({})
const aliasForm = reactive({})
const relationForm = reactive({})

watch(() => props.candidateFilters, (filters) => Object.assign(candidateForm, filters), { immediate: true, deep: true })
watch(() => props.aliasReviewFilters, (filters) => Object.assign(aliasForm, filters), { immediate: true, deep: true })
watch(() => props.relationReviewFilters, (filters) => Object.assign(relationForm, filters), { immediate: true, deep: true })

const candidateHasActiveFilters = computed(() => (
  WORLD_CANDIDATE_QUERY_KEYS.some((key) => Boolean(props.candidateFilters[key]))
))
const ALIAS_ACTIVE_KEYS = ["source", "workflow_id", "scene_index", "source_chapter_index", "confidence_min", "confidence_max", "has_quote", "type_kind", "alias_kind", "multi_alias_only"]
const aliasHasActiveFilters = computed(() => ALIAS_ACTIVE_KEYS.some((key) => Boolean(props.aliasReviewFilters[key])))
const RELATION_ACTIVE_KEYS = ["relation_type", "relation_kind", "scene_index", "source_chapter_index", "strength_min", "strength_max", "type_kind", "has_quote", "multi_type_only", "has_reverse_candidates", "has_canonical_relation"]
const relationHasActiveFilters = computed(() => RELATION_ACTIVE_KEYS.some((key) => Boolean(props.relationReviewFilters[key])))
const activeFilterCount = (filters) => Object.entries(filters || {}).filter(([key, value]) => !["skip", "limit"].includes(key) && value !== "" && value != null && value !== false).length
const candidateActiveFilterCount = computed(() => activeFilterCount(props.candidateFilters))
const aliasActiveFilterCount = computed(() => activeFilterCount(props.aliasReviewFilters))
const relationActiveFilterCount = computed(() => activeFilterCount(props.relationReviewFilters))

function applyCandidateFilters() {
  void applyCandidateReviewFilters(candidateForm)
}
function applyAliasFilters() {
  void applyAliasReviewFilters(aliasForm, props.aliasReviewFilters)
}
function applyRelationFilters() {
  void applyRelationReviewFilters(relationForm, props.relationReviewFilters)
}

function clearReviewKeyword(kind) {
  if (kind === "candidate") {
    candidateForm.q = ""
    applyCandidateFilters()
  } else if (kind === "alias") {
    aliasForm.q = ""
    applyAliasFilters()
  } else {
    relationForm.q = ""
    applyRelationFilters()
  }
}

// ---- 别名队列派生 ----
const flatAliases = computed(() => props.aliasGroups.flatMap((group) => group.members || []))
const aliasSelectableIds = computed(() => (
  flatAliases.value.filter((item) => !item.managed_by_suggestion).map((item) => aliasKey(item)).filter(Boolean)
))
function groupSelectableIds(group) {
  return (group.members || []).filter((item) => !item.managed_by_suggestion).map((item) => aliasKey(item))
}

watch(flatAliases, (aliases) => {
  reconcileBulkSelection("world-aliases", aliases.filter((item) => !item.managed_by_suggestion).map((item) => aliasKey(item)).filter(Boolean))
}, { immediate: true })

watch(() => props.relationGroups, (groups) => {
  reconcileBulkSelection("world-relation-groups", groups.map((group) => group.group_id))
}, { immediate: true, deep: true })

watch([tab, localCandidates, () => props.aliasGroups, () => props.relationGroups], () => {
  if (!activeKey.value) return
  const exists = tab.value === "objects"
    ? localCandidates.value.some((item) => entityId(item) === activeKey.value)
    : tab.value === "aliases"
      ? props.aliasGroups.some((group) => (group.members || []).some((item) => aliasKey(item) === activeKey.value))
      : props.relationGroups.some((group) => group.group_id === activeKey.value)
  if (!exists) {
    activeKey.value = ""
    mobileDetailOpen.value = false
    void nextTick(() => syncReviewSelection(""))
  }
}, { deep: true, immediate: true })

// ---- 关系组展示 ----
function canonicalTypeLabels(group) {
  return (group.canonical_relations || []).map((item) => reviewTypeLabel("relation", item.relation_type)).join("、")
}
</script>
