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
    <!-- toolbar -->
    <div class="world-bible-toolbar">
      <div class="world-bible-toolbar__title">
        <h1>人物与世界</h1>
        <span>{{ pages.length }} 个资料页 · {{ bibleEntityTotal }} 个人物或设定</span>
      </div>
      <div class="world-bible-toolbar__actions">
        <span class="world-bible-toolbar__modes" role="group" aria-label="世界笔记展示方式">
          <button
            v-for="(label, mode) in modeLabels"
            :key="mode"
            class="btn btn-sm btn-ghost"
            :class="{ 'is-active': displayMode === mode }"
            data-action="bible-set-display-mode"
            :data-mode="mode"
            :aria-pressed="displayMode === mode"
            @click="setDisplayMode(mode)"
          >{{ label }}</button>
        </span>
        <button v-if="displayMode === 'gallery'" class="btn btn-sm" data-action="bible-new-entity" @click="showEntityCreateForm()">新建人物或设定</button>
        <button class="btn btn-sm btn-primary" data-action="bible-new-page" @click="createPage">{{ displayMode === 'gallery' ? '新建资料页' : '新建页面' }}</button>
        <details
          ref="toolbarMoreEl"
          class="world-bible-toolbar__more scene-workbench-tools"
          data-section="bible-toolbar-more"
          @toggle="toolbarMoreOpen = $event.currentTarget.open"
          @keydown.esc.stop.prevent="closeToolbarMore(true)"
        >
          <summary class="btn btn-sm btn-ghost" aria-controls="world-bible-more-tools" :aria-expanded="String(toolbarMoreOpen)">更多工具</summary>
          <div id="world-bible-more-tools" class="world-bible-toolbar__more-actions scene-workbench-tools__menu" role="group" aria-label="更多工具">
            <button class="btn btn-sm" data-action="bible-manage-categories" @click="runToolbarAction(openCategoryManager)">管理分类</button>
            <button class="btn btn-sm" data-action="bible-manage-page-templates" @click="runToolbarAction(openPageTemplateManager)">页面模板</button>
            <button class="btn btn-sm" data-action="bible-open-worldbook-import" @click="runToolbarAction(() => { worldbookImportOpen = true })">导入目录</button>
            <button class="btn btn-sm" data-action="bible-open-suggestions" @click="runToolbarAction(openSuggestions)">创设建议</button>
            <button class="btn btn-sm" data-action="bible-open-conflicts" @click="runToolbarAction(openConflicts)">冲突检查</button>
            <button
              class="btn btn-sm"
              data-action="bible-inspect-current-page"
              :disabled="!activePage && !semanticInspectionPending"
              @click="runToolbarAction(inspectCurrentPage)"
            >{{ semanticInspectionPending ? "停止检修" : "检修当前页" }}</button>
          </div>
        </details>
      </div>
    </div>

    <WorldbookImportPanel
      :project-id="projectId"
      :open="worldbookImportOpen"
      :suggestion-id="bibleDeepLink.worldbookImportSuggestionId || ''"
      @close="worldbookImportOpen = false"
    />

    <WorldHealthPanel
      :project-id="projectId"
      :target-type="bibleDeepLink.adoptionPackageId ? 'world_adoption_package' : 'world_bible_draft'"
      :target-id="bibleDeepLink.adoptionPackageId || activeDraft?.id || ''"
      :requires-full-scope="validationRequiresFullScope"
      :initial-run="validationRun"
      :policy-status="validationPolicy"
      @updated="validationRun = $event"
      @policy-updated="validationPolicy = $event"
      @open-source="openValidationSource"
    />

    <details class="panel world-bible-open-questions" data-section="bible-open-questions">
      <summary>
        <strong>待我决定</strong>
        <span class="badge">{{ authorOpenQuestions.length }} 项</span>
        <span class="world-bible-open-questions__hint">
          {{ authorOpenQuestions.length
            ? `来自 ${authorOpenQuestionSourceCount} 个已保存页面`
            : "当前没有已保存的未决项" }}
        </span>
      </summary>
      <div v-if="authorOpenQuestions.length" class="world-bible-open-questions__list">
        <button
          v-for="entry in authorOpenQuestions"
          :key="entry.key"
          type="button"
          class="btn world-bible-open-question"
          :data-bible-open-question-page-id="entry.pageId || undefined"
          :data-bible-open-question-draft-id="entry.draftId || undefined"
          @click="openAuthorOpenQuestion(entry)"
        >
          <span>{{ entry.question }}</span>
          <small>{{ entry.sourceTitle }} · {{ entry.draftId ? "工作稿" : "已发布页" }}</small>
        </button>
      </div>
      <p v-else class="world-bible-empty-hint">AI 保留下来的未决选择会在这里汇总；这里只统计保存过的未勾选项目。</p>
    </details>

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
      <div v-else class="panel world-bible-gallery">
        <div class="world-bible-gallery__hero">
          <h2>人物与世界</h2>
          <p>在一处找回人物、地点、势力、物品、事件、规则和资料页。</p>
        </div>
        <form class="world-card-filters" role="search" @submit.prevent="applyCardFilters()">
          <label class="world-card-filters__search">
            <span>搜索资料</span>
            <input v-model="cardSearch" type="search" maxlength="120" placeholder="名称或内容" />
          </label>
          <label>
            <span>资料形态</span>
            <select :value="cardFilters.kind" @change="applyCardFilters({ kind: $event.target.value })">
              <option value="all">全部卡片</option>
              <option value="entity">人物与具体设定</option>
              <option value="page">资料页与工作稿</option>
            </select>
          </label>
          <label>
            <span>类型</span>
            <select :value="cardFilters.type" @change="applyCardFilters({ type: $event.target.value })">
              <option value="">全部类型</option>
              <option v-for="option in cardTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <div class="world-card-filters__actions">
            <button class="btn btn-sm btn-primary" type="submit">查找</button>
            <button v-if="hasCardFilters" class="btn btn-sm" type="button" @click="clearCardFilters">清除</button>
          </div>
        </form>
        <div v-if="props.bible?.entitiesLoadError" class="empty-state" role="alert" data-author-action="retry">
          <p>人物与设定暂时没有加载出来；资料页和工作稿仍可使用。</p>
          <button class="btn btn-sm" type="button" @click="retryCards">重新加载</button>
        </div>
        <div v-if="unifiedCards.length" class="world-bible-page-card-grid world-card-grid">
          <article
            v-for="card in unifiedCards"
            :key="card.key"
            class="world-bible-page-card world-card"
            :class="`world-card--${card.kind}`"
            :data-world-card-kind="card.kind"
            :data-world-card-id="card.id || card.draftId"
            :style="{ '--world-bible-type-color': cardMeta(card).color }"
          >
            <div class="world-bible-page-card__band"></div>
            <div class="world-bible-page-card__head">
              <div class="world-bible-page-card__icon">{{ cardMeta(card).symbol }}</div>
              <div class="world-bible-page-card__title">
                <h3>{{ card.title }}</h3>
                <div class="world-bible-page-card__meta">
                  <span>{{ cardMeta(card).label }}</span>
                  <span class="badge">{{ card.state === 'working' ? '工作稿' : '已采用' }}</span>
                </div>
              </div>
            </div>
            <p class="world-bible-page-card__summary">{{ card.summary || '还没有摘要，可以打开后补充。' }}</p>
            <div class="world-bible-page-card__footer">
              <span>{{ card.kind === 'page' ? '资料页' : '人物或具体设定' }}</span>
              <span v-if="card.draftId">已保留未发布修改</span>
            </div>
            <div class="world-bible-page-card__actions">
              <button class="btn btn-sm btn-primary" type="button" data-action="open-world-card" @click="openWorldCard(card)">{{ card.state === 'working' ? '继续编辑' : '打开' }}</button>
            </div>
          </article>
        </div>
        <div v-else-if="hasCardFilters" class="empty-state">
          <p>没有找到符合条件的资料。</p>
          <button class="btn btn-sm" type="button" @click="clearCardFilters">查看全部</button>
        </div>
        <div v-else class="empty-state">
          <p>还没有人物或世界资料。可以先建一个具体设定，也可以从空白资料页开始。</p>
          <div class="world-card-empty-actions">
            <button class="btn btn-sm" type="button" @click="showEntityCreateForm()">新建人物或设定</button>
            <button class="btn btn-sm btn-primary" type="button" @click="createPage">新建资料页</button>
          </div>
        </div>
        <p v-if="entityCardsTruncated" class="world-bible-empty-hint">
          这里先显示前 50 个人物或设定；需要完整管理时可进入对象库。
          <button class="btn btn-sm" type="button" @click="openObjectLibrary">查看对象库</button>
        </p>
        <div v-if="pages.length" class="world-bible-section-title">按资料页分类</div>
        <div v-if="pages.length" class="world-bible-category-grid">
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
      <section class="panel world-bible-graph" aria-labelledby="world-bible-graph-title">
        <div class="world-bible-panel__header">
          <div>
            <h2 id="world-bible-graph-title">关联图</h2>
            <div class="world-bible-page-meta">关联不等于变更影响；依赖影响未覆盖。</div>
          </div>
          <div class="world-bible-panel__actions" role="group" aria-label="关联图范围">
            <button class="btn btn-sm" data-action="bible-graph-depth-1" :disabled="!hasGraphPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 1" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 1 }" @click="setGraphDepth(1)">当前页 · 1 跳</button>
            <button class="btn btn-sm" data-action="bible-graph-depth-2" :disabled="!hasGraphPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 2" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 2 }" @click="setGraphDepth(2)">扩展到 2 跳</button>
            <button class="btn btn-sm" data-action="bible-graph-global" :aria-pressed="graphScope === 'global'" :class="{ 'btn-primary': graphScope === 'global' }" @click="setGraphScope('global')">全局</button>
          </div>
        </div>
        <p v-if="graphLoading" class="world-bible-empty-hint" role="status">正在加载关联图…</p>
        <div v-else-if="graphError" class="empty-state" role="alert">
          <p>{{ graphError }}</p><button class="btn btn-sm" data-action="bible-graph-retry" @click="loadKnowledgeGraph">重试</button>
        </div>
        <template v-else-if="knowledgeGraph">
          <p v-if="graphPartialDetails.length" class="world-bible-projection-status__hint">
            结果已部分省略：{{ graphPartialDetails.join('；') }}。
          </p>
          <p v-if="!knowledgeGraph.nodes?.length" class="world-bible-empty-hint">尚没有可展示的已采用关联。</p>
          <ul class="world-bible-graph__list" aria-label="关联图节点列表">
            <li v-for="node in knowledgeGraph.nodes || []" :key="node.id">
              <button class="btn world-bible-graph__node" :data-graph-node-kind="node.kind" :data-graph-node-id="node.id" @click="openGraphNode(node)">
                <strong>{{ node.label || '未命名资料' }}</strong><span>{{ node.kind === 'world_bible_page' ? '世界书页' : '世界对象' }}</span>
              </button>
            </li>
          </ul>
          <ul v-if="graphEdges.length" class="world-bible-graph__edges" aria-label="关联图关联列表">
            <li v-for="edge in graphEdges" :key="edge.id">{{ edge.sourceLabel }} → {{ edge.kindLabel }}{{ edge.via_relation_id ? '（经关系）' : '' }} → {{ edge.targetLabel }}</li>
          </ul>
          <details class="world-bible-graph__visual">
            <summary>查看关系示意图（最多 40 个节点 / 80 条边）</summary>
            <svg v-if="graphLayout.nodes.length" class="world-bible-graph__svg" :viewBox="`0 0 560 ${Math.max(160, graphLayout.nodes.length * 72 + 40)}`" role="img" aria-label="世界书关联示意图">
              <line v-for="edge in graphLayout.edges" :key="edge.id" :x1="graphLayout.positions[edge.source_id].x" :y1="graphLayout.positions[edge.source_id].y" :x2="graphLayout.positions[edge.target_id].x" :y2="graphLayout.positions[edge.target_id].y" />
              <g v-for="node in graphLayout.nodes" :key="node.id" :transform="`translate(${graphLayout.positions[node.id].x}, ${graphLayout.positions[node.id].y})`"><circle r="22" /><text y="4">{{ node.label?.slice(0, 8) }}</text></g>
            </svg>
          </details>
        </template>
      </section>
    </template>

    <!-- EDITOR mode (default) -->
    <template v-else>
      <!-- synopsis panel -->
      <details
        class="panel world-bible-synopsis-panel"
        data-section="bible-synopsis"
        :open="['queued', 'running'].includes(synopsis?.status)"
      >
        <summary class="world-bible-support-summary">
          <div>
            <strong>世界观简介</strong>
            <span class="badge">创作参考</span>
            <div class="world-bible-page-meta">AI 整理的参考资料；不会替代你已确认的核心设定。</div>
          </div>
          <span class="world-bible-support-summary__status">{{ taskStatusLabel(synopsis?.status || 'missing') }}</span>
        </summary>
        <div class="world-bible-synopsis-panel__body">
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
          <div v-else class="empty-state">
            <p>创建一个世界书页面开始整理设定。</p>
          </div>
        </main>

        <!-- activation inspector (right) -->
        <details
          class="panel world-bible-inspector"
          data-section="bible-ai-reference-rules"
          :open="Boolean(currentProfile || activationTrace)"
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
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getRouter, getToast, getShowModalHtml, getCloseModal, getConfirmAction } from "../../../bridge/index.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"
import { showEntityCreateForm } from "../logic/worldEntityOps.js"
import WorldbookImportPanel from "./WorldbookImportPanel.vue"
import WorldHealthPanel from "./WorldHealthPanel.vue"
import { knowledgeGraphLayout, useWorldBible } from "./useWorldBible.js"
import { buildWorldCards, worldCardQuery } from "./worldCards.js"

const props = defineProps({
  projectId: { type: String, default: null },
  subView: { type: String, default: "bible" },
  bible: { type: Object, default: null },
  bibleDeepLink: { type: Object, default: () => ({ draftId: "", pageId: "" }) },
  entityTypes: { type: Array, default: () => [] },
  worldCardFilters: { type: Object, default: () => ({ q: "", kind: "all", type: "" }) },
  defaultDisplayMode: { type: String, default: "editor" },
})

const rootEl = ref(null)
const toolbarMoreEl = ref(null)
const toolbarMoreOpen = ref(false)
const worldbookImportOpen = ref(Boolean(props.bibleDeepLink?.openWorldbookImport))
const validationRun = ref(props.bible?.validationRun || null)
const validationPolicy = ref(props.bible?.validationPolicy || { active: false })
watch(() => props.bibleDeepLink?.openWorldbookImport, (open) => {
  if (open) worldbookImportOpen.value = true
})

const modeLabels = { gallery: "总览", editor: "编辑资料页", filter: "资料页筛选", graph: "关联图" }

function closeToolbarMore(restoreFocus = false) {
  if (!toolbarMoreEl.value?.open) return
  toolbarMoreEl.value.open = false
  toolbarMoreOpen.value = false
  if (restoreFocus) nextTick(() => toolbarMoreEl.value?.querySelector("summary")?.focus())
}

function runToolbarAction(action) {
  const summary = toolbarMoreEl.value?.querySelector("summary")
  closeToolbarMore(false)
  summary?.focus()
  action()
}

function onToolbarOutsideClick(event) {
  if (toolbarMoreEl.value?.open && !toolbarMoreEl.value.contains(event.target)) closeToolbarMore(false)
}

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
  knowledgeGraph,
  graphLoading,
  graphError,
  graphScope,
  graphDepth,

  pages,
  drafts,
  pageTemplates,
  activationProfiles,

  onBeforeUnmount: cleanup,
  setDisplayMode,
  loadKnowledgeGraph,
  setGraphDepth,
  setGraphScope,
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
  inspectCurrentPage,
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
  ownsProject,
  captureModalOwner,
  ownsModalOwner,
  esc,
} = useWorldBible(props)

const graphLayout = computed(() => knowledgeGraphLayout(knowledgeGraph.value?.nodes || [], knowledgeGraph.value?.edges || []))
const cardFilters = computed(() => props.worldCardFilters || { q: "", kind: "all", type: "" })
const cardSearch = ref(cardFilters.value.q || "")
watch(() => cardFilters.value.q, (value) => { cardSearch.value = value || "" })
const bibleEntityTotal = computed(() => Number(props.bible?.entityTotal || 0))
const unifiedCards = computed(() => buildWorldCards({
  pages: pages.value,
  drafts: drafts.value,
  entities: props.bible?.entities || [],
  filters: cardFilters.value,
}))
const hasCardFilters = computed(() => Boolean(cardFilters.value.q || cardFilters.value.type || cardFilters.value.kind !== "all"))
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
const hasGraphPageRoot = computed(() => Boolean(activePage.value?.id))
const graphPartialDetails = computed(() => {
  const result = knowledgeGraph.value || {}
  const counts = Object.entries(result.omitted_counts || {}).filter(([, value]) => Number(value) > 0)
  const reasons = result.truncated ? (result.truncation_reasons || []) : []
  return [...reasons, ...counts.map(([key, value]) => `${key} ${value}`)]
})
const graphEdges = computed(() => {
  const labels = new Map((knowledgeGraph.value?.nodes || []).map((node) => [node.id, node.label || "未命名资料"]))
  const kinds = { page_reference: "页面引用", page_entity_reference: "页面关联对象", entity_relation: "对象关系" }
  return (knowledgeGraph.value?.edges || []).map((edge) => ({ ...edge, sourceLabel: labels.get(edge.source_id) || "不可用来源", targetLabel: labels.get(edge.target_id) || "不可用目标", kindLabel: kinds[edge.kind] || "关联" }))
})
function openGraphNode(node) {
  if (node.kind === "world_bible_page") return openPageCard(node.id)
  getRouter()?.navigate("world", "objects", true, new URLSearchParams({ entity_id: node.id }))
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
  if (overrides.kind === "page" && next.type && !pages.value.some((page) => page.page_type === next.type)) next.type = ""
  getRouter()?.navigate("world", "bible", true, worldCardQuery(next))
}

function clearCardFilters() {
  cardSearch.value = ""
  getRouter()?.navigate("world", "bible", true, new URLSearchParams())
}

function retryCards() {
  getRouter()?.refresh?.()
}

function openObjectLibrary() {
  const query = new URLSearchParams()
  if (cardFilters.value.q) query.set("q", cardFilters.value.q)
  if (cardFilters.value.type) query.set("entity_type", cardFilters.value.type)
  getRouter()?.navigate("world", "objects", true, query)
}

function openWorldCard(card) {
  if (card.kind === "entity") {
    getRouter()?.navigate("world", "objects", true, new URLSearchParams({ entity_id: card.id }))
    return
  }
  if (card.id) openPageCard(card.id)
  else if (card.draftId) openDraft(card.draftId)
}

function openValidationSource(target) {
  if (target?.kind === "draft") openDraft(target.id)
  else if (target?.kind === "page") openPageCard(target.id)
}

// ---- computed locals ----
const freeDrafts = computed(() => drafts.value.filter((d) => !d.page_id))
const canPublish = computed(() => activePage.value?.status !== "archived")
const validationRequiresFullScope = computed(() => Boolean(props.bibleDeepLink?.adoptionPackageId)
  || ["rule", "schema", "terminology", "world_core"].includes(activeDraft.value?.page_type)
  || Boolean(activeDraft.value?.page_meta_json?.validation_policy)
  || Boolean(activeDraft.value?.linked_asset_refs_json?.length))
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
const authorOpenQuestionSourceCount = computed(
  () => new Set(authorOpenQuestions.value.map((item) => item.sourceKey)).size,
)
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
    activeActivationProfileId.value = saved.id
    activationTrace.value = null
    getToast()("规则工作稿已保存；发布前不会影响真实调用", "success")
    getRouter().refresh()
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
      activeActivationProfileId.value = saved.id
      getToast()("AI 参考规则已发布", "success")
      getRouter().refresh()
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
  document.addEventListener("click", onToolbarOutsideClick)
})

onBeforeUnmount(() => {
  activationMutationGeneration += 1
  cleanup()
  assetRefPicker?.destroy?.()
  assetRefPicker = null
  destroyActivationTargetPicker()
  document.removeEventListener("click", onToolbarOutsideClick)
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
  if (["core_entity", "entity", "profile", "event"].includes(type)) { router.navigate("world", "objects"); return }
  getToast()("该引用类型暂无可用的编辑入口", "warning")
}

function assetRefType(ref) {
  return ref?.type || ref?.source_type || ref?.target_type || ""
}

function assetRefId(ref) {
  return ref?.id || ref?.source_id || ref?.target_id || ""
}


</script>
