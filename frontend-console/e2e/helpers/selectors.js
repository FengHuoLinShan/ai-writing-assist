/**
 * 统一 DOM 选择器常量
 */

export const SEL = {
  // 顶部状态栏
  topbarTitle: ".logo",
  topbarProject: "#topbar-project",
  topbarStatus: "#topbar-status",

  // 侧边栏
  sidebar: "#sidebar",
  navItem: (view) => `[data-view="${view}"]`,

  // 工作区
  workspace: "#workspace",
  workspaceContent: "#workspace-content",
  viewTitle: "#topbar-module",

  // 空态 / 加载
  emptyState: ".empty-state",
  loading: ".loading",
  loadingSkeleton: ".loading-skeleton",

  // 数据表格
  dataTable: ".data-table",
  tableRow: (id) => `tr[data-id="${id}"]`,
  clickableRow: "tr.clickable",

  // 项目卡片
  projectGrid: ".project-grid",
  projectCard: (id) => `.project-card[data-id="${id}"]`,
  projectImportToggle: '[data-action="toggle-import"]',
  projectImportFile: "#pv-import-file",
  projectImportSubmit: '[data-action="upload-file"]',
  projectImportHistory: "#import-list-body",
  projectImportHistoryRetry: '[data-action="retry-import-history"]',

  // 按钮
  btnPrimary: ".btn-primary",
  btnDanger: ".btn-danger",
  btnSm: ".btn-sm",

  // 模态框
  modalOverlay: "#modal-overlay",
  modalContent: "#modal-content",
  modalTitle: "#modal-title",
  modalBody: "#modal-body",
  modalFooter: "#modal-footer",
  modalClose: "#modal-close",

  // 表单
  formInput: ".form-input",
  formSelect: ".form-select",
  formTextarea: ".form-textarea",

  // Toast
  toastContainer: "#toast-container",
  toastItems: "#toast-container > *",

  // 主题
  themeToggle: "#theme-toggle",
  themeOption: (theme) => `#theme-menu [data-theme-value="${theme}"]`,

  // 写作台
  writingToolbar: ".writing-toolbar",
  writingWorkspace: ".writing-workspace-layout",
  writingTreeRail: ".writing-tree-rail",
  writingPanelRail: ".writing-panel-rail",
  writingEditorContainer: "#writing-editor-container",
  writingEditor: "#writing-editor",
  writingSheet: ".writing-sheet",
  writingSceneLabel: ".scene-tree-label",
  writingSceneCockpit: ".scene-cockpit",
  mobileQuickNote: ".mobile-quick-note",
  mobileNoteEditor: "#mobile-note-editor",
  writingToolsMenu: "details.writing-tools-menu > summary",
  deepImportProgress: "#writing-deep-import-bar-container",
  deepImportMapNext: '[data-action="deep-import-map-next"]',

  // 世界书
  worldBibleWorkspace: ".world-bible-workspace",
  worldBibleNewPage: '[data-action="bible-new-page"]',
  worldBibleCreateTitle: "#bible-create-title",
  worldBibleSavePage: '[data-action="bible-save-page"]',
  worldBiblePublishPage: '[data-action="bible-publish-page"]',
  worldBibleImproveWithAi: '[data-action="bible-improve-with-ai"]',

  // 地图
  mapBreadcrumb: ".map-breadcrumb",
  mapCanvas: "[data-testid='map-canvas']",
  mapDetailPanel: "#map-detail-panel",
  mapFactionBar: ".map-faction-bar",
  mapLeaflet: "#map-leaflet",
  mapSceneBar: ".map-scene-bar",
  mapSceneLabel: ".map-scene-label",
  mapTerrainSelect: "#map-terrain-select",
  mapBindSelect: "#map-bind-select",
  mapBindCenter: "#map-bind-center",
  mapMarkerType: "#map-marker-type",
  mapMarkerEntity: "#map-marker-entity",
  mapMarkerLabel: "#map-marker-label",
  mapMarkerSceneStart: "#map-marker-scene-start",
  mapMarkerSceneEnd: "#map-marker-scene-end",
  mapTerritoryFaction: "#map-territory-faction",
  mapDetailName: "#map-detail-name",
  mapDetailAutogen: "#map-detail-autogen",

  // 命令栏
  commandInput: "#command-input",
  commandPrompt: "#command-prompt",
  commandBar: "#command-bar",

  // 帮助
  helpOverlay: "#help-overlay",
  helpClose: "#help-close",

  // 右侧批注区
  contextualNotes: "#contextual-notes",

  // 子标签
  subnavItem: (sub) => `[data-subview="${sub}"]`,
}
