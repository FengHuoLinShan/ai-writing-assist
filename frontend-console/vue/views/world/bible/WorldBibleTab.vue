<!--
  WorldBibleTab — world/bible tab（世界书）。
  对应 vanilla worldBibleView（worldBibleView.js）的 render + bindEvents + onLeave。
  DOM class/id/data-action 逐节点保留（e2e 世界书契约）。
-->
<template>
  <section
    class="world-bible-workspace"
    ref="rootEl"
    :inert="editorMutationPending || undefined"
    :aria-busy="editorMutationPending"
  >
    <WorldSidebarToolCard :actions="sidebarActions" show-smart-dedup @select="handleSidebarAction" />
    <!-- 旧扩展动作保留隐藏兼容 seam；创建入口已迁移为 bible-new-resource。 -->
    <span hidden aria-hidden="true">
      <button v-for="(label, mode) in legacyModeLabels" :key="mode" type="button" data-action="bible-set-display-mode" :data-mode="mode" :aria-pressed="displayMode === mode" @click="setDisplayMode(mode)">{{ label }}</button>
      <button type="button" data-action="bible-manage-categories" @click="openCategoryManager">管理分类</button>
      <button type="button" data-action="bible-manage-page-templates" @click="openPageTemplateManager">页面模板</button>
      <button type="button" data-action="bible-open-worldbook-import" @click="worldbookImportOpen = true">导入目录</button>
      <button type="button" data-action="bible-open-suggestions" @click="openSuggestions">创设建议</button>
      <button type="button" data-action="bible-open-conflicts" @click="openConflicts">冲突检查</button>
      <button type="button" data-action="bible-open-graph" @click="setDisplayMode('graph')">关联图</button>
      <button type="button" data-action="bible-inspect-current-page" @click="inspectCurrentPage">{{ semanticInspectionPending ? '停止检修' : '检修当前页' }}</button>
    </span>

    <!-- 编辑器和次级工具仍保留就地状态操作；资料库首页操作移入一级侧栏。 -->
    <div v-if="displayMode !== 'gallery'" class="world-bible-toolbar">
      <div class="world-bible-toolbar__title">
        <h1>资料库</h1>
        <span>{{ displayMode === 'editor' ? '编辑资料页' : '次级资料工具' }}</span>
      </div>
      <div class="world-bible-toolbar__actions">
        <button class="btn btn-sm btn-ghost" type="button" @click="returnToLibrary">← 返回资料库</button>
        <button class="btn btn-sm" type="button" @click="toolDialog = 'more'">更多工具</button>
      </div>
    </div>

    <WorldbookImportPanel
      :project-id="projectId"
      :open="worldbookImportOpen"
      :suggestion-id="bibleDeepLink.worldbookImportSuggestionId || ''"
      @close="worldbookImportOpen = false"
    />

    <p v-if="bible?.detailError" class="form-error" role="alert">{{ bible.detailError }} <button class="btn btn-sm" type="button" @click="getRouter()?.refresh()">重试</button></p>
    <WorldToolDialog :open="Boolean(toolDialog)" :title="toolDialogTitle" @close="toolDialog = ''">
      <WorldHealthPanel
        v-if="toolDialog === 'health'"
        :project-id="projectId"
        :target-type="bibleDeepLink.adoptionPackageId ? 'world_adoption_package' : 'world_bible_draft'"
        :target-id="bibleDeepLink.adoptionPackageId || activeDraft?.id || ''"
        :requires-full-scope="validationRequiresFullScope"
        :initial-run="validationRun"
        :policy-status="validationPolicy"
        :gap-root="healthGapRoot"
        @updated="validationRun = $event"
        @policy-updated="validationPolicy = $event"
        @open-source="openValidationSource"
        @gap-root-needed="openHealthFromLibrary"
      />
      <div v-else-if="toolDialog === 'questions'" class="world-bible-open-questions__list">
        <button v-for="entry in authorOpenQuestions" :key="entry.key" type="button" class="btn world-bible-open-question" :data-bible-open-question-page-id="entry.pageId || undefined" :data-bible-open-question-draft-id="entry.draftId || undefined" @click="openQuestionFromDialog(entry)">
          <span>{{ entry.question }}</span><small>{{ entry.sourceTitle }} · {{ entry.draftId ? "工作稿" : "已发布页" }}</small>
        </button>
        <p v-if="!authorOpenQuestions.length" class="world-bible-empty-hint">当前没有已保存的未决项。</p>
      </div>
      <div v-else-if="toolDialog === 'types'" class="world-more-types">
        <button v-for="type in extraTypeOptions" :key="type.value" type="button" class="btn" @click="selectMoreType(type.value)">{{ type.label }}</button>
      </div>
      <div v-else-if="toolDialog === 'create'" class="world-create-choices">
        <button type="button" class="btn btn-primary" data-action="bible-new-entity-choice" @click="createEntityFromDialog('character')">人物</button><button type="button" class="btn" @click="createEntityFromDialog('location')">地点</button><button type="button" class="btn" @click="createEntityFromDialog('')">其他设定</button>
        <button type="button" class="btn" data-action="bible-new-page-choice" @click="createPageFromDialog">资料页</button>
      </div>
      <div v-else-if="toolDialog === 'more'" class="world-more-tools">
        <button class="btn" type="button" @click="toolDialog = 'health'">世界健康</button>
        <button class="btn" type="button" @click="runDialogAction(openCategoryManager)">管理分类</button>
        <button class="btn" type="button" @click="runDialogAction(openPageTemplateManager)">页面模板</button>
        <button class="btn" type="button" @click="runDialogAction(openObjectTools)">人物与设定工具</button>
        <button class="btn" type="button" @click="runDialogAction(() => setDisplayMode('graph'))">关联图</button>
        <button class="btn" type="button" @click="runDialogAction(() => { worldbookImportOpen = true })">导入目录</button>
        <button class="btn" type="button" @click="runDialogAction(openSuggestions)">创设建议</button>
        <button class="btn" type="button" @click="runDialogAction(openConflicts)">冲突检查</button>
      </div>
    </WorldToolDialog>

    <WorldTopicPickerDialog
      :open="Boolean(topicPickerCard)"
      :topics="libraryTopics"
      :target-title="topicPickerCard?.title || ''"
      :member-topic-ids="topicPickerMemberIds"
      @close="topicPickerCard = null"
      @toggle="toggleTopicMembership"
    />

    <!-- ==================== display modes ==================== -->

    <!-- GALLERY mode -->
    <template v-if="displayMode === 'gallery'">
      <div v-if="galleryCategory" class="panel world-bible-gallery">
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
              <span>{{ projectionTask?.meta?.page_id === page.id ? `写作参考：${taskStatusLabel(projectionTask.status || 'pending')}` : '写作参考：打开后查看' }}</span>
            </div>
            <div class="world-bible-page-card__actions">
              <button class="btn btn-sm btn-primary" data-action="bible-open-page-card" :data-page-id="page.id" @click="openPageCard(page.id)">打开编辑</button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state"><p>这个分类下还没有世界书页面。</p></div>
      </div>
      <div v-else class="panel world-bible-gallery world-library-content">
        <WorldEntityDetail
          v-if="selectedEntity"
          :entity="selectedEntity"
          :project-id="projectId"
          :type-label="cardMeta({ kind: 'entity', typeKey: selectedEntity.entity_type }).label"
          :aliases-open="props.bibleDeepLink?.entitySection === 'aliases'"
          @back="returnToLibrary"
          @edit="editSelectedEntity"
          @create-alias="createAliasForSelectedEntity"
          @edit-alias="editAliasForSelectedEntity"
          @create-task="createTaskForWorldEntity(selectedEntity)"
          @profile-dirty="entityProfileDirty = $event"
          @refresh="refreshCompletedEntity"
          @impact-preview="openImpactPreview('core_entity', selectedEntity.id, selectedEntity.name)"
        />
        <template v-else-if="showTypeHome">
          <div class="world-bible-gallery__hero">
            <h2>人物与世界</h2>
            <p>按主题和类型组织长期创作资料；同一份资料可以出现在多个主题里。</p>
          </div>
          <form class="world-card-filters world-card-filters--home" role="search" @submit.prevent="applyCardFilters()">
            <label class="world-card-filters__search"><span>搜索资料</span><input v-model="cardSearch" type="search" maxlength="120" placeholder="名称、别名或内容" /></label>
            <div class="world-card-filters__actions"><button class="btn btn-sm btn-primary" type="submit">查找</button></div>
          </form>
          <div v-if="props.bible?.entitiesLoadError" class="empty-state" role="alert" data-author-action="retry">
            <p>人物与设定数量暂时没有加载出来；资料页和工作稿仍可使用。</p><button class="btn btn-sm" type="button" @click="retryCards">重新加载</button>
          </div>
          <WorldLibraryHome
            v-if="libraryOverview"
            :overview="libraryOverview"
            :type-options="cardTypeOptions"
            :meta-for="cardMeta"
            @open="openWorldCard"
            @select-topic="selectHomeTopic"
            @select-type="selectTypeCard"
            @select-working="selectTypeCard('working')"
            @create-topic="createTopicFromDirectory({ name: $event, parentId: null })"
            @browse-all="applyCardFilters({})"
          />
          <WorldLibraryTypeGrid v-else :cards="commonTypeCards" :working-count="workingCardCount" @select="selectTypeCard" @more="toolDialog = 'types'" />
        </template>
        <template v-else>
          <div class="world-library-browse">
            <WorldLibraryDirectory
              class="world-library-browse__directory"
              :filters="{ ...cardFilters, unclassified: cardFilters.unclassified }"
              :topics="libraryTopics"
              :total-count="libraryOverview?.totals?.all ?? 0"
              :working-count="libraryOverview?.totals?.working ?? workingCardCount"
              :unclassified-count="libraryOverview?.totals?.unclassified ?? 0"
              :favorite-count="libraryOverview?.totals?.favorites ?? 0"
              :types="directoryTypes"
              :project-id="projectId"
              @select="applyCardFilters"
              @create-topic="createTopicFromDirectory"
              @rename-topic="renameTopicFromDirectory"
              @archive-topic="archiveTopicFromDirectory"
              @move-topic="moveTopicFromDirectory"
            />
            <div class="world-library-browse__main">
              <header class="world-type-results__header">
                <button type="button" class="btn btn-sm btn-ghost" @click="clearCardFilters">← 返回资料库首页</button>
                <div><h2>{{ activeTopicLabel || activeTypeLabel }}</h2><p>{{ libraryTotalLabel }}</p></div>
              </header>
              <form class="world-card-filters" role="search" @submit.prevent="applyCardFilters()">
                <label class="world-card-filters__search">
                  <span>搜索资料</span>
                  <input v-model="cardSearch" type="search" maxlength="120" placeholder="名称、别名或内容" />
                </label>
                <label>
                  <span>资料形态</span>
                  <select :value="cardFilters.kind" @change="applyCardFilters({ kind: $event.target.value })">
                    <option value="all">全部资料</option>
                    <option value="entity">人物与具体设定</option>
                    <option value="page">资料页与工作稿</option>
                  </select>
                </label>
                <label>
                  <span>排序</span>
                  <select :value="cardFilters.sort" @change="applyCardFilters({ sort: $event.target.value, skip: 0 })">
                    <option value="updated">最近更新</option>
                    <option value="recent">最近使用</option>
                    <option value="title">名称</option>
                    <option value="created">创建时间</option>
                  </select>
                </label>
                <div class="world-card-filters__actions">
                  <button class="btn btn-sm btn-primary" type="submit">查找</button>
                  <button v-if="hasCardFilters" class="btn btn-sm" type="button" @click="clearCardFilters">清除</button>
                </div>
              </form>
              <div v-if="props.bible?.libraryError" class="empty-state" role="alert" data-author-action="retry">
                <p>资料列表暂时没有加载出来，正在显示本地缓存结果。</p><button class="btn btn-sm" type="button" @click="retryCards">重新加载</button>
              </div>
              <div v-else-if="props.bible?.entitiesLoadError" class="empty-state" role="alert" data-author-action="retry"><p>人物与设定暂时没有加载出来；资料页和工作稿仍可使用。</p><button class="btn btn-sm" type="button" @click="retryCards">重新加载</button></div>
              <WorldLibraryCards v-if="unifiedCards.length && cardFilters.layout === 'cards'" :cards="unifiedCards" :meta-for="cardMeta" @open="openWorldCard" @create-task="createTaskForWorldCard" @toggle-favorite="toggleFavoriteCard" @add-to-topic="openTopicPicker" />
              <WorldLibraryList v-else-if="unifiedCards.length" :cards="unifiedCards" :meta-for="cardMeta" @open="openWorldCard" @create-task="createTaskForWorldCard" @toggle-favorite="toggleFavoriteCard" @add-to-topic="openTopicPicker" />
              <div v-else-if="!props.bible?.entitiesLoadError && !props.bible?.libraryError" class="empty-state"><p>没有找到符合条件的资料。</p><button class="btn btn-sm btn-primary" type="button" @click="toolDialog = 'create'">新建资料</button></div>
              <WorldPager
                v-if="serverDriven"
                :total="libraryTotal"
                :skip="cardFilters.skip || 0"
                :limit="libraryPageSize"
                prev-action="world-library-prev-page"
                next-action="world-library-next-page"
                @change="changeLibraryPage"
              />
              <p v-else-if="entityCardsTruncated" class="world-bible-empty-hint">已显示前 50 个人物或设定；可继续使用搜索精确定位。</p>
            </div>
          </div>
        </template>
        <div v-if="pages.length" hidden aria-hidden="true"><button v-for="item in categoryItems(true)" :key="item.type" type="button" data-action="bible-gallery-open" :data-category="item.type" @click="openGalleryCategory(item.type)">{{ item.meta.title }}</button></div>
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
              <span>{{ projectionTask?.meta?.page_id === page.id ? `写作参考：${taskStatusLabel(projectionTask.status || 'pending')}` : '写作参考：打开后查看' }}</span>
            </div>
            <div class="world-bible-page-card__actions">
              <button class="btn btn-sm btn-primary" data-action="bible-open-page-card" :data-page-id="page.id" @click="openPageCard(page.id)">打开编辑</button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state"><p>这个分类下还没有世界书页面。</p></div>
      </div>
    </template>

    <!-- GRAPH mode: SVG is a visual aid; the keyboard-operable list remains primary. -->
    <template v-else-if="displayMode === 'graph'">
      <WorldBibleKnowledgeGraph
        :project-id="projectId"
        :active-page="activePage"
        :active-entity-id="bibleDeepLink?.entityId || null"
        :type-catalog="reviewTypeCatalog"
        @open-page="openPageCard"
        @open-entity="openGraphEntity"
      />
    </template>

    <!-- EDITOR mode (default) -->
    <template v-else>
      <!-- synopsis panel -->
      <details
        class="panel world-bible-synopsis-panel"
        data-section="bible-synopsis"
        @toggle="$event.target.open && ensureBibleSupport('synopsis')"
        :open="['queued', 'running'].includes(synopsis?.status)"
      >
        <summary class="world-bible-support-summary">
          <div>
            <strong>世界观简介</strong>
            <span class="badge">创作参考</span>
            <div class="world-bible-page-meta">AI 整理的参考资料；不会替代你已确认的核心设定。</div>
          </div>
          <span class="world-bible-support-summary__status">{{ supportState.synopsis === 'ready' ? taskStatusLabel(synopsis?.status || 'missing') : supportState.synopsis === 'loading' ? '正在读取…' : '打开后读取' }}</span>
        </summary>
        <div v-if="supportState.synopsis === 'ready'" class="world-bible-synopsis-panel__body">
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
          <div class="world-bible-page-meta">
            状态：{{ taskStatusLabel(synopsis?.status || 'missing') }}
            <template v-if="synopsis?.current_revision">
              · 第 {{ synopsis.current_revision.version_number }} 版
              <template v-if="synopsis.current_revision.coverage_json?.source_count != null">
                · 覆盖 {{ synopsis.current_revision.coverage_json.source_count }} 个来源
              </template>
            </template>
          </div>
          <pre v-if="synopsis?.current_revision?.rendered_text" class="generate-markdown-pre">{{ synopsis.current_revision.rendered_text }}</pre>
          <div v-else class="world-bible-empty-hint">尚未生成简介；需要时会根据当前已保存资料准备临时参考。</div>
          <details v-if="synopsisTask || (synopsis?.warnings || []).length" class="world-bible-diagnostics">
            <summary>诊断信息</summary>
            <div v-if="synopsisTask">任务编号：{{ synopsisTask.task_id || '未提供' }}</div>
            <div v-for="(w, i) in (synopsis?.warnings || [])" :key="i" class="world-bible-projection-status__hint">{{ w }}</div>
          </details>
        </div>
      </details>

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

        <!-- content column: editor and contextual tools never create a third workspace rail -->
        <div class="world-bible-content-column">
          <!-- editor panel (main) -->
          <main class="panel world-bible-editor-panel">
          <template v-if="editSource">
            <WorldPageReader
              v-if="pageViewMode === 'read'"
              :source="editSource"
              :sections="sortedSections"
              :asset-refs="editSource.linked_asset_refs_json || []"
              :ref-items="readerRefItems"
              :type-label="typeMeta(editSource.page_type).label"
              :status-label="statusLabel(activePage?.status)"
              :working="isWorkingDraft"
              @edit="switchPageView('edit')"
              @back="returnToLibrary()"
            />
            <template v-else>
            <div class="world-bible-source-notice" role="note">资料页，不是事实源。正式设定请编辑对应世界对象；AI 建议不会自动发布。</div>
            <div class="world-bible-panel__header">
              <div>
                <h2>{{ editSource.title }}</h2>
                <div class="world-bible-page-meta">
                  {{ typeMeta(editSource.page_type).label }} · {{ isWorkingDraft ? '工作稿' : statusLabel(activePage?.status) }}
                  <span id="bible-autosave-status" class="world-bible-autosave-status" data-autosave-status="idle" role="status"></span>
                </div>
              </div>
              <div class="world-bible-panel__actions">
                <button class="btn btn-sm btn-ghost" data-action="bible-back-to-read" @click="switchPageView('read')">完成编辑</button>
                <button v-if="activePage?.id" class="btn btn-sm btn-ghost" data-action="bible-create-author-task" @click="createTaskForWorldPage">添加到计划中的任务</button>
                <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-improve-with-ai" @click="openInGenerationCenter">用 AI 完善此页</button>
                <button v-if="activePage?.id" class="btn btn-sm btn-ghost" data-action="bible-impact-preview" @click="openImpactPreview('world_bible_page', activePage.id, activePage.title)">影响预演</button>
                <button class="btn btn-sm" :class="{ 'btn-primary': !canPublish }" data-action="bible-save-page" @click="savePage()">保存工作稿</button>
                <button v-if="canPublish" class="btn btn-sm btn-primary" data-action="bible-publish-page" @click="publishDraft">保存并发布</button>
                <details v-if="activePage?.id || isWorkingDraft" class="world-bible-editor-tools" data-section="bible-page-tools">
                  <summary class="btn btn-sm btn-ghost">页面工具</summary>
                  <div class="world-bible-editor-tools__actions">
                    <button v-if="isWorkingDraft" class="btn btn-sm" data-action="bible-discard-draft" @click="discardDraft">丢弃工作稿</button>
                    <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-page-history" @click="openPageHistory">版本历史</button>
                    <button v-if="activePage?.id && !isWorkingDraft && activePage?.status !== 'archived'" class="btn btn-sm" data-action="bible-archive-page" @click="archivePage">归档页面</button>
                    <button v-if="activePage?.id" class="btn btn-sm" data-action="bible-refresh-projection" @click="refreshProjection(false)">更新写作参考</button>
                  </div>
                </details>
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
                </div>
                <details class="world-bible-page-settings" data-section="bible-page-settings">
                  <summary>页面设置</summary>
                  <div class="generate-form-grid">
                    <label>页面顺序
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
                    <span v-if="editSource.template_key" class="badge">{{ activeTemplateLabel }} · 第 {{ editSource.template_version || 1 }} 版</span>
                  </div>
                </details>
                <label class="bible-ai-field">
                  页面概览
                  <textarea class="form-textarea world-bible-editor" id="bible-free-text" rows="8">{{ editSource.free_text || '' }}</textarea>
                </label>

                <!-- sections -->
                <section class="world-bible-sections">
                  <div class="world-bible-sections__header">
                    <div>
                      <strong>页面分区</strong>
                      <div class="world-bible-page-meta">按内容用途分段整理；创作辅助范围和维护信息默认收起。</div>
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
                          <span class="badge">第 {{ index + 1 }} 节</span>
                          <span class="world-bible-section-editor__actions">
                            <button class="btn btn-sm" data-action="bible-section-up" aria-label="上移分区" @click="moveSection(section.section_id, -1)">↑</button>
                            <button class="btn btn-sm" data-action="bible-section-down" aria-label="下移分区" @click="moveSection(section.section_id, 1)">↓</button>
                            <button class="btn btn-sm" data-action="bible-section-remove" @click="removeSection(section.section_id)">移除</button>
                          </span>
                        </div>
                        <div class="generate-form-grid">
                          <label>标题<input class="form-input" data-section-field="title" maxlength="120" :value="section.title" /></label>
                          <label>内容形式<select class="form-select" data-section-field="section_type">
                            <option value="markdown" :selected="section.section_type === 'markdown'">普通资料</option>
                            <option value="checklist" :selected="section.section_type === 'checklist'">检查清单</option>
                            <option value="asset_collection" :selected="section.section_type === 'asset_collection'">资产清单</option>
                          </select></label>
                        </div>
                        <label class="bible-ai-field">
                          分区正文
                          <textarea class="form-textarea" data-section-field="body_markdown" rows="6">{{ section.body_markdown || '' }}</textarea>
                        </label>
                        <details class="world-bible-section-advanced" data-section="bible-section-advanced">
                          <summary>创作辅助与高级设置</summary>
                          <div class="world-bible-section-advanced__body">
                            <p class="world-bible-page-meta">默认设置适合普通资料。“公开世界常识”只描述故事内的知识范围，不会把页面公开给其他用户；“自动整理”控制 AI 是否据此准备摘要等参考资料，你明确选择整页作参考时仍可能读取本段。</p>
                            <div class="generate-form-grid">
                              <label>默认可见范围<select class="form-select" data-section-field="sensitivity_hint">
                                <option value="author_safe" :selected="section.sensitivity_hint === 'author_safe'">作者规划可见</option>
                                <option value="author_only" :selected="section.sensitivity_hint === 'author_only'">仅作者全知任务</option>
                                <option value="public_baseline" :selected="section.sensitivity_hint === 'public_baseline'">公开世界常识</option>
                              </select></label>
                              <label>自动整理<select class="form-select" data-section-field="projection_policy">
                                <option value="eligible" :selected="section.projection_policy === 'eligible'">参与自动整理</option>
                                <option value="excluded" :selected="section.projection_policy === 'excluded'">不参与自动整理</option>
                              </select></label>
                            </div>
                            <details class="world-bible-diagnostics">
                              <summary>维护信息</summary>
                              <p class="world-bible-page-meta">分区标识：<code>{{ section.section_id }}</code></p>
                              <label class="bible-ai-field">
                                局部引用标识（通常无需修改；每行一个，必须来自本页“关联资产”）
                                <textarea class="form-textarea" data-section-field="linked_asset_ref_hashes" rows="2">{{ (section.linked_asset_ref_hashes || []).join('\n') }}</textarea>
                              </label>
                            </details>
                          </div>
                        </details>
                      </article>
                    </template>
                    <div v-else class="world-bible-empty-hint">暂无分区；旧页面可继续只使用概览。</div>
                  </div>
                </section>

                <!-- asset refs -->
                <label class="bible-ai-field">
                  关联资产
                  <span class="world-bible-page-meta">按名称选择已采用的对象、关系或已发布页面；这里只保存引用，不内联修改资产。</span>
                  <div id="bible-asset-ref-picker"></div>
                  <textarea id="bible-asset-refs" hidden>{{ formatAssetRefs(editSource.linked_asset_refs_json) }}</textarea>
                </label>
                <ul
                  v-if="(editSource.linked_asset_refs_json || []).length"
                  class="bible-asset-ref-relations"
                  data-section="bible-asset-ref-relations"
                  aria-label="引用语义分级"
                >
                  <li v-for="(ref, index) in editSource.linked_asset_refs_json" :key="index">
                    <span class="bible-asset-ref-relations__label">{{ assetRefDisplayName(ref) }}</span>
                    <select
                      class="form-input"
                      :data-field="'asset-ref-relation-' + index"
                      :value="ref.relation || 'informs'"
                      @change="setAssetRefRelation(index, $event.target.value)"
                    >
                      <option value="informs">参考</option>
                      <option value="requires">依赖</option>
                      <option value="derives">派生</option>
                      <option value="conflicts">冲突</option>
                    </select>
                  </li>
                </ul>

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
                      <div>任务编号：{{ projectionTask.task_id || projectionTask.id || '未提供' }}</div>
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
          </template>
          <div v-else class="empty-state">
            <p>创建一个世界书页面开始整理设定。</p>
          </div>
          </main>

          <!-- contextual AI reference rules, progressively disclosed inside content -->
          <details
            class="panel world-bible-inspector"
            data-section="bible-ai-reference-rules"
            :open="Boolean(currentProfile || activationTrace)"
            @toggle="$event.target.open && ensureBibleSupport('profiles')"
          >
          <summary class="world-bible-support-summary">
            <div>
              <strong>AI 参考规则</strong>
              <div class="world-bible-page-meta">资料发布与规则发布相互独立。</div>
            </div>
            <span class="world-bible-support-summary__status">{{ currentProfile ? activationProfileStatusLabel(currentProfile.status) : '按需设置' }}</span>
          </summary>
          <div class="world-bible-inspector__body">
            <div class="world-bible-inspector__header">
              <span class="world-bible-page-meta">仅在需要精确控制 AI 参考资料时设置。</span>
              <button class="btn btn-sm" data-action="bible-activation-new" @click="openActivationProfileEditor()">新建规则</button>
            </div>
            <label class="bible-ai-field">
              规则方案
              <select class="form-select" id="bible-activation-profile" v-model="activeActivationProfileId">
                <option value="">未选择</option>
                <option v-for="prof in activationProfiles" :key="prof.id" :value="prof.id">
                  {{ prof.name || '未命名规则方案' }} · 第 {{ prof.version_number }} 版 · {{ activationProfileStatusLabel(prof.status) }}
                </option>
              </select>
            </label>
            <template v-if="currentProfile">
              <div class="world-bible-profile-summary">
                <div><span class="badge">{{ activationProfileStatusLabel(currentProfile.status) }}</span> {{ currentProfile.name || '未命名规则方案' }}</div>
                <div>{{ currentProfile.rules_json?.length || 0 }} 条规则 · 用于 {{ currentProfile.applicable_actions_json?.length || 0 }} 种写作场景</div>
              </div>
              <div class="world-bible-inspector__actions">
                <button class="btn btn-sm" data-action="bible-activation-edit" @click="openActivationProfileEditor(currentProfile)">编辑工作稿</button>
                <button class="btn btn-sm btn-primary" data-action="bible-activation-publish" :disabled="currentProfile.status === 'archived'" @click="publishActivationProfile">发布规则</button>
              </div>
              <label class="bible-ai-field">
                要预览的写作任务
                <textarea class="form-textarea" id="bible-activation-task" rows="4" placeholder="例如：描写北境商队使用银币"></textarea>
              </label>
              <button class="btn btn-sm" data-action="bible-activation-dry-run" @click="dryRunActivationProfile">预览参考结果</button>
            </template>
            <div v-else class="world-bible-empty-hint">创建或选择规则方案后，可配置关键词、排除词和固定参考资料。</div>
            <!-- activation trace -->
            <div v-if="activationTrace" class="world-bible-activation-trace">
            <div class="world-bible-section-title">本次参考资料</div>
            <div v-for="(item, index) in (activationTrace.rule_evaluations || [])" :key="item.rule_id || index" class="world-bible-trace-rule" :class="{ 'is-matched': item.matched }">
              第 {{ index + 1 }} 条规则 · {{ item.matched ? '适用' : '不适用' }} · 找到 {{ item.candidate_count || 0 }} 份资料
              <div v-if="(item.blocked_clauses || []).length">{{ item.blocked_clauses.map(activationTraceReasonLabel).join('、') }}</div>
            </div>
            <div class="world-bible-trace-group">
              <strong>已加入 ({{ (activationTrace.items || []).length }})</strong>
              <template v-if="(activationTrace.items || []).length">
                <div v-for="item in (activationTrace.items || [])" :key="item.label || item.target?.target_id" class="world-bible-trace-item">
                  <strong>{{ item.label || '未命名资料' }}</strong>
                  <div>符合当前参考规则并已加入</div>
                  <span v-if="item.excluded_reason" class="badge">{{ activationTraceReasonLabel(item.excluded_reason) }}</span>
                </div>
              </template>
              <div v-else class="world-bible-empty-hint">无</div>
            </div>
            <div class="world-bible-trace-group">
              <strong>未加入 ({{ (activationTrace.excluded_items || []).length }})</strong>
              <template v-if="(activationTrace.excluded_items || []).length">
                <div v-for="item in (activationTrace.excluded_items || [])" :key="item.label || item.target?.target_id" class="world-bible-trace-item">
                  <strong>{{ item.label || '未命名资料' }}</strong>
                  <div>{{ activationTraceReasonLabel(item.excluded_reason) }}</div>
                </div>
              </template>
              <div v-else class="world-bible-empty-hint">无</div>
            </div>
            <div v-for="(w, i) in (activationTrace.warnings || [])" :key="i" class="world-bible-projection-status__hint">{{ activationTraceWarningLabel(w) }}</div>
            </div>
          </div>
          </details>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getRouter, getToast, getShowModalHtml, getCloseModal, getConfirmAction } from "../../../bridge/index.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"
import { authorTaskPanelQuery } from "../../writing/home/authorTaskSource.js"
import { editEntity, showEntityCreateForm, syncWorldListRegistry } from "../logic/worldEntityOps.js"
import { showAliasCreateForm, showAliasEditForm, syncRelationsAliasesRegistry } from "../logic/worldRelationsAliasesOps.js"
import { worldSession } from "../worldSession.js"
import WorldSidebarToolCard from "../components/WorldSidebarToolCard.vue"
import WorldToolDialog from "../components/WorldToolDialog.vue"
import WorldPager from "../components/WorldPager.vue"
import WorldEntityDetail from "../library/WorldEntityDetail.vue"
import WorldLibraryCards from "../library/WorldLibraryCards.vue"
import WorldLibraryDirectory from "../library/WorldLibraryDirectory.vue"
import WorldLibraryHome from "../library/WorldLibraryHome.vue"
import WorldLibraryList from "../library/WorldLibraryList.vue"
import WorldLibraryTypeGrid from "../library/WorldLibraryTypeGrid.vue"
import WorldTopicPickerDialog from "../library/WorldTopicPickerDialog.vue"
import WorldPageReader from "../library/WorldPageReader.vue"
import WorldBibleKnowledgeGraph from "../pages/WorldBibleKnowledgeGraph.vue"
import WorldbookImportPanel from "./WorldbookImportPanel.vue"
import WorldHealthPanel from "./WorldHealthPanel.vue"
import { useWorldBible } from "./useWorldBible.js"
import {
  LIBRARY_PAGE_SIZE,
  buildWorldCards,
  cardsFromLibraryItems,
  usesServerLibrary,
  worldCardQuery,
} from "./worldCards.js"

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "bible" },
  bible: { type: Object, default: null },
  bibleDeepLink: { type: Object, default: () => ({ draftId: "", pageId: "" }) },
  entityTypes: { type: Array, default: () => [] },
  reviewTypeCatalog: { type: Object, default: () => ({}) },
  worldCardFilters: { type: Object, default: () => ({ q: "", kind: "all", type: "", state: "", layout: "cards" }) },
  defaultDisplayMode: { type: String, default: null },
})

const rootEl = ref(null)
const toolDialog = ref("")
const worldbookImportOpen = ref(Boolean(props.bibleDeepLink?.openWorldbookImport))
const validationRun = ref(props.bible?.validationRun || null)
const validationPolicy = ref(props.bible?.validationPolicy || { active: false })
const entityProfileDirty = ref(false)
let libraryScrollRestoreTimer = null
watch(() => props.bibleDeepLink?.openWorldbookImport, (open) => {
  if (open) worldbookImportOpen.value = true
})

const legacyModeLabels = { gallery: "总览", editor: "编辑资料页", filter: "资料页筛选", graph: "关联图" }

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
  editorMutationPending,
  semanticInspectionPending,
  autosaveStatus,
  flushWorldDraftAutosave,
  pageViewMode,
  editorHasUnsavedChanges,
  pages,
  drafts,
  pageTemplates,
  activationProfiles,
  supportState,
  ensureBibleSupport,
  rememberActivationProfile,

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
  openImpactPreview,
  inspectCurrentPage,
  openCategoryManager,
  openPageTemplateManager,
  openPageHistory,
  archivePage,
  setExternalLeaveGuard,

  typeMeta,
  categoryItems,
  pagesForCategory,
  statusLabel,
  taskStatusLabel,
  pageExcerpt,
  categoryOptions,
  formatAssetRefs,
  parseAssetRefs,
  ownsProject,
  captureModalOwner,
  ownsModalOwner,
  esc,
} = useWorldBible(props)

setExternalLeaveGuard(
  () => !entityProfileDirty.value || confirm("人物档案有未保存修改，确定放弃并离开吗？"),
  () => entityProfileDirty.value,
)

const cardFilters = computed(() => ({
  q: "",
  kind: "all",
  type: "",
  state: "",
  layout: "list",
  sort: "updated",
  topicId: "",
  favorite: false,
  unclassified: false,
  skip: 0,
  ...(props.worldCardFilters || {}),
}))
const cardSearch = ref(cardFilters.value.q || "")
watch(() => cardFilters.value.q, (value) => { cardSearch.value = value || "" })
const bibleEntityTotal = computed(() => Number(props.bible?.entityTotal || 0))
const completedEntityRows = ref({})
let completedEntityGeneration = 0
const visibleEntities = computed(() => (props.bible?.entities || []).map(item => completedEntityRows.value[item.id || item.entity_id] || item))
async function refreshCompletedEntity(entityId) {
  const projectId = props.projectId
  const generation = ++completedEntityGeneration
  try {
    const entity = await getApi().world.getEntity(entityId, projectId, { cache: "no-store" })
    if (!ownsProject(projectId) || generation !== completedEntityGeneration) return
    completedEntityRows.value = { ...completedEntityRows.value, [entityId]: entity }
  } catch (error) {
    if (ownsProject(projectId) && generation === completedEntityGeneration) getToast()(error.message || "补全结果已保留，当前资料刷新失败，可稍后重新打开。", "warning")
  }
}
watch(() => props.bible?.entities, () => { completedEntityRows.value = {} })
const libraryOverview = computed(() => props.bible?.libraryOverview || null)
const libraryTopics = computed(() => libraryOverview.value?.topics || [])
// 服务端列表可用时结果视图由其驱动；否则回退到既有客户端合并卡片。
const serverDriven = computed(() => usesServerLibrary(cardFilters.value)
  && Array.isArray(props.bible?.libraryItems)
  && !props.bible?.libraryError)
const serverLibraryCards = computed(() => cardsFromLibraryItems(props.bible?.libraryItems || []))
const libraryTotal = computed(() => Number(props.bible?.libraryTotal || 0))
const libraryPageSize = LIBRARY_PAGE_SIZE
const unifiedCards = computed(() => {
  if (serverDriven.value) return serverLibraryCards.value
  return buildWorldCards({
    pages: pages.value,
    drafts: drafts.value,
    entities: visibleEntities.value,
    filters: cardFilters.value,
  })
})
const hasCardFilters = computed(() => Boolean(
  cardFilters.value.q
  || cardFilters.value.type
  || cardFilters.value.state
  || cardFilters.value.topicId
  || cardFilters.value.favorite
  || cardFilters.value.unclassified
  || cardFilters.value.kind !== "all",
))
const workingCardCount = computed(() => Number(libraryOverview.value?.totals?.working ?? drafts.value.length))
const selectedEntity = computed(() => {
  const id = props.bibleDeepLink?.entityId
  if (!id) return null
  return visibleEntities.value.find((item) => (item.id || item.entity_id) === id) || null
})
watch(() => selectedEntity.value?.id || selectedEntity.value?.entity_id || "", (id) => {
  if (!id) return
  nextTick(() => {
    const content = document.getElementById("workspace-content")
    if (content) content.scrollTop = 0
  })
}, { immediate: true })
watch(() => [visibleEntities.value, props.entityTypes, props.reviewTypeCatalog], ([entities, entityTypes, reviewTypeCatalog]) => {
  const items = Array.isArray(entities) ? entities : []
  syncWorldListRegistry({ entities: items, entityTypes })
  syncRelationsAliasesRegistry({
    reviewTypeCatalog,
    aliases: items.flatMap((entity) => (entity.content_json?.aliases || []).map((item) => ({
      ...(typeof item === "string" ? { alias: item } : item),
      entity_id: entity.id || entity.entity_id,
      entity_name: entity.name,
    }))),
  })
}, { immediate: true, deep: true })
const entityCardsTruncated = computed(() => cardFilters.value.kind !== "page"
  && bibleEntityTotal.value > (props.bible?.entities || []).length)
const cardTypeOptions = computed(() => {
  const labels = new Map()
  for (const category of categoryItems(false)) if (category.type !== "custom") labels.set(category.type, category.meta.title)
  for (const option of props.entityTypes || []) if (option.value !== "custom") labels.set(option.value, option.label)
  for (const card of unifiedCards.value) if (card.typeKey !== "custom" && !labels.has(card.typeKey)) labels.set(card.typeKey, card.typeKey)
  return Array.from(labels, ([value, label]) => ({ value, label }))
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"))
})
const COMMON_TYPE_KEYS = ["character", "location", "faction", "item", "event", "rule"]
const COMMON_TYPE_META = {
  character: ["人物", "人"], location: ["地点", "地"], faction: ["势力／派系", "势"],
  item: ["物品", "物"], event: ["事件", "事"], rule: ["规则", "规"],
}
const entityTypeCounts = computed(() => new Map((props.bible?.entityFacets || []).map((item) => [item.entity_type, Number(item.count || 0)])))
const pageTypeCounts = computed(() => {
  const counts = new Map()
  for (const item of [...pages.value, ...drafts.value]) {
    const key = item.page_type || "custom"
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return counts
})
const countForType = (value) => Number(libraryOverview.value?.type_facets?.find(item => item.type === value)?.count ?? (Number(entityTypeCounts.value.get(value) || 0) + Number(pageTypeCounts.value.get(value) || 0)))
const commonTypeCards = computed(() => COMMON_TYPE_KEYS.map((value) => {
  const option = cardTypeOptions.value.find((item) => item.value === value)
  return { value, label: option?.label || COMMON_TYPE_META[value][0], symbol: COMMON_TYPE_META[value][1], count: countForType(value) }
}))
const extraTypeOptions = computed(() => cardTypeOptions.value.filter((item) => !COMMON_TYPE_KEYS.includes(item.value)))
const showTypeHome = computed(() => displayMode.value === "gallery" && !selectedEntity.value && !galleryCategory.value && !hasCardFilters.value)
const activeTypeLabel = computed(() => {
  if (cardFilters.value.favorite) return "收藏的资料"
  if (cardFilters.value.unclassified) return "未归类资料"
  if (cardFilters.value.state === "working") return "工作稿"
  if (cardFilters.value.type) return cardTypeOptions.value.find((item) => item.value === cardFilters.value.type)?.label || cardFilters.value.type
  if (cardFilters.value.q) return `“${cardFilters.value.q}”的搜索结果`
  return "全部资料"
})
const activeTopicLabel = computed(() => {
  if (!cardFilters.value.topicId) return ""
  const find = (nodes) => {
    for (const node of nodes || []) {
      if (node.id === cardFilters.value.topicId) return node
      const child = find(node.children || [])
      if (child) return child
    }
    return null
  }
  const topic = find(libraryTopics.value)
  return topic ? `主题：${topic.name}` : ""
})
const libraryTotalLabel = computed(() => (
  serverDriven.value
    ? `${libraryTotal.value} 项资料${libraryTotal.value > libraryPageSize ? `，第 ${Math.floor((cardFilters.value.skip || 0) / libraryPageSize) + 1} / ${Math.ceil(libraryTotal.value / libraryPageSize)} 页` : ""}`
    : `${typeResultCount.value} 项资料`
))
const directoryTypes = computed(() => cardTypeOptions.value.map((item) => ({
  ...item,
  count: countForType(item.value),
})))
const typeResultCount = computed(() => {
  if (serverDriven.value) return libraryTotal.value
  if (cardFilters.value.state === "working") return workingCardCount.value
  if (cardFilters.value.type) return countForType(cardFilters.value.type)
  return unifiedCards.value.length
})
const sidebarActions = computed(() => {
  if (selectedEntity.value) return [
    { key: "edit", label: "编辑资料", primary: true },
    { key: "all", label: "返回资料库" },
    { key: "task", label: "添加到计划中的任务" },
    { key: "more", label: "更多工具" },
  ]
  if (!showTypeHome.value) return [
    { key: "create", dataAction: "bible-new-resource", label: cardFilters.value.type ? `新建${activeTypeLabel.value}` : "新建资料", primary: true },
    { key: "all", label: "返回全部类型" },
    { key: cardFilters.value.layout === "cards" ? "list" : "cards", label: cardFilters.value.layout === "cards" ? "切换到列表" : "切换到卡片" },
    { key: "ai", label: "AI 工具" },
    { key: "more", label: "更多工具" },
  ]
  return [
    { key: "create", dataAction: "bible-new-resource", label: "＋ 新建资料", primary: true },
    { key: "health", label: "世界健康" },
    { key: "questions", label: "页面中的未决项", badge: authorOpenQuestions.value.length },
    { key: "ai", label: "AI 工具" },
    { key: "more", label: "更多工具" },
  ]
})
const toolDialogTitle = computed(() => ({ health: "世界健康", questions: "页面中的未决项", types: "更多类型", create: "新建资料", more: "更多工具" })[toolDialog.value] || "资料工具")

function handleSidebarAction(key) {
  if (["create", "health", "questions", "more"].includes(key)) { toolDialog.value = key; return }
  if (key === "all") { clearCardFilters(); return }
  if (key === "cards" || key === "list") { setLibraryLayout(key); return }
  if (key === "edit") { editSelectedEntity(); return }
  if (key === "task" && selectedEntity.value) { createTaskForWorldEntity(selectedEntity.value); return }
  if (key === "ai") {
    const query = worldCardQuery(cardFilters.value)
    query.set("owner_ai", "1")
    query.set("owner_ai_mode", "world")
    getRouter()?.navigate("world", "bible", true, query)
  }
}

function selectTypeCard(value) {
  cardSearch.value = ""
  if (value === "working") applyCardFilters({ q: "", state: "working", type: "", kind: "page" })
  else applyCardFilters({ q: "", state: "", type: value, kind: "all" })
}

function selectMoreType(value) {
  toolDialog.value = ""
  nextTick(() => selectTypeCard(value))
}

function runDialogAction(action) {
  toolDialog.value = ""
  nextTick(action)
}

function createEntityFromDialog(selectedType = "") {
  toolDialog.value = ""
  nextTick(() => showEntityCreateForm({ entity_type: selectedType }, {
    onCreated: (entity) => {
      const query = worldCardQuery({ ...cardFilters.value, type: entity.entity_type || selectedType })
      query.set("entity_id", entity.id || entity.entity_id)
      getRouter()?.navigate("world", "bible", true, query)
      return true
    },
  }))
}

function createPageFromDialog() {
  toolDialog.value = ""
  nextTick(createPage)
}

function openQuestionFromDialog(entry) {
  toolDialog.value = ""
  nextTick(() => openAuthorOpenQuestion(entry))
}
function openGraphEntity(entityId) {
  getRouter()?.navigate("world", "objects", true, new URLSearchParams({ entity_id: entityId }))
}

function openObjectTools() {
  getRouter()?.navigate("world", "bible", true, new URLSearchParams({ open: "object-tools" }))
}

function cardMeta(card) {
  if (card.kind === "page") {
    const meta = typeMeta(card.typeKey)
    return { color: meta.color, symbol: meta.symbol, label: meta.title }
  }
  const option = props.entityTypes.find((item) => item.value === card.typeKey)
  const meta = typeMeta(card.typeKey)
  const label = option?.label || (card.typeKey === "custom" ? "未分类资料" : card.typeKey) || "人物或设定"
  return { color: meta.color, symbol: String(label).slice(0, 2), label }
}

function applyCardFilters(overrides = {}) {
  const next = { ...cardFilters.value, q: cardSearch.value, ...overrides }
  // 筛选条件变化时回到第一页；仅翻页时保留 skip。
  const filtersChanged = worldCardQuery({ ...next, skip: 0 }).toString()
    !== worldCardQuery({ ...cardFilters.value, skip: 0 }).toString()
  if (filtersChanged && !("skip" in overrides)) next.skip = 0
  getRouter()?.navigate("world", "bible", true, worldCardQuery(next))
}

function changeLibraryPage(delta) {
  const current = cardFilters.value.skip || 0
  const nextSkip = Math.max(0, current + delta * libraryPageSize)
  if (nextSkip === current) return
  rememberLibraryScroll()
  applyCardFilters({ skip: nextSkip })
}

const topicPickerCard = ref(null)
const topicPickerMemberIds = ref([])

function cardTargetRef(card) {
  if (card.targetKind && card.targetId) return { kind: card.targetKind, id: card.targetId }
  if (card.kind === "entity") return { kind: "entity", id: card.id }
  if (card.draftId && !card.id) return { kind: "draft", id: card.draftId }
  if (card.id) return { kind: "page", id: card.id }
  return null
}

function recordOpenRecent(card) {
  const target = cardTargetRef(card)
  const api = getApi()
  if (!target || !api?.world?.recordWorldLibraryRecent || !props.projectId) return
  api.world.recordWorldLibraryRecent(props.projectId, target.kind, String(target.id)).catch(() => {})
}

async function toggleFavoriteCard(card) {
  const target = cardTargetRef(card)
  const api = getApi()
  if (!target || !api?.world?.addWorldLibraryFavorite || !props.projectId) return
  try {
    if (card.isFavorite) await api.world.removeWorldLibraryFavorite(props.projectId, target.kind, String(target.id))
    else await api.world.addWorldLibraryFavorite(props.projectId, target.kind, String(target.id))
    getRouter()?.refresh?.()
  } catch (error) {
    getToast()(error?.message || "收藏状态没有保存，请稍后重试", "warning")
  }
}

async function openTopicPicker(card) {
  const target = cardTargetRef(card)
  const api = getApi()
  if (!target || !api?.world?.getWorldLibraryMemberships || !props.projectId) return
  topicPickerCard.value = card
  topicPickerMemberIds.value = []
  try {
    const result = await api.world.getWorldLibraryMemberships(props.projectId, target.kind, String(target.id))
    if (topicPickerCard.value === card) topicPickerMemberIds.value = result?.topic_ids || []
  } catch {
    // 成员关系读取失败时仍允许选择主题，保存时会重新校验。
  }
}

async function toggleTopicMembership(topic) {
  const card = topicPickerCard.value
  const target = card ? cardTargetRef(card) : null
  const api = getApi()
  if (!target || !api?.world?.addWorldLibraryTopicMember || !props.projectId) return
  const member = topicPickerMemberIds.value.includes(topic.id)
  try {
    if (member) await api.world.removeWorldLibraryTopicMember(topic.id, props.projectId, target.kind, String(target.id))
    else await api.world.addWorldLibraryTopicMember(topic.id, props.projectId, target.kind, String(target.id))
    topicPickerMemberIds.value = member
      ? topicPickerMemberIds.value.filter((id) => id !== topic.id)
      : [...topicPickerMemberIds.value, topic.id]
  } catch (error) {
    getToast()(error?.message || "主题成员没有保存，请稍后重试", "warning")
  }
}

function selectHomeTopic(topicId) {
  applyCardFilters({ topicId, skip: 0, q: "", type: "", state: "", kind: "all", favorite: false, unclassified: false })
}

async function createTopicFromDirectory({ name, parentId }) {
  const api = getApi()
  if (!api?.world?.createWorldLibraryTopic || !props.projectId) return
  try {
    await api.world.createWorldLibraryTopic(props.projectId, { name, parent_id: parentId || null })
    getToast()("主题已创建", "success")
    getRouter()?.refresh?.()
  } catch (error) {
    getToast()(error?.message || "主题创建失败，请稍后重试", "warning")
  }
}

async function renameTopicFromDirectory({ topicId, name }) {
  const api = getApi()
  if (!api?.world?.updateWorldLibraryTopic || !props.projectId) return
  try {
    await api.world.updateWorldLibraryTopic(topicId, { novel_id: props.projectId, name }, props.projectId)
    getToast()("主题已改名", "success")
    getRouter()?.refresh?.()
  } catch (error) {
    getToast()(error?.message || "主题改名失败，请稍后重试", "warning")
  }
}

async function archiveTopicFromDirectory({ topicId, archived }) {
  const api = getApi()
  if (!api?.world?.archiveWorldLibraryTopic || !props.projectId) return
  const run = async () => {
    try {
      await api.world.archiveWorldLibraryTopic(topicId, props.projectId, archived)
      getToast()(archived ? "主题已归档，资料保持不变" : "主题已恢复", "success")
      if (cardFilters.value.topicId === topicId && archived) applyCardFilters({ topicId: "" })
      else getRouter()?.refresh?.()
    } catch (error) {
      getToast()(error?.message || "主题状态没有保存，请稍后重试", "warning")
    }
  }
  const confirm = getConfirmAction()
  if (confirm && archived) {
    confirm("归档这个主题吗？主题会从目录中隐藏，其中的资料和子主题保持不变。", run)
    return
  }
  await run()
}

async function moveTopicFromDirectory({ topicId, direction }) {
  const api = getApi()
  if (!api?.world?.reorderWorldLibraryTopics || !props.projectId) return
  const collect = (nodes) => {
    const rows = []
    for (const node of nodes || []) {
      rows.push(node, ...collect(node.children || []))
    }
    return rows
  }
  const all = collect(libraryTopics.value)
  const topic = all.find((node) => node.id === topicId)
  if (!topic) return
  const parentId = topic.parent_id || null
  const siblings = all.filter((node) => (node.parent_id || null) === parentId)
  const index = siblings.findIndex((node) => node.id === topicId)
  const swapWith = siblings[index + direction]
  if (index < 0 || !swapWith) return
  const ordered = siblings.map((node, position) => (position === index ? swapWith : position === index + direction ? topic : node))
  try {
    await api.world.reorderWorldLibraryTopics(props.projectId, parentId, ordered.map((node) => node.id))
    getRouter()?.refresh?.()
  } catch (error) {
    getToast()(error?.message || "主题顺序没有保存，请稍后重试", "warning")
  }
}


function setLibraryLayout(layout) {
  if (!["cards", "list"].includes(layout)) return
  applyCardFilters({ layout })
}

function clearCardFilters() {
  cardSearch.value = ""
  getRouter()?.navigate("world", "bible", true, new URLSearchParams())
}

function retryCards() {
  getRouter()?.refresh?.()
}

function returnToLibrary() {
  setDisplayMode("gallery")
  if (displayMode.value !== "gallery") return
  getRouter()?.navigate("world", "bible", true, worldCardQuery(cardFilters.value))
}

function libraryScrollKey() {
  return `${props.projectId || "none"}:${worldCardQuery(cardFilters.value).toString()}`
}

function rememberLibraryScroll() {
  const content = document.getElementById("workspace-content")
  if (content) worldSession.bible.libraryScrollPositions[libraryScrollKey()] = content.scrollTop
}

function restoreLibraryScroll() {
  if (displayMode.value !== "gallery" || selectedEntity.value) return
  const top = Number(worldSession.bible.libraryScrollPositions[libraryScrollKey()] || 0)
  nextTick(() => {
    clearTimeout(libraryScrollRestoreTimer)
    libraryScrollRestoreTimer = setTimeout(() => {
      const content = document.getElementById("workspace-content")
      if (content) content.scrollTop = top
    }, 0)
  })
}

function openWorldCard(card) {
  if (displayMode.value === "gallery" && !selectedEntity.value) rememberLibraryScroll()
  recordOpenRecent(card)
  const query = worldCardQuery(cardFilters.value)
  if (card.kind === "entity") {
    query.set("entity_id", card.id)
    getRouter()?.navigate("world", "bible", true, query)
    return
  }
  if (card.draftId) query.set("draft_id", card.draftId)
  else if (card.id) query.set("page_id", card.id)
  else return
  getRouter()?.navigate("world", "bible", true, query)
}

function createTaskForWorldCard(card) {
  if (card.kind === "page" && !card.id) {
    getToast()("请先发布这份工作稿，再把它作为任务来源", "warning")
    return
  }
  const kind = card.kind === "entity" ? "world_entity" : "world_page"
  const title = card.kind === "page"
    ? pages.value.find((page) => page.id === card.id)?.title || card.title
    : card.title
  getRouter()?.navigate("writing", null, true, authorTaskPanelQuery({ kind, id: card.id, title }))
}

function createTaskForWorldEntity(entity) {
  createTaskForWorldCard({ kind: "entity", id: entity.id || entity.entity_id, title: entity.name })
}

function createTaskForWorldPage() {
  if (!activePage.value?.id) return
  createTaskForWorldCard({ kind: "page", id: activePage.value.id, title: activePage.value.title })
}

function editSelectedEntity() {
  if (selectedEntity.value) editEntity(selectedEntity.value.id || selectedEntity.value.entity_id)
}

function createAliasForSelectedEntity() {
  if (!selectedEntity.value) return
  showAliasCreateForm(props.reviewTypeCatalog, { entityId: selectedEntity.value.id || selectedEntity.value.entity_id })
}

function editAliasForSelectedEntity(alias) {
  if (!selectedEntity.value) return
  showAliasEditForm(selectedEntity.value.id || selectedEntity.value.entity_id, alias)
}

function openValidationSource(target) {
  if (target?.kind === "draft") openDraft(target.id)
  else if (target?.kind === "page") openPageCard(target.id)
  else if (target?.kind === "entity") openWorldCard({ kind: "entity", id: target.id })
  else if (target?.kind === "adoption") getRouter()?.navigate("world", "bible", true, new URLSearchParams({ adoption_package_id: target.id }))
}

// ---- computed locals ----
const AUTOSAVE_STATUS_LABELS = {
  scheduled: "修改将在停笔后自动保存到工作稿",
  saving: "正在自动保存工作稿…",
  conflict: "工作稿已在别处更新，已暂停自动保存；请对照最新内容后手动保存",
  error: "自动保存暂时失败，输入已在本机备份；恢复后自动重试",
}
// ---- 阅读态：切换与引用名称解析 ----
async function switchPageView(mode) {
  if (mode === "read") {
    if (pageViewMode.value === "edit" && editorHasUnsavedChanges && editorHasUnsavedChanges()) {
      const flushed = await flushWorldDraftAutosave()
      if (!flushed) return // 冲突或失败：留在编辑态处理
    }
    pageViewMode.value = "read"
    void resolveReaderRefs()
  } else {
    pageViewMode.value = "edit"
    nextTick(() => document.getElementById("bible-title")?.focus?.())
  }
}

const readerRefItems = ref([])
let readerRefGeneration = 0
async function resolveReaderRefs() {
  const source = editSource.value
  if (!source) {
    readerRefItems.value = []
    return
  }
  const refs = (source.linked_asset_refs_json || []).slice(0, 50)
  if (!refs.length) {
    readerRefItems.value = []
    return
  }
  const generation = ++readerRefGeneration
  const items = refs.map((rawRef) => {
    const kind = canonicalAssetRefType(assetRefType(rawRef))
    const id = assetRefId(rawRef)
    return { kind, id, label: id || "引用", unavailable: false }
  })
  readerRefItems.value = items
  for (const [index, rawRef] of refs.entries()) {
    const kind = canonicalAssetRefType(assetRefType(rawRef))
    const id = assetRefId(rawRef)
    if (!id || generation !== readerRefGeneration) continue
    try {
      if (kind === "world_bible_page") {
        const page = pages.value.find((item) => item.id === id)
          || await Promise.resolve(getApi().world.getBiblePage(id, props.projectId)).catch(() => null)
        if (generation !== readerRefGeneration) return
        if (page) items[index] = { kind, id, label: page.title || id, unavailable: false }
        else items[index] = { kind, id, label: id, unavailable: true }
      } else if (kind === "core_entity") {
        const known = visibleEntities.value.find((item) => (item.id || item.entity_id) === id)
        const entity = known || await Promise.resolve(getApi().world.getEntity(id, props.projectId)).catch(() => null)
        if (generation !== readerRefGeneration) return
        if (entity) items[index] = { kind, id, label: entity.name || id, unavailable: false }
        else items[index] = { kind, id, label: id, unavailable: true }
      }
    } catch {
      // 单条解析失败保留 ID 兜底。
    }
  }
  if (generation === readerRefGeneration) readerRefItems.value = [...items]
}
watch(() => pageViewMode.value === "read" ? editSource.value?.id : null, () => {
  if (pageViewMode.value === "read") void resolveReaderRefs()
}, { immediate: true })

// 编辑器输入是 DOM 驱动的非受控表单：状态必须命令式写入，
// 任何输入期间的响应式重渲染都会把输入框重置回绑定值。
watch(autosaveStatus, (status) => {
  const el = document.getElementById("bible-autosave-status")
  if (!el) return
  el.textContent = AUTOSAVE_STATUS_LABELS[status] || ""
  el.dataset.autosaveStatus = status || "idle"
})
const freeDrafts = computed(() => drafts.value.filter((d) => !d.page_id))
const canPublish = computed(() => activePage.value?.status !== "archived")
const validationRequiresFullScope = computed(() => Boolean(props.bibleDeepLink?.adoptionPackageId)
  || ["rule", "schema", "terminology", "world_core"].includes(activeDraft.value?.page_type)
  || Boolean(activeDraft.value?.page_meta_json?.validation_policy)
  || Boolean(activeDraft.value?.linked_asset_refs_json?.length))
const healthGapRoot = computed(() => {
  if (props.bibleDeepLink?.adoptionPackageId) return null
  if (selectedEntity.value?.id) return { type: "core_entity", id: selectedEntity.value.id, label: selectedEntity.value.name }
  if (activeDraft.value?.id) {
    return {
      type: "world_bible_page_draft",
      id: activeDraft.value.id,
      page_id: activeDraft.value.page_id,
      label: activeDraft.value.title || "当前工作稿",
      selected_world_bible_draft_ids: [activeDraft.value.id],
    }
  }
  if (activePage.value?.id) {
    return { type: "world_bible_page", id: activePage.value.id, label: activePage.value.title || "当前页面" }
  }
  return null
})
function openHealthFromLibrary() {
  toolDialog.value = "health"
  getToast()("先打开一份工作稿或页面，再从它发起定向查漏", "warning")
}
const authorOpenQuestions = computed(() => {
  const sources = [
    ...pages.value
      .filter((page) => page.status !== "archived")
      .map((page) => {
        const draft = draftForPage(page.id)
        return { source: draft || page, pageId: page.id, draftId: draft?.id || null }
      }),
    ...freeDrafts.value.map((draft) => ({ source: draft, pageId: null, draftId: draft.id })),
  ]
  return sources.flatMap(({ source, pageId, draftId }) => {
    const section = source.sections_json?.find((item) => item.section_id === "author-open-questions")
    if (!section) return []
    const sourceKey = `${draftId ? "draft" : "page"}:${source.id}`
    return String(section.body_markdown || "").split(/\r?\n/).flatMap((line, index) => {
      const match = line.match(/^\s*[-*]\s+\[\s\]\s+(.+?)\s*$/)
      return match ? [{
        key: `${sourceKey}:${index}`,
        sourceKey,
        question: match[1],
        sourceTitle: source.title || "未命名页面",
        pageId,
        draftId,
      }] : []
    })
  })
})
const currentProfile = computed(() => activationProfiles.value.find((p) => p.id === activeActivationProfileId.value) || null)
const activeTemplateLabel = computed(() => pageTemplates.value.find((template) => template.template_key === editSource.value?.template_key)?.name || "当前模板")
function activationProfileStatusLabel(status) {
  return ({ draft: "工作稿", published: "已发布", archived: "已归档" })[status] || "状态未知"
}
function activationTraceReasonLabel(reason) {
  return ({
    rule_disabled: "规则当前未启用",
    action: "不适用于当前操作",
    mode: "不适用于当前可见范围",
    scope_mismatch: "当前任务不适用",
    positive_not_matched: "关键词未命中",
    negative_matched: "命中了排除词",
    reader_cutoff: "超出读者可见范围",
    character_knowledge_hidden: "超出人物当前认知",
    target_missing: "资料已不可用",
    target_archived: "资料已归档",
    rule_top_k: "超出当前条目数量上限",
    rule_token_cap: "超出当前参考篇幅",
    global_budget_evicted: "超出本次总参考篇幅",
    global_budget_truncated: "因本次总参考篇幅而缩短",
  })[reason] || "未满足当前参考规则"
}
function activationTraceWarningLabel(warning) {
  return ({ projection_stale: "部分写作参考可能不是最新版本，请先更新页面的写作参考。" })[warning]
    || "部分参考资料需要检查。"
}
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

async function openAuthorOpenQuestion(entry) {
  if (entry.draftId && activeDraft.value?.id !== entry.draftId) openDraft(entry.draftId)
  if (!entry.draftId && (activePage.value?.id !== entry.pageId || activeDraft.value)) openPageCard(entry.pageId)
  await nextTick()
  const opened = entry.draftId
    ? activeDraft.value?.id === entry.draftId
    : activePage.value?.id === entry.pageId && !activeDraft.value
  if (opened) {
    rootEl.value
      ?.querySelector('[data-section-id="author-open-questions"]')
      ?.scrollIntoView?.({ block: "center" })
  }
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
let activationTargetPicker = null
let assetRefPicker = null
let activationMutationGeneration = 0

function captureActivationOwner(modalNode = null) {
  return {
    generation: ++activationMutationGeneration,
    novelId: props.projectId,
    selectionId: activeActivationProfileId.value,
    picker: activationTargetPicker,
    modal: captureModalOwner(modalNode),
  }
}

function ownsActivationOwner(owner) {
  return owner.generation === activationMutationGeneration
    && ownsProject(owner.novelId)
    && activeActivationProfileId.value === owner.selectionId
    && ownsModalOwner(owner.modal)
}

function destroyActivationTargetPicker(picker = activationTargetPicker) {
  picker?.destroy?.()
  if (activationTargetPicker === picker) activationTargetPicker = null
}

function openActivationProfileEditor(profile = null) {
  activationMutationGeneration += 1
  const rule = profile?.rules_json?.[0] || null
  const profileKey = profile?.profile_key || `writing.world_bible.${Date.now().toString(36)}`
  const action = profile?.applicable_actions_json?.[0] || "writing.generate"
  const tokenCap = rule?.rank?.token_cap ?? 1200
  const referenceLengthOptions = [
    [600, "精简"], [1200, "标准"], [2400, "充分"], [4800, "较长"],
  ]
  if (!referenceLengthOptions.some(([value]) => value === tokenCap)) {
    referenceLengthOptions.unshift([tokenCap, "沿用当前篇幅"])
  }
  const target = rule?.select?.target_refs?.[0]
    || (activePage.value?.id ? { target_type: "world_bible_page", target_id: activePage.value.id } : {})
  const body = `
    <p class="world-bible-empty-hint">简单模式支持关键词匹配、固定参考资料、优先程度和参考篇幅；更复杂的规则需在高级工具中处理。</p>
    <div class="form-group"><label>名称</label><input class="form-input" id="bible-profile-name" value="${esc(profile?.name || "场景写作世界资料")}" /></div>
    <p class="form-help">这套规则用于世界共创、页面建议和相关 AI 操作。</p>
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
      <label>最多选取条数<input class="form-input" id="bible-rule-top-k" type="number" min="1" max="256" value="${esc(rule?.rank?.top_k ?? 12)}" /></label>
      <label>单次参考篇幅<select class="form-select" id="bible-rule-token-cap">${referenceLengthOptions.map(([value, label]) => `<option value="${value}" ${value === tokenCap ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    </div>
  `
  const showModalHtml = getShowModalHtml()
  showModalHtml(profile ? "编辑 AI 参考规则工作稿" : "新建 AI 参考规则", body, [{
    text: "保存工作稿",
    class: "btn-primary",
    handler: () => saveActivationProfileEditor(profile, { profileKey, action }),
  }], { size: "large" })
  mountActivationTargetPicker(target)
}

function mountActivationTargetPicker(target) {
  const root = document.getElementById("bible-rule-target-picker")
  if (!root) return
  destroyActivationTargetPicker()
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
  activationTargetPicker = picker
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
        const result = await api.world.listWorldLibrary({ novel_id: props.projectId, kind: 'page', state: 'active', q: query || undefined, limit: 20 })
        return (result.items || []).map(item => ({ kind: 'world_bible_page', id: item.id, label: item.title || '未命名世界书页面', description: typeMeta(item.item_type).label, status: '已发布' }))
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

async function saveActivationProfileEditor(profile, { profileKey, action }) {
  const splitTerms = (id) => String(document.getElementById(id)?.value || "")
    .split(/[,，\n]+/).map((v) => v.trim()).filter(Boolean)
  const positive = splitTerms("bible-rule-positive")
  const rawTarget = document.getElementById("bible-rule-target")?.value?.trim() || ""
  const separator = rawTarget.indexOf(":")
  if (!positive.length || separator < 1) {
    getToast()("请填写至少一个正向词并选择有效资料目标", "warning")
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
  const owner = captureActivationOwner(document.getElementById("bible-profile-name"))
  try {
    const name = document.getElementById("bible-profile-name")?.value?.trim() || "AI 参考规则"
    const api = getApi()
    const saved = profile
      ? await api.context.updateActivationProfile(profile.id, { base_version_number: profile.version_number, name, applicable_actions_json: [action], rules_json: [rule] }, owner.novelId)
      : await api.context.createActivationProfile({ novel_id: owner.novelId, profile_key: profileKey, name, applicable_actions_json: [action], rules_json: [rule] })
    destroyActivationTargetPicker(owner.picker)
    if (!ownsActivationOwner(owner)) return true
    getCloseModal()()
    rememberActivationProfile(saved)
    activationTrace.value = null
    getToast()("规则工作稿已保存；发布前不会影响真实调用", "success")
  } catch (err) {
    if (ownsActivationOwner(owner)) {
      getToast()(err.message || "保存规则失败", "error")
      return false
    }
    return true
  }
}

async function publishActivationProfile() {
  const profile = currentProfile.value
  if (!profile) return
  getConfirmAction()("发布此启用配置？后续显式启用它的 AI 功能将固定使用该版本。", async () => {
    const owner = captureActivationOwner()
    try {
      const api = getApi()
      const saved = await api.context.publishActivationProfile(profile.id, { base_version_number: profile.version_number, revision_reason: "manual_publish" }, owner.novelId)
      if (!ownsActivationOwner(owner)) return true
      rememberActivationProfile(saved)
      getToast()("AI 参考规则已发布", "success")
    } catch (err) {
      if (ownsActivationOwner(owner)) {
        getToast()(err.message || "发布规则失败", "error")
        return false
      }
      return true
    }
  })
}

// ---- lifecycle ----
onMounted(() => {
  rootEl.value?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  mountAssetRefPicker()
  restoreLibraryScroll()
})

// 页面默认阅读态：编辑是显式切换，进入时再挂载依赖编辑 DOM 的资产选择器
watch(pageViewMode, (mode) => {
  if (mode === "edit") nextTick(() => mountAssetRefPicker())
})

onBeforeUnmount(() => {
  clearTimeout(libraryScrollRestoreTimer)
  activationMutationGeneration += 1
  cleanup()
  assetRefPicker?.destroy?.()
  assetRefPicker = null
  destroyActivationTargetPicker()
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
  assetRefPicker?.destroy?.()
  const picker = createReferencePicker({
    root,
    projectId: props.projectId,
    sources: assetRefSources(),
    mode: "multiple",
    maxItems: 50,
    placeholder: "按名称搜索关联资产",
    onOpen: (item) => openAssetRef(item.kind, item.id),
    onChange: (_items, refs) => {
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
  assetRefPicker = picker
}

function openAssetRef(type, id) {
  const router = getRouter()
  if (["world_bible_page", "page"].includes(type)) { openPageCard(id); return }
  if (["relation", "entity_relation"].includes(type)) { router.navigate("world", "relations"); return }
  if (["core_entity", "entity", "profile", "event"].includes(type)) {
    setDisplayMode("gallery")
    if (displayMode.value === "gallery") openWorldCard({ kind: "entity", id })
    return
  }
  getToast()("该引用类型暂无可用的编辑入口", "warning")
}

function setAssetRefRelation(index, relation) {
  const refs = editSource.value?.linked_asset_refs_json || []
  if (!refs[index]) return
  refs[index] = { ...refs[index], relation }
  const input = document.getElementById("bible-asset-refs")
  if (input) input.value = formatAssetRefs(refs)
}

function assetRefDisplayName(ref) {
  const kind = canonicalAssetRefType(assetRefType(ref))
  const id = assetRefId(ref)
  const kindLabel = { core_entity: "世界对象", entity_relation: "对象关系", world_bible_page: "世界书页面" }[kind] || kind
  if (kind === "world_bible_page") {
    const page = pages.value.find((item) => item.id === id)
    if (page?.title) return `${kindLabel} · ${page.title}`
  }
  return `${kindLabel} · ${String(id).slice(0, 8)}`
}

function assetRefType(ref) {
  return ref?.type || ref?.source_type || ref?.target_type || ""
}

function assetRefId(ref) {
  return ref?.id || ref?.source_id || ref?.target_id || ""
}


</script>

<style scoped>
.world-library-content { min-width: 0; }
.world-library-content :deep(.world-bible-page-card__actions) { flex-wrap: wrap; }
.world-library-browse { display: grid; grid-template-columns: 232px minmax(0, 1fr); gap: 22px; align-items: start; }
.world-library-browse__directory { position: sticky; top: 12px; }
.world-library-browse__main { display: grid; gap: 12px; min-width: 0; }
.world-bible-autosave-status { margin-left: 8px; color: var(--text-muted); font-size: 12px; }
.world-bible-autosave-status[data-autosave-status="conflict"] { color: var(--danger, #b42318); }
@media (max-width: 1100px) {
  .world-library-browse { grid-template-columns: minmax(0, 1fr); }
  .world-library-browse__directory { position: static; }
}
.world-type-results__header { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.world-type-results__header h2, .world-type-results__header p { margin: 0; }
.world-type-results__header p { margin-top: 3px; color: var(--text-muted); }
.world-more-types, .world-more-tools, .world-create-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.world-more-types .btn, .world-more-tools .btn, .world-create-choices .btn { min-height: 48px; justify-content: flex-start; }
.world-bible-open-questions__list { display: grid; gap: 8px; }
.world-bible-open-question { display: flex; min-height: 48px; align-items: flex-start; justify-content: space-between; gap: 12px; text-align: left; }
.world-bible-open-question small { color: var(--text-muted); }
@media (max-width: 760px) {
  .world-bible-toolbar__actions .btn, .world-bible-toolbar__actions summary { min-height: 44px; }
  .world-card-filters { grid-template-columns: minmax(0, 1fr); }
  .world-card-filters input, .world-card-filters select, .world-card-filters .btn { min-height: 44px; }
  .world-more-types, .world-more-tools, .world-create-choices { grid-template-columns: minmax(0, 1fr); }
}
</style>
