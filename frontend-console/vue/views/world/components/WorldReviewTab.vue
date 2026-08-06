<!--
  WorldReviewTab — world review（待处理）三队列：review-objects / review-aliases /
  review-relations（vanilla _renderReviewQueue 及各工作区的 Vue 化）。
  筛选变更一律 navigate 写 query；草稿/错误/批量选择落 worldSession；
  候选乐观更新走本地镜像（props 只读），钩子注册进 worldEntityOps。
-->
<template>
  <div>
    <!-- 二级 tab 导航（vanilla _renderReviewQueue 822-836） -->
    <div class="subnav subnav-secondary" style="margin-bottom:12px;">
      <button type="button" class="subnav-item" :class="{ active: tab === 'review-objects' }" :aria-current="tab === 'review-objects' ? 'page' : undefined" data-action="nav-review-objects" @click="navigateSub('review-objects')">对象 ({{ reviewCounts.objects || 0 }})</button>
      <button type="button" class="subnav-item" :class="{ active: tab === 'review-aliases' }" :aria-current="tab === 'review-aliases' ? 'page' : undefined" data-action="nav-review-aliases" @click="navigateSub('review-aliases')">别名 ({{ reviewCounts.aliases || 0 }})</button>
      <button type="button" class="subnav-item" :class="{ active: tab === 'review-relations' }" :aria-current="tab === 'review-relations' ? 'page' : undefined" data-action="nav-review-relations" @click="navigateSub('review-relations')">关系 ({{ reviewCounts.relations || 0 }})</button>
    </div>

    <!-- ==================== review-objects ==================== -->
    <template v-if="tab === 'review-objects'">
      <!-- vanilla _renderCandidatesList 收尾处 `renderBulkToolbar(...) + html`：批量条前置（仅非空时存在） -->
      <WorldBulkToolbar
        v-if="localCandidates.length"
        scope="world-candidates"
        :actions="[
          { action: 'accept-candidates', label: '批量采用', className: 'btn-primary' },
          { action: 'ignore-candidates', label: '批量忽略/设为临时', className: 'btn-danger' },
        ]"
        noun="待处理项"
        hint="合并项仍需逐条选择目标对象"
        :select-all-ids="localCandidates.map(entityIdOf)"
        select-all-label="全选当前待处理项"
        @run="(action) => runReviewBulkAction('world-candidates', action, localCandidates)"
      />
      <WorldFilterPanel panel-key="review-objects" :has-active-filters="candidateHasActiveFilters" :project-id="projectId">
        <div class="filter-bar world-review-filters" style="margin-bottom:12px;">
          <select id="review-candidate-entity-type" v-model="candidateForm.entity_type" class="form-select" aria-label="对象类型筛选">
            <option value="">全部类型</option>
            <option v-for="type in entityTypes" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
          <select id="review-candidate-action" v-model="candidateForm.suggested_action" class="form-select" aria-label="建议动作筛选">
            <option value="">全部动作</option>
            <option v-for="(label, value) in suggestedActionLabels" :key="value" :value="value">{{ label }}</option>
          </select>
          <input id="review-candidate-source" v-model="candidateForm.source" class="form-input" placeholder="来源" aria-label="来源筛选" />
          <details class="world-diagnostic-filter" :open="Boolean(candidateFilters.workflow_id)">
            <summary>诊断筛选</summary>
            <input id="review-candidate-workflow" v-model="candidateForm.workflow_id" class="form-input" data-diagnostic-field placeholder="处理批次编号" aria-label="按处理批次编号诊断筛选" />
          </details>
          <input id="review-candidate-scene" v-model="candidateForm.scene_index" class="form-input" placeholder="场景序号" aria-label="场景序号筛选" />
          <input id="review-candidate-chapter" v-model="candidateForm.source_chapter_index" class="form-input" placeholder="章节" aria-label="章节筛选" />
          <input id="review-candidate-confidence-min" v-model="candidateForm.confidence_min" class="form-input" placeholder="最低置信度" aria-label="最低置信度" />
          <input id="review-candidate-confidence-max" v-model="candidateForm.confidence_max" class="form-input" placeholder="最高置信度" aria-label="最高置信度" />
          <button class="btn btn-sm" data-action="apply-candidate-review-filters" @click="applyCandidateFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-candidate-review-filters" @click="resetCandidateReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>

      <template v-if="candidateLoadError && localCandidates.length === 0">
        <div class="empty-state" role="alert">
          <div class="empty-icon">!</div>
          <p>{{ candidateLoadError }}</p>
          <button class="btn btn-primary world-review-touch-target" data-action="retry-candidate-load" @click="retryLoad">重试加载</button>
        </div>
      </template>
      <template v-else-if="localCandidates.length === 0">
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>没有待处理对象。</p>
          <p>AI 或导入提出、尚未采用的对象会出现在这里，你可以决定如何处置。</p>
        </div>
      </template>
      <template v-else>
        <p class="world-list-description">
          以下内容尚未进入当前有效设定。请结合来源和证据决定采用、合并、设为别名或忽略。
        </p>

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
              <WorldCandidateGroupItem v-for="candidate in group.candidates" :key="entityIdOf(candidate)" :candidate="candidate" badge-label="建议别名" :action-options="{}" />
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
              <WorldCandidateGroupItem v-for="candidate in group" :key="entityIdOf(candidate)" :candidate="candidate" badge-label="相似名称" :action-options="{ allowAlias: true, allowMerge: true }" />
            </div>
          </section>
        </div>

        <!-- 普通候选表（vanilla _renderCandidatesList 1930-1976） -->
        <table v-if="regularCandidates.length" class="data-table table-card-list">
          <thead>
            <tr>
              <th class="selection-cell"><WorldSelectionInput mode="all" scope="world-candidates" :ids="regularCandidates.map(entityIdOf)" label="全选普通待处理项" /></th>
              <th>名称</th>
              <th>类型</th>
              <th>重要度</th>
              <th>建议动作</th>
              <th>证据</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="candidate in regularCandidates" :key="entityIdOf(candidate)" :data-id="entityIdOf(candidate)">
              <td class="selection-cell"><WorldSelectionInput mode="one" scope="world-candidates" :id="entityIdOf(candidate)" :label="`选择 ${candidate.name || '待处理项'}`" /></td>
              <td data-label="名称">{{ candidate.name }}</td>
              <td data-label="类型" class="world-table-cell--type">{{ candidate.entity_type }}</td>
              <td data-label="重要度">{{ candidate.importance ?? candidate.importance_score ?? "-" }}</td>
              <td data-label="建议动作"><span class="candidate-action-badge" :class="`candidate-action-badge--${actionLabelOf(candidate).action}`">{{ actionLabelOf(candidate).label }}</span></td>
              <td data-label="证据" style="max-width:220px;color:var(--text-dim);font-size:12px;"><WorldInlineEvidence :pairs="inlineEvidencePairs(candidateMeta(candidate))" /></td>
              <td data-label="操作"><div class="row-actions"><WorldCandidateActions :candidate="candidate" :action-options="{ allowAlias: true, allowMerge: true }" /></div></td>
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
    <template v-else-if="tab === 'review-aliases'">
      <p class="world-list-description">处理尚未采用的别名。别名不独立创建对象。</p>
      <div class="review-search-bar">
        <input id="review-alias-q" v-model="aliasForm.q" class="form-input" placeholder="搜索别名、对象或引用" aria-label="搜索待处理别名" />
        <button class="btn btn-sm btn-primary" data-action="apply-alias-review-filters" @click="applyAliasFilters">搜索</button>
      </div>
      <div class="review-quick-filters">
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="multi_alias_only" data-filter-value="true" @click="setReviewQuickFilter('alias', 'multi_alias_only', 'true', aliasReviewFilters)">同对象多别名</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="type_kind" data-filter-value="custom" @click="setReviewQuickFilter('alias', 'type_kind', 'custom', aliasReviewFilters)">自定义类型</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="has_quote" data-filter-value="false" @click="setReviewQuickFilter('alias', 'has_quote', 'false', aliasReviewFilters)">缺少引用</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="confidence_min" data-filter-value="0.95" @click="setReviewQuickFilter('alias', 'confidence_min', '0.95', aliasReviewFilters)">高置信度</button>
      </div>
      <WorldReviewFilterChips kind="alias" :filters="aliasReviewFilters" />
      <WorldFilterPanel panel-key="review-aliases" :has-active-filters="aliasHasActiveFilters" :project-id="projectId">
        <div class="filter-bar" style="margin-bottom:12px;">
          <input id="review-alias-source" v-model="aliasForm.source" class="form-input" placeholder="来源" aria-label="按来源筛选待处理别名" />
          <details class="world-diagnostic-filter" :open="Boolean(aliasReviewFilters.workflow_id)">
            <summary>诊断筛选</summary>
            <input id="review-alias-workflow" v-model="aliasForm.workflow_id" class="form-input" data-diagnostic-field placeholder="处理批次编号" aria-label="按处理批次编号诊断筛选待处理别名" />
          </details>
          <input id="review-alias-scene" v-model="aliasForm.scene_index" class="form-input" placeholder="场景序号" aria-label="按场景序号筛选待处理别名" />
          <input id="review-alias-chapter" v-model="aliasForm.source_chapter_index" class="form-input" placeholder="章节序号" aria-label="按章节序号筛选待处理别名" />
          <input id="review-alias-confidence-min" v-model="aliasForm.confidence_min" class="form-input" placeholder="最低置信度" aria-label="待处理别名最低置信度" />
          <select id="review-alias-type-kind" v-model="aliasForm.type_kind" class="form-select" aria-label="待处理别名类型范围">
            <option value="">全部类型</option>
            <option value="recommended">推荐类型</option>
            <option value="custom">自定义类型</option>
          </select>
          <select id="review-alias-page-size" v-model.number="aliasForm.limit" class="form-select" aria-label="待处理别名每页数量">
            <option :value="20">每页 20 组</option>
            <option :value="50">每页 50 组</option>
          </select>
          <button class="btn btn-sm" data-action="apply-alias-review-filters" @click="applyAliasFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-alias-review-filters" @click="resetAliasReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>

      <div v-if="aliasReviewLoadError" class="empty-state">
        <p>加载待处理别名失败。</p>
        <p class="world-text-dim">{{ aliasReviewLoadError }}</p>
      </div>
      <div v-else-if="!flatAliases.length" class="empty-state">
        <p>没有待处理别名。</p>
        <p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p>
      </div>
      <template v-else>
        <WorldBulkToolbar
          v-if="aliasSelectableIds.length"
          scope="world-aliases"
          :actions="[
            { action: 'review-aliases-batch', label: '批量采用', className: 'btn-primary' },
            { action: 'ignore-aliases-batch', label: '批量忽略', className: 'btn-danger' },
          ]"
          noun="别名"
          hint="未编辑条目会原样采用；全选仅作用于当前页"
          :select-all-ids="aliasSelectableIds"
          select-all-label="全选当前页别名"
          @run="(action) => runReviewBulkAction('world-aliases', action, flatAliases)"
        />
        <div class="review-group-list">
          <section v-for="group in aliasGroups" :key="group.group_id" class="review-group-card" :data-group-id="group.group_id">
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
              <article v-for="item in group.members || []" :key="aliasKeyOf(item)" class="review-member-row review-member-row--selectable">
                <div class="selection-cell">
                  <WorldSelectionInput v-if="!item.managed_by_suggestion" mode="one" scope="world-aliases" :id="aliasKeyOf(item)" :label="`选择别名 ${item.alias}`" />
                </div>
                <div class="review-member-row__main">
                  <div>
                    <strong>{{ item.alias }}</strong> <span>{{ reviewTypeLabel('alias', item.alias_type) }}</span>
                    <span v-if="item.type_kind === 'custom'" class="badge badge-draft">自定义</span>
                    <span v-if="session.aliasReviewDrafts[aliasKeyOf(item)]" class="badge badge-canonical">已编辑</span>
                  </div>
                  <div v-if="item.suggested_alias_type && item.suggested_alias_type !== item.alias_type" class="review-suggestion">建议类型：{{ reviewTypeLabel('alias', item.suggested_alias_type) }}（仅点击采用后才会修改）</div>
                  <WorldEvidenceSummary :item="item" kind="alias" :numeric-value="item.confidence" />
                  <div v-if="session.aliasReviewErrors[aliasKeyOf(item)]" class="review-item-error" role="alert">{{ session.aliasReviewErrors[aliasKeyOf(item)] }}</div>
                </div>
                <span v-if="item.managed_by_suggestion" class="world-text-dim">随对象建议处理</span>
                <button v-else class="btn btn-sm btn-primary" data-action="prepare-alias-review" :data-entity-id="item.entity_id" :data-alias="item.alias" @click="showAliasReviewDecisionForm(item.entity_id, item.alias)">编辑决策</button>
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
    <template v-else-if="tab === 'review-relations'">
      <p class="world-list-description">处理 AI 抽取或导入提出、尚未采用的关系。</p>
      <div class="review-search-bar">
        <input id="review-relation-q" v-model="relationForm.q" class="form-input" placeholder="搜索对象、关系类型或描述" aria-label="搜索待处理关系" />
        <button class="btn btn-sm btn-primary" data-action="apply-relation-review-filters" @click="applyRelationFilters">搜索</button>
      </div>
      <div class="review-quick-filters">
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="multi_type_only" data-filter-value="true" @click="setReviewQuickFilter('relation', 'multi_type_only', 'true', relationReviewFilters)">同对象对多类型</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="type_kind" data-filter-value="custom" @click="setReviewQuickFilter('relation', 'type_kind', 'custom', relationReviewFilters)">自定义类型</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="has_quote" data-filter-value="false" @click="setReviewQuickFilter('relation', 'has_quote', 'false', relationReviewFilters)">缺少引用</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="strength_max" data-filter-value="0.69" @click="setReviewQuickFilter('relation', 'strength_max', '0.69', relationReviewFilters)">低强度</button>
        <span class="review-scene-quick-filter"><input id="review-relation-scene-quick" v-model="relationForm.scene_index" class="form-input" placeholder="场景序号" aria-label="快速按场景筛选" /><button class="btn btn-sm" data-action="apply-relation-scene-quick" @click="setReviewQuickFilter('relation', 'scene_index', relationForm.scene_index.trim(), relationReviewFilters)">按场景筛选</button></span>
      </div>
      <WorldReviewFilterChips kind="relation" :filters="relationReviewFilters" />
      <WorldFilterPanel panel-key="review-relations" :has-active-filters="relationHasActiveFilters" :project-id="projectId">
        <div class="filter-bar" style="margin-bottom:12px;">
          <input id="review-relation-type" v-model="relationForm.relation_type" class="form-input" placeholder="关系类型" aria-label="按关系类型筛选待处理关系" />
          <input id="review-relation-scene" v-model="relationForm.scene_index" class="form-input" placeholder="场景序号" aria-label="按场景序号筛选待处理关系" />
          <input id="review-relation-source-chapter" v-model="relationForm.source_chapter_index" class="form-input" placeholder="章节序号" aria-label="按章节序号筛选待处理关系" />
          <input id="review-relation-strength-min" v-model="relationForm.strength_min" class="form-input" placeholder="最低强度" aria-label="待处理关系最低强度" />
          <select id="review-relation-type-kind" v-model="relationForm.type_kind" class="form-select" aria-label="待处理关系类型范围">
            <option value="">全部类型</option>
            <option value="recommended">推荐类型</option>
            <option value="custom">自定义类型</option>
          </select>
          <select id="review-relation-page-size" v-model.number="relationForm.limit" class="form-select" aria-label="待处理关系每页数量">
            <option :value="20">每页 20 组</option>
            <option :value="50">每页 50 组</option>
          </select>
          <button class="btn btn-sm" data-action="apply-relation-review-filters" @click="applyRelationFilters">筛选</button>
          <button class="btn btn-sm" data-action="reset-relation-review-filters" @click="resetRelationReviewFilters">清空</button>
        </div>
      </WorldFilterPanel>

      <div v-if="relationReviewLoadError" class="empty-state">
        <p>加载待处理关系失败。</p>
        <p class="world-text-dim">{{ relationReviewLoadError }}</p>
      </div>
      <div v-else-if="!relationGroups.length" class="empty-state">
        <p>没有待处理关系。</p>
        <p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p>
      </div>
      <template v-else>
        <WorldBulkToolbar
          scope="world-relation-groups"
          :actions="[
            { action: 'apply-relation-decisions', label: '应用已准备决策', className: 'btn-primary' },
            { action: 'ignore-relation-groups', label: '整组忽略', className: 'btn-danger' },
          ]"
          noun="关系组"
          hint="先在组内准备采用/归并决策；全选仅作用于当前页"
          :select-all-ids="relationGroups.map((group) => group.group_id)"
          select-all-label="全选当前页关系组"
          @run="(action) => runReviewBulkAction('world-relation-groups', action, relationGroups)"
        />
        <div class="review-group-list">
          <section v-for="group in relationGroups" :key="group.group_id" class="review-group-card" :data-group-id="group.group_id">
            <header class="review-group-card__header">
              <div class="review-group-card__select"><WorldSelectionInput mode="one" scope="world-relation-groups" :id="group.group_id" :label="`选择 ${group.source_name || '源对象'} 到 ${group.target_name || '目标对象'}`" /></div>
              <div class="review-group-card__title">
                <strong>{{ group.source_name || "未命名对象" }} → {{ group.target_name || "未命名对象" }}</strong>
                <span>{{ group.member_count }} 条候选 · {{ group.evidence_count || 0 }} 条证据</span>
              </div>
              <span class="badge" :class="session.relationReviewDrafts[group.group_id] ? 'badge-canonical' : 'badge-candidate'">{{ relationDraftLabel(group.group_id) }}</span>
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
                <div><strong>{{ reviewTypeLabel('relation', member.relation_type) }}</strong><span v-if="member.type_kind === 'custom'" class="badge badge-draft">自定义</span></div>
                <div class="review-member-row__description">{{ member.description || "暂无描述" }}</div>
                <WorldEvidenceSummary :item="member.evidence_summary || member" kind="relation" :numeric-value="member.strength" />
              </article>
            </div>
            <footer class="review-group-card__actions">
              <button class="btn btn-sm btn-primary" data-action="prepare-relation-review" :data-group-id="group.group_id" @click="showRelationGroupReviewForm(group.group_id)">{{ session.relationReviewDrafts[group.group_id] ? "修改决策" : "处理本组" }}</button>
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
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch, onBeforeUnmount } from "vue"
import { getRouter } from "../../../bridge/index.js"
import { worldSession as session } from "../worldSession.js"
import {
  WORLD_SUGGESTED_ACTION_LABELS,
  WORLD_CANDIDATE_QUERY_KEYS,
} from "../logic/worldQuery.js"
import { reconcileBulkSelection } from "../logic/worldBulkSelection.js"
import { candidateMeta, entityId } from "../logic/worldEntityHelpers.js"
import { registerCandidateListHooks, syncWorldListRegistry } from "../logic/worldEntityOps.js"
import {
  aliasKey,
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
  reviewTypeLabel,
  runReviewBulkAction,
  setReviewQuickFilter,
  showAliasReviewDecisionForm,
  showRelationGroupReviewForm,
  splitCandidateGroups,
  syncReviewRegistry,
} from "../logic/useWorldReview.js"
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
  reviewSubView: { type: String, default: "review-objects" },
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

const tab = computed(() => props.reviewSubView || "review-objects")
const suggestedActionLabels = WORLD_SUGGESTED_ACTION_LABELS
const entityIdOf = entityId
const aliasKeyOf = aliasKey

function navigateSub(sub) {
  getRouter()?.navigate("world", sub)
}

function retryLoad() {
  getRouter()?.refresh?.()
}

// ---- 注册表同步（决策模态/批量按 id 查找） ----
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

// ---- 候选乐观镜像（vanilla _removeCandidateOptimistically/_restoreCandidateSnapshot） ----
const localCandidates = ref([])

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
onBeforeUnmount(() => registerCandidateListHooks({}))

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
const ALIAS_ACTIVE_KEYS = ["source", "workflow_id", "scene_index", "source_chapter_index", "confidence_min", "confidence_max", "has_quote", "type_kind", "multi_alias_only"]
const aliasHasActiveFilters = computed(() => ALIAS_ACTIVE_KEYS.some((key) => Boolean(props.aliasReviewFilters[key])))
const RELATION_ACTIVE_KEYS = ["relation_type", "scene_index", "source_chapter_index", "strength_min", "strength_max", "type_kind", "has_quote", "multi_type_only"]
const relationHasActiveFilters = computed(() => RELATION_ACTIVE_KEYS.some((key) => Boolean(props.relationReviewFilters[key])))

function applyCandidateFilters() {
  void applyCandidateReviewFilters(candidateForm)
}
function applyAliasFilters() {
  void applyAliasReviewFilters(aliasForm, props.aliasReviewFilters)
}
function applyRelationFilters() {
  void applyRelationReviewFilters(relationForm, props.relationReviewFilters)
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

// ---- 关系组展示 ----
function relationDraftLabel(groupId) {
  const draft = session.relationReviewDrafts[groupId]
  return draft
    ? { accept: "已准备：独立采用", merge: "已准备：归并", ignore: "已准备：忽略" }[draft.action]
    : "尚未准备决策"
}

function canonicalTypeLabels(group) {
  return (group.canonical_relations || []).map((item) => reviewTypeLabel("relation", item.relation_type)).join("、")
}
</script>
