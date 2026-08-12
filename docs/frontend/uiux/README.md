# UI/UX 设计规范与执行指南

本目录是前端「Editorial Archive 提纯」二次设计的权威规范集，供执行 agent 按页面认领实施。
**本目录只含设计标准与执行规范，不含业务需求**；业务契约以 `docs/modules/14_frontend.md`、
各模块 README 与 `AGENTS.md` 为准。

## 文件索引

| 文件 | 内容 |
|---|---|
| `design-standard.md` | 主规范：设计原则、token 终态、色彩/ Typography/ Spacing/ 组件/ 响应式/ 动效/ 无障碍标准、死代码清理清单 |
| `pages/today.md` | 今日工作台（首页） |
| `pages/writing.md` | 写作编辑器（核心页，三栏） |
| `pages/world.md` | 人物与世界（9 子视图 + 3 审核队列） |
| `pages/outline-scene.md` | 故事结构 4 子视图 + 场景工作台 |
| `pages/map.md` | 地图总览 + 沉浸画布（仅表层，不动 mapView.js 引擎） |
| `pages/rag.md` | 查找/检索 + 索引状态 |
| `pages/generate.md` | 高级生成 4 tab |
| `pages/project.md` | 作品档案/导入/回收站 |
| `pages/settings.md` | 账户设置 + 项目偏好（表单页） |
| `pages/rp-experience.md` | RP 沉浸路径：home / journeys / interaction |

## 执行顺序（全局 → 页面 → 细节）

1. **全局层先行**（由单个 agent 顺序完成，相互耦合不可并行）：
   - G1 token 层归一（`design-standard.md` §1）：删死色板、迁移别名、tracking 修正、同步
     `editorialTheme.test.js` / `typographyTokens.test.js`。
   - G2 组件层去重（§5）：合并"定义→覆写"两步、消除可消除的 `!important`、收编非 scoped SFC 内联样式。
   - G3 断点归一（§6）：720→760 合并、长尾断点处置。
2. **页面层并行**（每个页面文件可由不同 agent 认领，一次一个）：
   优先级顺序：writing → world → today → outline-scene → rag → generate → settings → project → rp-experience → map。
3. **细节收口**：交互状态与无障碍抽查（§7/§8）、五视角 Review（设计师/产品/普通用户/高频用户/前端工程师）。

## 认领规则

- 一次只认领一个页面文件；开始前在 PR 描述注明对应 `pages/*.md`。
- 跨页面共享组件（btn/card/modal/subnav/empty-state…）的样式只能按 `design-standard.md` §5 改全局规则，**禁止在页面规范外自创组件变体**；发现标准未覆盖的场景，回本目录补标准再实施。
- 页面规范中「必须保留的契约」一节列出的 `#id` / `data-action` / role 名称 / 可访问名称是测试契约，改动必须同步对应 e2e/vitest。

## 硬约束（违反即返工）

- 不改业务规则、API shape、路由结构；LLM/数据流相关一律不碰。
- 不动 `frontend-console/views/mapView.js` 内部架构（仅表层 class 对齐）。
- 不引入新依赖；不做 Vue 组件库化重构（ADR-0009 语义 class 路线）。
- 动态内容不得进 `innerHTML`/`v-html` 未转义；不提交 `.env`。
- 危险操作（合并/删除/废弃）保留二次确认 UI。
- 分支：从最新 `origin/main` 建 `codex/<slug>`，不直提 main。

## 验证命令速查

```bash
cd frontend-console
npm run test                          # vitest（含 CSS 契约测试）
npm run test:e2e:smoke                # 功能冒烟（home/project/import/writing）
npm run test:e2e:core                 # 核心集（含 world/outline-scenes/map）
npm run test:e2e:visual               # 视觉回归（39 张三主题快照）
npm run test:e2e:visual:update        # 重建视觉基线（改动确认后执行，逐张过目）
make docs-check BASE_REF=origin/main  # 仓库根目录，文档同步核对
```

## 完成定义（每个页面/阶段）

1. 对应 `pages/*.md` 的「验收标准」全部满足；
2. `npm run test` 全绿；受影响的 e2e 子集全绿；
3. 视觉快照差异逐张人工确认后 `test:e2e:visual:update` 重建；
4. `docs/modules/14_frontend.md` 与 `frontend-console/README.md` 同步（如布局契约/文件结构变化）；
5. `make docs-check BASE_REF=origin/main` 通过或逐项说明无影响。

## 已知但不属于本规范范围的问题

- `:save` / `:export` 是只 toast 不执行的假命令（`frontend-console/commands.js:188-196`）——产品决策项，UI 执行不得擅自实现或删除。
- RP 路径与作者路径的主题切换入口重复（InteractionView 内置 vs Topbar ThemePicker）——裁定见 `pages/rp-experience.md`。
