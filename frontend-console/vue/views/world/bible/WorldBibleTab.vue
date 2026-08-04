<!--
  WorldBibleTab — world/bible tab（世界书）。
  对应 vanilla worldBibleView（worldBibleView.js）的 render + bindEvents + onLeave。
  DOM class/id/data-action 逐节点保留（e2e 世界书契约）。
-->
<template>
  <section class="world-bible-workspace" ref="rootEl">
    <!-- toolbar -->
    <div class="view-header world-bible-toolbar">
      <div class="view-header__title">
        世界书
        <span class="view-header__count">{{ pages.length }} 个页面</span>
      </div>
      <div class="view-header__actions">
        <span class="world-bible-toolbar__modes" role="group" aria-label="世界书展示模式">
          <button
            v-for="(label, mode) in modeLabels"
            :key="mode"
            class="btn btn-sm"
            :class="{ 'btn-primary': displayMode === mode }"
            data-action="bible-set-display-mode"
            :data-mode="mode"
            :aria-pressed="displayMode === mode"
            @click="setDisplayMode(mode)"
          >{{ label }}</button>
        </span>
        <button class="btn btn-sm btn-primary" data-action="bible-new-page" @click="createPage">新建页面</button>
        <button class="btn btn-sm" data-action="bible-manage-categories" @click="openCategoryManager">管理分类</button>
        <button class="btn btn-sm" data-action="bible-manage-page-templates" @click="openPageTemplateManager">页面模板</button>
        <button class="btn btn-sm" data-action="bible-open-suggestions" @click="openSuggestions">创设建议</button>
        <button class="btn btn-sm" data-action="bible-open-conflicts" @click="openConflicts">冲突检查</button>
      </div>
    </div>

    <!-- ==================== display modes ==================== -->

    <!-- GALLERY mode -->
    <template v-if="displayMode === 'gallery'">
      <div v-if="!pages.length" class="panel world-bible-gallery">
        <div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div>
      </div>
      <div v-else-if="galleryCategory" class="panel world-bible-gallery">
        <div class="world-bible-category-header" :style="{ '--world-bible-type-color': galleryMeta.color }">
          <button class="btn btn-sm" data-action="bible-gallery-back" @click="backToGalleryHome">返回图鉴首页</button>
          <div class="world-bible-category-icon">{{ galleryMeta.symbol }}</div>
          <div>
            <h2>{{ galleryMeta.title }} <span>({{ galleryPages.length }})</span></h2>
            <p>{{ galleryMeta.desc }}</p>
          </div>
        </div>
        <div v-if="galleryPages.length" class="world-bible-page-card-grid">
          <article
            v-for="page in galleryPages"
            :key="page.id"
            class="world-bible-page-card"
            :style="{ '--world-bible-type-color': typeMeta(page.page_type).color }"
          >
            <div class="world-bible-page-card__band"></div>
            <div class="world-bible-page-card__head">
              <div class="world-bible-page-card__icon">{{ typeMeta(page.page_type).symbol }}</div>
              <div class="world-bible-page-card__title">
                <h3>{{ page.title || "未命名页面" }}</h3>
                <div class="world-bible-page-card__meta">
                  <span>{{ typeMeta(page.page_type).title }}</span>
                  <span class="badge" :class="displayStateBadgeClass(worldAssetDisplay(page).displayState)">{{ worldAssetDisplay(page).label }}</span>
                </div>
              </div>
            </div>
            <p class="world-bible-page-card__summary">{{ pageExcerpt(page) }}</p>
            <div class="world-bible-page-card__footer">
              <span>{{ projectionTask?.meta?.page_id === page.id ? `投影：${taskStatusLabel(projectionTask.status || 'pending')}` : '投影：按页查看' }}</span>
            </div>
            <div class="world-bible-page-card__actions">
              <button class="btn btn-sm btn-primary" data-action="bible-open-page-card" :data-page-id="page.id" @click="openPageCard(page.id)">打开编辑</button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state"><p>这个分类下还没有世界书页面。</p></div>
      </div>
      <div v-else class="panel world-bible-gallery">
        <div class="world-bible-gallery__hero">
          <h2>世界书图鉴</h2>
          <p>选择分类查看该类型的页面卡。</p>
        </div>
        <div class="world-bible-category-grid">
          <button
            v-for="(item, index) in categoryItems(true)"
            :key="item.type"
            class="world-bible-category-card"
            type="button"
            data-action="bible-gallery-open"
            :data-category="item.type"
            :style="{ '--world-bible-type-color': item.meta.color, animationDelay: `${index * 0.03}s` }"
            @click="openGalleryCategory(item.type)"
          >
            <span class="world-bible-category-card__band"></span>
            <span class="world-bible-category-card__icon">{{ item.meta.symbol }}</span>
            <span class="world-bible-category-card__name">{{ item.meta.title }}</span>
            <span class="world-bible-category-card__desc">{{ item.meta.desc }}</span>
            <span class="world-bible-category-card__count">{{ item.count }} 个页面</span>
          </button>
        </div>
      </div>
    </template>

    <!-- FILTER mode -->
    <template v-else-if="displayMode === 'filter'">
      <div v-if="!pages.length" class="panel world-bible-filter">
        <div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div>
      </div>
      <div v-else class="panel world-bible-filter">
        <div class="world-bible-section-title">页面分类</div>
        <div class="world-bible-category-grid" role="group" aria-label="世界书页面分类">
          <button
            v-for="(item, index) in categoryItems(true)"
            :key="item.type"
            class="world-bible-category-card"
            :class="{ 'is-active': item.type === activeCategory }"
            type="button"
            data-action="bible-set-category"
            :data-category="item.type"
            :aria-pressed="item.type === activeCategory"
            :style="{ '--world-bible-type-color': item.meta.color, animationDelay: `${index * 0.03}s` }"
            @click="setActiveCategory(item.type)"
          >
            <span class="world-bible-category-card__band"></span>
            <span class="world-bible-category-card__icon">{{ item.meta.symbol }}</span>
            <span class="world-bible-category-card__name">{{ item.meta.title }}</span>
            <span class="world-bible-category-card__desc">{{ item.meta.desc }}</span>
            <span class="world-bible-category-card__count">{{ item.count }} 个页面</span>
          </button>
        </div>
        <div class="world-bible-section-title">{{ filterTitle }} <span>{{ filterPages.length }} 个页面</span></div>
        <div v-if="filterPages.length" class="world-bible-page-card-grid">
          <article
            v-for="page in filterPages"
            :key="page.id"
            class="world-bible-page-card"
            :style="{ '--world-bible-type-color': typeMeta(page.page_type).color }"
          >
            <div class="world-bible-page-card__band"></div>
            <div class="world-bible-page-card__head">
              <div class="world-bible-page-card__icon">{{ typeMeta(page.page_type).symbol }}</div>
              <div class="world-bible-page-card__title">
                <h3>{{ page.title || "未命名页面" }}</h3>
                <div class="world-bible-page-card__meta">
                  <span>{{ typeMeta(page.page_type).title }}</span>
                  <span class="badge" :class="displayStateBadgeClass(worldAssetDisplay(page).displayState)">{{ worldAssetDisplay(page).label }}</span>
                </div>
              </div>
            </div>
            <p class="world-bible-page-card__summary">{{ pageExcerpt(page) }}</p>
            <div class="world-bible-page-card__footer">
              <span>{{ projectionTask?.meta?.page_id === page.id ? `投影：${taskStatusLabel(projectionTask.status || 'pending')}` : '投影：按页查看' }}</span>
            </div>
            <div class="world-bible-page-card__actions">
              <button class="btn btn-sm btn-primary" data-action="bible-open-page-card" :data-page-id="page.id" @click="openPageCard(page.id)">打开编辑</button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state"><p>这个分类下还没有世界书页面。</p></div>
      </div>
    </template>

    <!-- EDITOR mode (default) -->
    <template v-else>
      <!-- synopsis panel -->
      <section class="panel world-bible-synopsis-panel">
        <div class="world-bible-panel__header">
          <div>
            <h2>世界观简介 <span class="badge">作者模式 · P1</span></h2>
            <div class="world-bible-page-meta">只读 AI 派生资料；不会替代确定性的核心世界设定摘要。</div>
          </div>
          <div class="world-bible-panel__actions">
            <button
              class="btn btn-sm btn-primary"
              data-action="bible-refresh-synopsis"
              :disabled="synopsis?.pinned"
              :title="synopsis?.pinned ? '请先取消固定' : ''"
              @click="refreshSynopsis"
            >刷新简介</button>
            <button class="btn btn-sm" data-action="bible-synopsis-history" @click="openSynopsisHistory">版本历史</button>
            <button class="btn btn-sm" data-action="bible-toggle-synopsis-auto" @click="toggleSynopsisAuto">{{ synopsis?.auto_refresh_enabled ? '关闭自动维护' : '启用自动维护' }}</button>
            <button v-if="synopsis?.pinned" class="btn btn-sm" data-action="bible-unpin-synopsis" @click="unpinSynopsis">取消固定并刷新</button>
          </div>
        </div>
        <div class="world-bible-page-meta">
          状态：{{ taskStatusLabel(synopsis?.status || 'missing') }}
          <template v-if="synopsis?.current_revision">
            · v{{ synopsis.current_revision.version_number }} · 约 {{ synopsis.current_revision.token_estimate }} 词元
            <template v-if="synopsis.current_revision.coverage_json?.source_count != null">
              · 覆盖 {{ synopsis.current_revision.coverage_json.source_count }} 个来源
            </template>
          </template>
        </div>
        <pre v-if="synopsis?.current_revision?.rendered_text" class="generate-markdown-pre">{{ synopsis.current_revision.rendered_text }}</pre>
        <div v-else class="world-bible-empty-hint">尚无成功版本；生成中心启用时会使用有界确定性降级资料。</div>
        <details v-if="synopsisTask || (synopsis?.warnings || []).length" class="world-bible-diagnostics">
          <summary>诊断信息</summary>
          <div v-if="synopsisTask">任务 ID：{{ synopsisTask.task_id || '未提供' }}</div>
          <div v-for="(w, i) in (synopsis?.warnings || [])" :key="i" class="world-bible-projection-status__hint">{{ w }}</div>
        </details>
      </section>

      <!-- editor layout -->
      <div class="world-bible-layout">
        <!-- page nav rail (left) — uses workspace-rail to match vanilla renderWorkspaceRail -->
        <details class="workspace-rail world-bible-nav-rail workspace-rail--left" :data-workspace-rail-key="workspaceRailKey" :open="navRailOpen" @toggle="onNavRailToggle">
          <summary class="workspace-rail__summary" aria-label="收起页面">
            <span class="workspace-rail__title">页面</span>
            <span class="workspace-rail__chevron" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </span>
          </summary>
          <div class="workspace-rail__body">
            <aside class="panel world-bible-page-nav">
              <div class="world-bible-page-nav__heading">页面</div>
              <div v-if="!pages.length && !freeDrafts.length" class="world-bible-empty-hint">暂无页面</div>
              <template v-else>
                <button
                  v-for="draft in freeDrafts"
                  :key="draft.id"
                  class="btn btn-sm world-bible-page-btn"
                  :class="{ 'btn-primary': activeDraft?.id === draft.id }"
                  :data-bible-draft-id="draft.id"
                  @click="openDraft(draft.id)"
                >
                  {{ draft.title }} <span class="badge">工作稿</span>
                </button>
                <button
                  v-for="page in pages"
                  :key="page.id"
                  class="btn btn-sm world-bible-page-btn"
                  :class="{ 'btn-primary': activePage?.id === page.id }"
                  :data-bible-page-id="page.id"
                  @click="openPageCard(page.id)"
                >
                  {{ page.title }}<template v-if="draftForPage(page.id)"> <span class="badge">工作稿</span></template>
                </button>
              </template>
            </aside>
          </div>
        </details>

        <!-- editor panel (main) -->
        <main class="panel world-bible-editor-panel">
          <template v-if="editSource">
            <div class="world-bible-source-notice" role="note">资料页，不是事实源。正式设定请编辑对应世界对象；AI 建议不会自动发布。</div>
            <div class="world-bible-panel__header">
              <div>
                <h2>{{ editSource.title }}</h2>
                <div class="world-bible-page-meta">{{ typeMeta(editSource.page_type).label }} · {{ isWorkingDraft ? '工作稿' : statusLabel(activePage?.status) }}</div>
              </div>
              <div class="world-bible-panel__actions">
                <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-improve-with-ai" @click="openInGenerationCenter">用 AI 完善此页</button>
                <button class="btn btn-sm" data-action="bible-save-page" @click="savePage()">保存工作稿</button>
                <button v-if="canPublish" class="btn btn-sm btn-primary" data-action="bible-publish-page" @click="publishDraft">保存并发布</button>
                <button v-if="isWorkingDraft" class="btn btn-sm" data-action="bible-discard-draft" @click="discardDraft">丢弃工作稿</button>
                <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-page-history" @click="openPageHistory">版本历史</button>
                <button v-if="activePage?.id && !isWorkingDraft && activePage?.status !== 'archived'" class="btn btn-sm" data-action="bible-archive-page" @click="archivePage">归档页面</button>
                <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-refresh-projection" @click="refreshProjection(false)">刷新投影</button>
              </div>
            </div>
            <div class="world-bible-editor-layout">
              <div>
                <div class="generate-form-grid">
                  <label>标题
                    <input class="form-input" id="bible-title" :value="editSource.title || ''" maxlength="255" />
                  </label>
                  <label>类别
                    <select class="form-select" id="bible-page-type" :value="editSource.page_type">
                      <option v-for="cat in categoryOptions(editSource.page_type)" :key="cat.category_key" :value="cat.category_key">{{ cat.name }}</option>
                    </select>
                  </label>
                  <label>排序
                    <input class="form-input" id="bible-sort-order" type="number" :value="editSource.sort_order || 0" />
                  </label>
                  <label>页面模板
                    <select class="form-select" id="bible-page-template">
                      <option value="">空白页</option>
                      <option v-for="tpl in pageTemplates" :key="tpl.template_key" :value="tpl.template_key" :selected="editSource.template_key === tpl.template_key">
                        {{ tpl.name }} · v{{ tpl.version_number }}{{ tpl.builtin ? ' · 内置' : '' }}
                      </option>
                    </select>
                  </label>
                </div>
                <div class="world-bible-template-actions">
                  <button class="btn btn-sm" data-action="bible-apply-page-template" @click="applySelectedPageTemplate">应用模板到工作稿</button>
                  <span v-if="editSource.template_key" class="badge">{{ editSource.template_key }} · v{{ editSource.template_version || 1 }}</span>
                </div>
                <label class="bible-ai-field">
                  页面概览
                  <textarea class="form-textarea world-bible-editor" id="bible-free-text" rows="8">{{ editSource.free_text || '' }}</textarea>
                </label>

                <!-- sections -->
                <section class="world-bible-sections">
                  <div class="world-bible-sections__header">
                    <div>
                      <strong>页面分区</strong>
                      <div class="world-bible-page-meta">分区 ID 在发布与恢复时保持稳定，用于 diff 和来源定位。</div>
                    </div>
                    <button class="btn btn-sm" data-action="bible-section-add" @click="addSection">新增分区</button>
                  </div>
                  <div class="world-bible-section-list">
                    <template v-if="sortedSections.length">
                      <article
                        v-for="(section, index) in sortedSections"
                        :key="section.section_id"
                        class="world-bible-section-editor"
                        :data-section-index="index"
                        :data-section-id="section.section_id"
                      >
                        <div class="world-bible-section-editor__toolbar">
                          <span class="badge">{{ section.section_id }}</span>
                          <span class="world-bible-section-editor__actions">
                            <button class="btn btn-sm" data-action="bible-section-up" aria-label="上移分区" @click="moveSection(section.section_id, -1)">↑</button>
                            <button class="btn btn-sm" data-action="bible-section-down" aria-label="下移分区" @click="moveSection(section.section_id, 1)">↓</button>
                            <button class="btn btn-sm" data-action="bible-section-remove" @click="removeSection(section.section_id)">移除</button>
                          </span>
                        </div>
                        <div class="generate-form-grid">
                          <label>标题<input class="form-input" data-section-field="title" maxlength="120" :value="section.title" /></label>
                          <label>类型<select class="form-select" data-section-field="section_type">
                            <option value="markdown" :selected="section.section_type === 'markdown'">markdown</option>
                            <option value="checklist" :selected="section.section_type === 'checklist'">checklist</option>
                            <option value="asset_collection" :selected="section.section_type === 'asset_collection'">asset_collection</option>
                          </select></label>
                          <label>敏感度<select class="form-select" data-section-field="sensitivity_hint">
                            <option value="author_safe" :selected="section.sensitivity_hint === 'author_safe'">author_safe</option>
                            <option value="author_only" :selected="section.sensitivity_hint === 'author_only'">author_only</option>
                            <option value="public_baseline" :selected="section.sensitivity_hint === 'public_baseline'">public_baseline</option>
                          </select></label>
                          <label>投影<select class="form-select" data-section-field="projection_policy">
                            <option value="eligible" :selected="section.projection_policy === 'eligible'">eligible</option>
                            <option value="excluded" :selected="section.projection_policy === 'excluded'">excluded</option>
                          </select></label>
                        </div>
                        <label class="bible-ai-field">
                          分区正文
                          <textarea class="form-textarea" data-section-field="body_markdown" rows="6">{{ section.body_markdown || '' }}</textarea>
                        </label>
                        <label class="bible-ai-field">
                          局部引用 hash（每行一个，必须来自页面级引用）
                          <textarea class="form-textarea" data-section-field="linked_asset_ref_hashes" rows="2">{{ (section.linked_asset_ref_hashes || []).join('\n') }}</textarea>
                        </label>
                      </article>
                    </template>
                    <div v-else class="world-bible-empty-hint">暂无分区；旧页面可继续只使用概览。</div>
                  </div>
                </section>

                <!-- asset refs -->
                <label class="bible-ai-field">
                  关联资产
                  <span class="world-bible-page-meta">按名称选择已采用的对象、关系、地图事实或已发布页面；这里只保存引用，不内联修改资产。</span>
                  <div id="bible-asset-ref-picker"></div>
                  <textarea id="bible-asset-refs" hidden>{{ formatAssetRefs(editSource.linked_asset_refs_json) }}</textarea>
                </label>

                <!-- projection status -->
                <div v-if="activePage?.id" class="world-bible-projection-status">
                  <template v-if="projectionTask">
                    <div>上下文摘要：{{ taskStatusLabel(projectionTask.status || 'pending') }} · 进度 {{ Math.round((projectionTask.progress || 0) * 100) }}%</div>
                    <div v-if="projectionTask.error_message" class="world-bible-projection-status__error">{{ projectionTask.error_message }}</div>
                    <div v-if="projectionConflictHint" class="world-bible-projection-status__hint">{{ projectionConflictHint }}</div>
                    <button
                      v-if="projectionTask.status === 'failed' && projectionTask.available_actions?.includes('retry')"
                      class="btn btn-sm"
                      data-action="bible-retry-projection"
                      :disabled="projectionRetryPending"
                      @click="retryProjectionTask"
                    >{{ projectionRetryPending ? '重试中...' : '重试任务' }}</button>
                    <button
                      v-if="projectionTask.status === 'failed' || projectionTask.status === 'done'"
                      class="btn btn-sm"
                      data-action="bible-force-refresh-projection"
                      @click="refreshProjection(true)"
                    >强制重新刷新</button>
                    <details class="world-bible-diagnostics">
                      <summary>诊断信息</summary>
                      <div>任务 ID：{{ projectionTask.task_id || projectionTask.id || '未提供' }}</div>
                      <div>原始状态：{{ projectionTask.status || 'pending' }}</div>
                    </details>
                  </template>
                  <div v-else class="world-bible-empty-hint world-bible-empty-hint--projection">
                    <div>上下文摘要尚未刷新。</div>
                    <details class="world-bible-diagnostics">
                      <summary>诊断信息</summary>
                      <div>本地恢复键：{{ taskStorageKeyValue }}</div>
                    </details>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="empty-state">
            <p>创建一个世界书页面开始整理设定。</p>
          </div>
        </main>

        <!-- activation inspector (right) -->
        <aside class="panel world-bible-inspector">
          <div class="world-bible-inspector__header">
            <div>
              <strong>AI 参考规则</strong>
              <div class="world-bible-page-meta">资料发布与规则发布相互独立。</div>
            </div>
            <button class="btn btn-sm" data-action="bible-activation-new" @click="openActivationProfileEditor()">新建</button>
          </div>
          <label class="bible-ai-field">
            Activation Profile
            <select class="form-select" id="bible-activation-profile" v-model="activeActivationProfileId">
              <option value="">未选择</option>
              <option v-for="prof in activationProfiles" :key="prof.id" :value="prof.id">
                {{ prof.name }} · v{{ prof.version_number }} · {{ prof.status }}
              </option>
            </select>
          </label>
          <template v-if="currentProfile">
            <div class="world-bible-profile-summary">
              <div><span class="badge">{{ currentProfile.status }}</span> {{ currentProfile.profile_key }}</div>
              <div>{{ currentProfile.rules_json?.length || 0 }} 条规则 · {{ (currentProfile.applicable_actions_json || []).join('、') }}</div>
            </div>
            <div class="world-bible-inspector__actions">
              <button class="btn btn-sm" data-action="bible-activation-edit" @click="openActivationProfileEditor(currentProfile)">编辑工作稿</button>
              <button class="btn btn-sm btn-primary" data-action="bible-activation-publish" :disabled="currentProfile.status === 'archived'" @click="publishActivationProfile">发布规则</button>
            </div>
            <label class="bible-ai-field">
              Dry-run 任务文本
              <textarea class="form-textarea" id="bible-activation-task" rows="4" placeholder="例如：描写北境商队使用银币"></textarea>
            </label>
            <button class="btn btn-sm" data-action="bible-activation-dry-run" @click="dryRunActivationProfile">执行 Dry-run</button>
          </template>
          <div v-else class="world-bible-empty-hint">创建或选择 Profile 后，可配置正向词、排除词和固定资料目标。</div>
          <!-- activation trace -->
          <div v-if="activationTrace" class="world-bible-activation-trace">
            <div class="world-bible-section-title">本次参考资料</div>
            <div v-for="item in (activationTrace.rule_evaluations || [])" :key="item.rule_id" class="world-bible-trace-rule" :class="{ 'is-matched': item.matched }">
              {{ item.rule_id }} · {{ item.matched ? '命中' : '未命中' }} · {{ item.candidate_count || 0 }} 个候选
              <div v-if="(item.blocked_clauses || []).length">{{ item.blocked_clauses.join('、') }}</div>
            </div>
            <div class="world-bible-trace-group">
              <strong>已加入 ({{ (activationTrace.items || []).length }})</strong>
              <template v-if="(activationTrace.items || []).length">
                <div v-for="item in (activationTrace.items || [])" :key="item.label || item.target?.target_id" class="world-bible-trace-item">
                  <strong>{{ item.label || item.target?.target_id || '未知目标' }}</strong>
                  <div>{{ item.activation_reason || item.source || '' }} · {{ item.token_after ?? item.token_before ?? 0 }} tokens</div>
                  <span v-if="item.excluded_reason" class="badge">{{ item.excluded_reason }}</span>
                </div>
              </template>
              <div v-else class="world-bible-empty-hint">无</div>
            </div>
            <div class="world-bible-trace-group">
              <strong>被排除 / 裁剪 ({{ (activationTrace.excluded_items || []).length }})</strong>
              <template v-if="(activationTrace.excluded_items || []).length">
                <div v-for="item in (activationTrace.excluded_items || [])" :key="item.label || item.target?.target_id" class="world-bible-trace-item">
                  <strong>{{ item.label || item.target?.target_id || '未知目标' }}</strong>
                  <div>{{ item.activation_reason || item.source || '' }} · {{ item.token_after ?? item.token_before ?? 0 }} tokens</div>
                  <span v-if="item.excluded_reason" class="badge">{{ item.excluded_reason }}</span>
                </div>
              </template>
              <div v-else class="world-bible-empty-hint">无</div>
            </div>
            <div v-for="(w, i) in (activationTrace.warnings || [])" :key="i" class="world-bible-projection-status__hint">{{ w }}</div>
          </div>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getRouter, getToast, getConfirm, getShowModalHtml, getCloseModal, getEsc, getErrorLog, getConfirmAction } from "../../../bridge/index.js"
import { worldSession } from "../worldSession.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"
import {
  BIBLE_PAGE_TYPES,
  useWorldBible,
} from "./useWorldBible.js"

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "bible" },
  bible: { type: Object, default: null },
  bibleDeepLink: { type: Object, default: () => ({ draftId: "", pageId: "" }) },
})

const rootEl = ref(null)

const modeLabels = { editor: "编辑", gallery: "图鉴", filter: "筛选" }

const {
  displayMode,
  activeCategory,
  galleryCategory,
  activeActivationProfileId,
  activationTrace,
  activePage,
  activeDraft,
  editSource,
  isWorkingDraft,
  sectionsSignal,
  synopsis,
  synopsisTask,
  projectionTask,
  projectionConflictHint,
  projectionRetryPending,

  pages,
  categories,
  drafts,
  pageTemplates,
  activationProfiles,

  initialize,
  onBeforeUnmount: cleanup,
  setDisplayMode,
  setActiveCategory,
  openGalleryCategory,
  backToGalleryHome,
  openPageCard,
  openDraft,
  createPage,
  savePage,
  publishDraft,
  discardDraft,
  applySelectedPageTemplate,
  addSection,
  removeSection,
  moveSection,
  refreshProjection,
  retryProjectionTask,
  refreshSynopsis,
  toggleSynopsisAuto,
  openSynopsisHistory,
  unpinSynopsis,
  dryRunActivationProfile,
  openInGenerationCenter,
  openSuggestions,
  openConflicts,
  openCategoryManager,
  openPageTemplateManager,
  openPageHistory,
  archivePage,

  typeMeta,
  categoryItems,
  pagesForCategory,
  statusLabel,
  taskStatusLabel,
  pageExcerpt,
  categoryOptions,
  formatAssetRefs,
  parseAssetRefs,
  captureSectionsFromDom,
  readSectionsFromDom,
  rerenderSectionEditor,
  editorHasUnsavedChanges,
  esc,
} = useWorldBible(props)

// ---- computed locals ----
const freeDrafts = computed(() => drafts.value.filter((d) => !d.page_id))
const canPublish = computed(() => activePage.value?.status !== "archived")
const currentProfile = computed(() => activationProfiles.value.find((p) => p.id === activeActivationProfileId.value) || null)
const galleryMeta = computed(() => {
  const meta = typeMeta(galleryCategory.value || "custom")
  return meta
})
const galleryPages = computed(() => pagesForCategory(galleryCategory.value || ""))
const filterTitle = computed(() => activeCategory.value === "all" ? "全部页面" : typeMeta(activeCategory.value).title)
const filterPages = computed(() => pagesForCategory(activeCategory.value))

// Sorted sections from edit source
const sortedSections = computed(() => {
  // Force reactivity on sections signal
  sectionsSignal.value
  const source = editSource.value
  if (!source?.sections_json) return []
  const items = Array.isArray(source.sections_json) ? [...source.sections_json] : []
  items.sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0)
    || String(a.section_id || "").localeCompare(String(b.section_id || "")))
  return items
})

function draftForPage(pageId) {
  if (!pageId) return null
  return drafts.value.find((d) => d.page_id === pageId) || null
}

// workspace rail key (match vanilla workspaceRailKey)
const workspaceRailKey = computed(() =>
  `workspace-rail:${props.projectId || 'global'}:world-bible:pages`
)

// nav rail open/closed state (from sessionStorage, matching vanilla renderWorkspaceRail)
const navRailOpen = ref(readNavRailState())
function readNavRailState() {
  try {
    const stored = sessionStorage.getItem(workspaceRailKey.value)
    if (stored === 'open') return true
    if (stored === 'closed') return false
  } catch { /* ignore */ }
  return true // default open
}
function onNavRailToggle(event) {
  const open = event.target.open
  try {
    sessionStorage.setItem(workspaceRailKey.value, open ? 'open' : 'closed')
  } catch { /* ignore */ }
  navRailOpen.value = open
}

// task storage key for display
const taskStorageKeyValue = computed(() => {
  if (!activePage.value?.id || !props.projectId) return ""
  return `worldBibleProjection:${props.projectId}:${activePage.value.id}:context_brief`
})

// ---- activation profile editor ----
function openActivationProfileEditor(profile = null) {
  const rule = profile?.rules_json?.[0] || null
  const target = rule?.select?.target_refs?.[0]
    || (activePage.value?.id ? { target_type: "world_bible_page", target_id: activePage.value.id } : {})
  const body = `
    <p class="world-bible-empty-hint">简单模式只支持确定性词匹配、固定 TargetRef、优先级和预算；不支持 regex、随机、Prompt role 或递归。</p>
    <div class="form-group"><label>Profile key</label><input class="form-input" id="bible-profile-key" value="${esc(profile?.profile_key || "writing.world_bible")}" ${profile ? "disabled" : ""} /></div>
    <div class="form-group"><label>名称</label><input class="form-input" id="bible-profile-name" value="${esc(profile?.name || "场景写作世界资料")}" /></div>
    <div class="form-group"><label>适用操作</label><input class="form-input" id="bible-profile-action" value="${esc(profile?.applicable_actions_json?.[0] || "writing.generate")}" /></div>
    <div class="form-group"><label>规则名称</label><input class="form-input" id="bible-rule-name" value="${esc(rule?.name || "命中关键词时加入资料")}" /></div>
    <div class="form-group"><label>正向词（逗号分隔）</label><input class="form-input" id="bible-rule-positive" value="${esc((rule?.match?.positive_terms || []).join(","))}" /></div>
    <div class="form-group"><label>排除词（逗号分隔）</label><input class="form-input" id="bible-rule-negative" value="${esc((rule?.match?.negative_terms || []).join(","))}" /></div>
    <div class="form-group">
      <label>固定资料目标</label>
      <div id="bible-rule-target-picker"></div>
      <input type="hidden" id="bible-rule-target" value="${esc(target?.target_type && target?.target_id ? `${target.target_type}:${target.target_id}` : "")}" />
    </div>
    <p class="form-help">只可选择已采用的世界对象或已发布的世界书页面。</p>
    <div class="generate-form-grid">
      <label>优先级<input class="form-input" id="bible-rule-priority" type="number" min="0" max="1000" value="${esc(rule?.rank?.priority ?? 700)}" /></label>
      <label>Top-K<input class="form-input" id="bible-rule-top-k" type="number" min="1" max="256" value="${esc(rule?.rank?.top_k ?? 12)}" /></label>
      <label>Token cap<input class="form-input" id="bible-rule-token-cap" type="number" min="64" max="32000" value="${esc(rule?.rank?.token_cap ?? 1200)}" /></label>
    </div>
  `
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  showModalHtml(profile ? "编辑 AI 参考规则工作稿" : "新建 AI 参考规则", body, [{
    text: "保存工作稿",
    class: "btn-primary",
    handler: () => saveActivationProfileEditor(profile),
  }], { size: "large" })
  mountActivationTargetPicker(target)
}

function mountActivationTargetPicker(target) {
  const root = document.getElementById("bible-rule-target-picker")
  if (!root) return
  const picker = createReferencePicker({
    root,
    projectId: props.projectId,
    sources: assetRefSources().filter((s) => s.kind === "core_entity" || s.kind === "world_bible_page"),
    placeholder: "按名称搜索资料目标",
    onChange: (_items, refs) => {
      const input = document.getElementById("bible-rule-target")
      if (input) input.value = refs[0] ? `${refs[0].kind}:${refs[0].id}` : ""
    },
  })
  if (target?.target_id) {
    picker.resolve([{ kind: canonicalAssetRefType(target.target_type), id: target.target_id }])
  }
  // Store picker ref for cleanup
  window.__bibleActivationTargetPicker = picker
}

function canonicalAssetRefType(type) {
  if (["core_entity", "entity", "profile", "event"].includes(type)) return "core_entity"
  if (["relation", "entity_relation"].includes(type)) return "entity_relation"
  if (["world_bible_page", "page"].includes(type)) return "world_bible_page"
  return type
}

function assetRefSources() {
  const api = getApi()
  return [
    {
      kind: "core_entity", label: "世界对象",
      search: async (query, { projectId, limit }) => {
        const data = await api.world.listEntities({ novel_id: projectId, display_state: "active", q: query || undefined, skip: 0, limit })
        return (data?.items || []).filter((item) => item?.status === "canonical").map((item) => ({
          kind: "core_entity", id: item?.id || item?.entity_id,
          label: item?.name || "未命名对象",
          description: [item?.entity_type || "世界对象", item?.summary || item?.description].filter(Boolean).join(" · "),
          status: worldAssetDisplay(item).label, unavailable: item?.status !== "canonical",
        }))
      },
      resolve: async (ids, { projectId }) => Promise.all(ids.map(async (id) => {
        try {
          const item = await api.world.getEntity(id, projectId)
          return { kind: "core_entity", id: item?.id || item?.entity_id, label: item?.name || "未命名对象", description: [item?.entity_type || "世界对象", item?.summary || item?.description].filter(Boolean).join(" · "), status: worldAssetDisplay(item).label, unavailable: item?.status !== "canonical" }
        } catch { return { kind: "core_entity", id, label: "不可用引用", unavailable: true } }
      })),
    },
    {
      kind: "world_bible_page", label: "世界书页面",
      search: async (query) => {
        const needle = String(query || "").toLowerCase()
        return pages.value.filter((p) => ["canonical", "confirmed"].includes(p.status))
          .filter((p) => !needle || String(p.title || "").toLowerCase().includes(needle))
          .slice(0, 20)
          .map((p) => ({ kind: "world_bible_page", id: p.id, label: p.title || "未命名世界书页面", description: typeMeta(p?.page_type).label, status: "已发布" }))
      },
      resolve: async (ids) => Promise.all(ids.map(async (id) => {
        const loaded = pages.value.find((p) => p.id === id)
        if (loaded) return { kind: "world_bible_page", id: loaded.id, label: loaded.title || "未命名世界书页面", description: typeMeta(loaded?.page_type).label, status: "已发布" }
        try {
          const p = await api.world.getBiblePage(id, props.projectId)
          return { kind: "world_bible_page", id: p.id, label: p.title || "未命名世界书页面", description: typeMeta(p?.page_type).label, status: "已发布" }
        } catch { return { kind: "world_bible_page", id, label: "不可用引用", unavailable: true } }
      })),
    },
  ]
}

async function saveActivationProfileEditor(profile) {
  const splitTerms = (id) => String(document.getElementById(id)?.value || "")
    .split(/[,，\n]+/).map((v) => v.trim()).filter(Boolean)
  const action = document.getElementById("bible-profile-action")?.value?.trim() || ""
  const positive = splitTerms("bible-rule-positive")
  const rawTarget = document.getElementById("bible-rule-target")?.value?.trim() || ""
  const separator = rawTarget.indexOf(":")
  if (!action || !positive.length || separator < 1) {
    getToast()("请填写适用操作、至少一个正向词和有效资料目标", "warning")
    return
  }
  const rule = {
    rule_id: profile?.rules_json?.[0]?.rule_id || `rule_${Date.now().toString(36)}`,
    name: document.getElementById("bible-rule-name")?.value?.trim() || "资料规则",
    enabled: true,
    scope: { actions: [action], modes: ["author_safe", "author_full"], match_sources: ["task_text", "current_scene_text", "explicit_focus"] },
    match: { positive_terms: positive, negative_terms: splitTerms("bible-rule-negative"), positive_logic: "any", negative_logic: "any", mode: "normalized_substring" },
    select: {
      target_refs: [{ target_type: rawTarget.slice(0, separator).trim(), target_id: rawTarget.slice(separator + 1).trim(), target_path: "" }],
      expand_page_links: true, relation_types: [], max_depth: 1,
    },
    rank: { priority: Number(document.getElementById("bible-rule-priority")?.value || 700), top_k: Number(document.getElementById("bible-rule-top-k")?.value || 12), token_cap: Number(document.getElementById("bible-rule-token-cap")?.value || 1200) },
  }
  try {
    const name = document.getElementById("bible-profile-name")?.value?.trim() || "AI 参考规则"
    const api = getApi()
    const saved = profile
      ? await api.context.updateActivationProfile(profile.id, { base_version_number: profile.version_number, name, applicable_actions_json: [action], rules_json: [rule] }, props.projectId)
      : await api.context.createActivationProfile({ novel_id: props.projectId, profile_key: document.getElementById("bible-profile-key")?.value?.trim() || "", name, applicable_actions_json: [action], rules_json: [rule] })
    closeModal()
    window.__bibleActivationTargetPicker?.destroy?.()
    window.__bibleActivationTargetPicker = null
    activeActivationProfileId.value = saved.id
    activationTrace.value = null
    getToast()("规则工作稿已保存；发布前不会影响真实调用", "success")
    getRouter().refresh()
  } catch (err) {
    getToast()(err.message || "保存规则失败", "error")
  }
}

async function publishActivationProfile() {
  const profile = currentProfile.value
  if (!profile) return
  getConfirmAction()("发布此 Activation Profile？后续显式启用它的 AI 调用将固定使用该 revision。", async () => {
    try {
      const api = getApi()
      const saved = await api.context.publishActivationProfile(profile.id, { base_version_number: profile.version_number, revision_reason: "manual_publish" }, props.projectId)
      activeActivationProfileId.value = saved.id
      getToast()("AI 参考规则已发布", "success")
      getRouter().refresh()
    } catch (err) {
      getToast()(err.message || "发布规则失败", "error")
    }
  })
}

// ---- lifecycle ----
onMounted(() => {
  rootEl.value?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  mountAssetRefPicker()
})

onBeforeUnmount(() => {
  cleanup()
  window.__bibleActivationTargetPicker?.destroy?.()
  window.__bibleActivationTargetPicker = null
})

function mountAssetRefPicker() {
  const root = document.getElementById("bible-asset-ref-picker")
  if (!root) return
  const input = document.getElementById("bible-asset-refs")
  if (!input) return
  let wireRefs = []
  try {
    wireRefs = parseAssetRefs(input.value || "")
  } catch { wireRefs = [] }
  const picker = createReferencePicker({
    root,
    projectId: props.projectId,
    sources: window.__bibleAssetRefSources || assetRefSources(),
    mode: "multiple",
    maxItems: 50,
    placeholder: "按名称搜索关联资产",
    onOpen: (item) => openAssetRef(item.kind, item.id),
    onChange: (_items, refs) => {
      const wireRefs2 = []
      try {
        const existing = parseAssetRefs(input.value || "")
        const originals = existing.filter((ref) => refs.some((r) => canonicalAssetRefType(assetRefType(ref)) === r.kind && assetRefId(ref) === r.id))
        const news = refs.filter((r) => !existing.some((ref) => canonicalAssetRefType(assetRefType(ref)) === r.kind && assetRefId(ref) === r.id))
        input.value = formatAssetRefs([...originals, ...news.map((r) => ({ type: r.kind, id: r.id }))])
      } catch {
        input.value = formatAssetRefs(refs.map((r) => ({ type: r.kind, id: r.id })))
      }
    },
  })
  const canonicalRefs = wireRefs.map((ref) => ({ kind: canonicalAssetRefType(assetRefType(ref)), id: assetRefId(ref) })).filter((ref) => ref.kind && ref.id)
  picker.resolve(canonicalRefs)
  window.__bibleAssetRefPicker = picker
}

function openAssetRef(type, id) {
  const router = getRouter()
  if (["world_bible_page", "page"].includes(type)) { openPageCard(id); return }
  if (["relation", "entity_relation"].includes(type)) { router.navigate("world", "relations"); return }
  if (type === "map_fact") { router.navigate("map", null, true, new URLSearchParams({ projectId: props.projectId, mode: "overview" })); return }
  if (["core_entity", "entity", "profile", "event"].includes(type)) { router.navigate("world", "objects"); return }
  getToast()("该引用类型暂无可用的编辑入口", "warning")
}

function assetRefType(ref) {
  return ref?.type || ref?.source_type || ref?.target_type || ""
}

function assetRefId(ref) {
  return ref?.id || ref?.source_id || ref?.target_id || ""
}


function getModalHelpers() {
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  return { showModalHtml, closeModal }
}



</script>
