# 设置页 UI/UX 执行规范（账户设置 / 项目偏好）

> 依据：`docs/frontend/uiux/design-standard.md`（下称主规范，§x 均指该文件）、
> 2026-08 页面级调研（带行号证据）、`docs/product/user-personas.md`。
> 行号均以 `frontend-console/` 为根；`GlobalSettingsView.vue` / `ProjectSettingsView.vue`
> 均位于 `vue/views/settings/`。本文件只定 UI/UX 执行标准，不改业务规则与 API shape。

## 1. 页面定位与目标画像

- **账户设置（`/#settings`，GlobalSettingsView.vue）**：账号级模型连接（provider 选择、API Key、余额）与全局作者偏好。主服务**画像 A**（作者）：连接一次、长期不再回来，要求"看得懂、改得安心"。RP 回跳场景（`returningToRp`，:34-37, :217-223）临时服务**画像 B**：此时只保留连接区并承诺"连接成功后会回到刚才的旅程位置"（:241），不暴露作者偏好区——该分层正确，必须保留。
- **项目偏好（`/#workbench/:id/project-settings`，ProjectSettingsView.vue）**：纯画像 A。两个 tab：「创作偏好」（全局默认的项目级覆盖，高频低危）与「高级导入」（深度导入流水线参数，低频专家向）。按 §0 决策优先级与画像准则，**默认 tab 必须停留在创作偏好**；高级导入是渐进展开的第二层，不得提升其视觉权重。
- 用户会喜欢的理由（产品假设，待真实数据验证）：作者能在一个页面确认"当前用哪个模型、Key 是否有效、余额还剩多少"，并按项目微调偏好且随时一键回到全局默认；RP 用户被引导来补连接时能立刻回去继续故事。
- 主要摩擦：失败反馈全靠瞬时 toast（§2 问题 4/5）；高级导入参数名暴露流水线内部心智（§2 问题 8）。

## 2. 现状问题清单（按严重度排序）

**P0 功能/门禁**

1. **项目页加载失败死锁**：`loadProjectSettings` 失败时返回 `effectiveLLM/effectivePrefs = null`（vue/settingsIslands.js:61-70），`dataReady` 永假（ProjectSettingsView.vue:52），页面永久停在 `<p role="status">加载中…</p>`（:334），无错误文案、无重试入口。
2. **`e2e/visual-settings.spec.js` 整体漂移**：断言标题「账户设置」（:81）、「项目设置」（:93）与现行「账户与模型连接」（GlobalSettingsView.vue:224）、「项目偏好」（ProjectSettingsView.vue:241）不符；tab 名「深度导入」「作者偏好」（:101, :105）与现行「高级导入」「创作偏好」（ProjectSettingsView.vue:24-27）不符；mask 的 `.projects-using-list`（spec :35）在视图中已不存在，仅 styles.css:9312-9319 残留死样式。视觉门禁当前必然红或长期未跑。
3. **账户页连接加载失败裸空白**：`listLLMConnections` 失败降级为空 providers 数组（GlobalSettingsView.vue:21-24），radiogroup 渲染为空白区域，仅 console.error + 一次 toast（vue/settingsIslands.js:28-31），无空态无重试。

**P1 交互与反馈**

4. **校验与失败全靠瞬时 toast**：空 Key（GlobalSettingsView.vue:130-133）、偏好越界（:176-177）、保存失败（:146, :186；ProjectSettingsView.vue:134, :146, :180）均无字段级内联错误，toast 消失后无从回看原因；成功亦无持久确认（无"已保存"就态标记）。
5. **dirty 状态不可见**：两页均有 leave guard（GlobalSettingsView.vue:198-210；ProjectSettingsView.vue:213-225），但页面上没有任何"有未保存修改"的持续指示，用户只能离开时被动发现。
6. **`.form-row` 窄屏不换行**：styles.css:1103-1107 为无 wrap 的 flex 横排，无任何媒体查询；作者偏好三栏与高级导入多栏在 <640px 被压成窄列。editorial 仅对 world/generate 的 tab 做了窄屏降级（editorial-theme.css:1334-1348），表单行没有同等待遇。
7. **`#theme-toggle` 三方样式争抢**（完整证据链）：
   - A. SFC 非 scoped 内联样式（ThemePicker.vue:121-125，`<style>` 无 scoped，全局注入，均有 `.topbar-theme` 前缀，无 `!important`）；
   - B. 结构层 hover/active 规则（styles.css:8766-8785，4 条全 `!important`，含 `[data-theme="dark"]` 变体 :8779-8785）；
   - C. editorial 覆层（editorial-theme.css:193-214，`#theme-toggle.btn-icon` 4 个 `!important`、菜单 hover 朱红文字 `!important`）；
   - 胜负关系：基样式 C 靠 `!important` 无条件压 A ✓；但 **C 未写 `#theme-toggle:hover`**，B 的灰调 `--bg-hover` 在 editorial 主题下漏出，toggle hover 是结构层灰色而非主题风格（真实断裂点）；菜单项 hover B/C 同特异性同 `!important`，C 靠加载顺序赢 → dark 主题下菜单 hover 也变成 editorial 朱红文字，B 的暗色适配被吃掉。另有 toggle 图标恒为「☀」不随主题变化（ThemePicker.vue:15）。
8. **高级导入组名面向开发者**：「Global」「Phase 0 Plan」「Phase 1A Scene Slicing」「Reducer max tokens」等中英混排（logic/deepImport.js:7-97），向作者暴露内部流水线心智，违反 AGENTS.md「不暴露内部枚举/工程术语」；h4 组标题与字段之间无 helper，参数用途全靠字段名。

**P2 结构与一致性**

9. **Key 安全信息权重不足**：「Key 加密保存、验证产生费用」与操作引导共用 `.settings-section-hint`（GlobalSettingsView.vue:239-242 vs :294-296），费用提示无视觉区分；已连接时的就态说明放在 placeholder（:291），输入后即消失。
10. **两页分组层级不统一**：全局页 h2→section h3（:238, :328）；项目页 h2→tab→（仅高级导入有 h4），「创作偏好」tab 内无区块标题（:313-332 vs GlobalSettingsView.vue:328）。且项目页 tab 内容不在 `.settings-section` 内，吃不到 editorial 卡片化 + 红角标 + 序号水印（editorial-theme.css:781-801, :814-827, :1206-1217），两页视觉密度不一致。
11. **重复 id 隐患**：`#project-settings-goto-global` 出现两次（ProjectSettingsView.vue:232 空态分支、:266 notice 条），靠 v-if/v-else 互斥保命，重构易踩雷。
12. **表单细节**：「默认专注模式」用 span + 嵌套 label 伪 label 结构（AuthorPreferencesForm.vue:56-61），可访问名称依赖 DOM 顺序而非 `for`/`aria-labelledby`；`select` 复用 `.form-input`（:42），editorial 下得到文本框式 3px 左边线但无下拉箭头（`.form-select` 的箭头 SVG 在 styles.css:1068-1084，未被使用）。
13. **结构层与覆层风格相反**：`.form-input` 结构层是下划线式（styles.css:1019-1032），editorial 覆层是盒式（editorial-theme.css:610-629），结构层在 editorial 下成死代码，维护双份心智（属主规范 §1.1/§10 全局项，本页执行时随表单触碰一并归并）。
14. **测试钩子无集中选择器**：selectors.js 仅主题两条（e2e/helpers/selectors.js:73-74），settings 各 spec 自行硬编码 id/role。

## 3. 目标布局与信息层级

### 3.1 账户设置（`/#settings`）

```
h2 账户与模型连接（+「进入当前项目 →」）
└─ section「连接 AI 服务」(h3)
   ├─ hint（操作引导，--text-sm secondary，一级）
   ├─ provider 卡片栅格（role=radiogroup，2 列 → 窄屏 1 列）
   ├─ Key 字段组：label → input → helper/error（缩进链见下）
   ├─ 安全提示行（warning 语义：左 2px --warning 线 + --text-sm，区别于引导 hint）
   └─ 操作行：主按钮（验证、保存并使用）→ 清除 Key（btn-link）→ 刷新余额（btn-link）
└─ section「通用创作偏好」(h3)（RP 回跳时整段隐藏，保留现状）
   ├─ AuthorPreferencesForm（日更目标 / 编辑器字体 / 默认专注模式）
   └─ 操作行：保存作者偏好（btn-primary）
```

### 3.2 项目偏好（`/#workbench/:id/project-settings`）

```
h2 项目偏好 ·项目名 + tablist（创作偏好 | 高级导入）
├─ aside 模型提示条（当前模型：label · model · 未连接 / 管理账户与模型连接）
└─ #project-settings-tab-panel（role=tabpanel）
   ├─ tab 创作偏好：补 h3 级区块标题「创作偏好」与全局页对齐信息 scent
   │  └─ AuthorPreferencesForm + SourceLabel + 字段级「恢复到全局默认」
   └─ tab 高级导入：hint → 来源行 → h4 分组表单（组名改用户语言）→ 操作行
```

**表单分组层级与缩进链（落主规范 §5.2）**：

- 层级：页面标题 h2（衬线 24）→ 区块 h3（16/600，项目页两个 tab 面板各补一个）→ 子分组 h4（仅高级导入，14/600）→ 字段 label。
- 缩进链：label（`--text-sm`、`--text-secondary`，位于控件上方、间距 `--space-1`）→ 控件（底 `--bg-elevated`、边 `--line-default`、`--radius-sm`，高 36px 桌面 / ≥44px 触控）→ helper（`--text-xs`、`--text-secondary`）/ error（`--text-xs`、`--error`，与 helper 同位互斥）。
- SourceLabel 与「恢复到全局默认」与 helper 同级缩进，顺序：控件 → SourceLabel 行 → error/helper。
- 现状 `.form-group label` 间距为 `--space-2`（styles.css:1095-1101），执行时收敛到 `--space-1`，全站表单统一。

## 4. 逐区域标准

### 4.1 模型连接区（provider 选择）

- 卡片栅格保持 `role="radiogroup"` + `role="radio"` + roving tabindex 与方向键/Home/End（GlobalSettingsView.vue:244-281, :59-85）——键盘契约不动。
- 卡片信息序：名称（条目标题档）→ 模型（`--text-sm` secondary）→ 状态行（已连接/未连接/当前使用）→ 余额（mono 计数 + 「余额可能有延迟」`--text-xs` tertiary）。状态用文字 + 色点，不用彩色 pill（§5.8）。
- 选中态：`--line-active` 语义（左侧 3px 朱红或 `--accent` 描边），不新增卡外阴影。
- 切换 provider 清空已输入 Key（:46-49）属现状合理保护，保留；但清空时若已有输入应先给就地确认提示（防误触丢 Key）。

### 4.2 API Key（安全敏感信息呈现）

- **掩码**：`type="password"` + `autocomplete="new-password"` 保持（:286-290）；已保存的 Key 永不回显、不提供复制按钮——界面上只出现「已连接/已验证」状态，不出现掩码串或尾号（当前接口不返回 Key 本体，维持该边界）。
- **验证状态反馈**（目标三态，替代纯 toast）：
  - 验证中：主按钮 spinner + `aria-busy`（现状 :300-309 保留），Key 输入框禁用，卡片行内显示「正在验证连接…」；
  - 成功：toast 保留，卡片状态即时翻转为「已连接 · 当前使用」，Key 框旁出现持久「已验证」helper（`--success` 色点 + 文字），placeholder 不再承担就态说明；
  - 失败：字段级内联 error（`--error` 边 + helper 变错文，§5.2 状态链）+ toast 保留，按钮抖动动画（styles.css:9224-9233）可保留但不得是唯一反馈。
- **费用与安全提示**：第二条 hint（:294-296）升格为 warning 语义行（左 2px `--warning` 线），与操作引导 hint 视觉分级；文案保持用户语言，不出现「加密存储实现细节」。
- **清除 Key**：二次确认保留（:156-158，文案已说明影响范围，符合 AGENTS.md 危险操作约束）。

### 4.3 作者偏好（全局 + 项目共用 AuthorPreferencesForm）

- 三字段目标结构全部改真 label：`for` 指向 `#author-daily-goal` / `#author-editor-font` / `#author-default-focus`（AuthorPreferencesForm.vue:27, :41, :56-61 现状）。
- `select` 改挂 `.form-select`（或补齐箭头样式），获得下拉箭头视觉（styles.css:1068-1084）。
- 校验（日更目标 0-100000 等）失败：字段级内联 error + warning toast，不再只有 toast（:176-177 现状）。
- 桌面三栏横排保持；窄屏纵排（§6）。

### 4.4 项目偏好（来源与覆盖）

- SourceLabel 四态配色（styles.css:9174-9192）保留，统一为「文字 + 色点」而非 pill 底（§5.8）；unset 态维持 warning 语义。
- 「恢复到全局默认」保持 `.btn-link` 三级操作（AuthorPreferencesForm.vue:32-38 等），成功 toast 文案含字段中文名（现状 :202 用字段 key，执行时核实后端返回后改用户语言）。
- 模型提示条（ProjectSettingsView.vue:263-270）保留灰底横条形态；「· 未连接」状态前置 warning 色点，引导按钮文案不变。

### 4.5 高级导入（专家区）

- h4 分组保留，但组名改用户语言（如「全局」「导入规划」「场景切分」「场景融合」「世界抽取」「结构分析」），字段 label 中「Max tokens」「Reducer」等工程词逐步替换为中文功能描述；映射表执行时与后端 key 一一核对（logic/deepImport.js:7-97），**只改显示文案，不改 key**。
- 每个 h4 组下补一句 helper（`--text-sm` secondary）说明该组参数影响什么。
- 越界/类型校验失败同 §4.3：字段级内联 error（现状 ProjectSettingsView.vue:134 只有 toast）。
- 「恢复默认」二次确认保留（:153-154）。

## 5. 状态覆盖清单

| 状态 | 现状缺口 | 目标形态 |
|---|---|---|
| 空态（无项目） | 项目页已有（:229-236），保留 | `.empty-state` + 引导 + 返回按钮（§5.9） |
| 空态（连接列表加载失败） | **缺**：空白 radiogroup + 一次 toast（vue/settingsIslands.js:28-31） | `.error-card`：一句人话 + 「重试」按钮（§5.9） |
| 加载中 | 账户页无指示（island 预取）；项目页纯文本「加载中…」（:334） | `.loading-skeleton` 骨架屏，reduced-motion 降级（§5.9） |
| 加载失败（项目页） | **缺**：永久停在「加载中…」（:52, :334；vue/settingsIslands.js:61-70） | `.error-card` + 重试；`dataReady` 区分 loading/error/ready 三态 |
| 验证/保存中 | 按钮 spinner + `aria-busy`（:237, :307）已有 | 保留；另禁用手区内其余按钮 |
| 保存成功 | 仅瞬时 toast | toast + 字段/卡片持久「已验证/已保存」helper |
| 保存失败 | toast + 按钮抖动 500ms | 字段级内联 error + toast；抖动降为辅助 |
| 校验失败 | warning toast，无内联（:131, :177） | §5.2 error 链：红边 + 错文 + toast |
| 冲突（他处已改） | 无并发检测（执行时核实后端语义） | 至少保证保存失败文案可读，不做静默覆盖 |
| 余额不可用 | 已有降级文案「余额暂时无法获取」（:277） | 保留 |
| 未连接 | 卡片「未连接」+ placeholder 引导；notice 条「· 未连接」 | 保留；placeholder 就态说明改为 helper |
| 未保存修改 | 仅离开拦截，无可视标记（:198-210；ProjectSettingsView.vue:213-225） | 操作行旁「有未保存修改」`--text-sm` warning 持续指示 |

## 6. 响应式行为（四档）

| 档位 | 行为 |
|---|---|
| Desktop ≥1440 | 表单页内容限宽居中（Key 输入 640px 上限 styles.css:9443-9445 保留并归 token）；provider 栅格 2 列 |
| Laptop 1100-1440 | 默认形态，同上 |
| Tablet 760-1100 | provider 栅格降 1 列；`.form-row` 允许 2 列或纵排 |
| Mobile <760 | 单栏：`.form-row` 纵排（修复 styles.css:1103-1107 无 wrap 缺陷）；`.settings-actions` 纵排按钮 100% 宽（styles.css:9477-9484 已有）；输入 ≥44px / 16px（editorial-theme.css:1305-1314 已有）；tab 横向滚动 + scroll-snap（:1316-1327 已有）；模型提示条纵排（styles.css:9495-9498 已有） |

- 现状双断点（styles.css ≤640 :9461-9499 + editorial ≤760 :1263-1371）随主规范 §6 断点归一合并到 760 一档；390px 页面级横向溢出零容忍。

## 7. 必须保留的契约

**#id（测试锚点，改名必须同步 e2e）**

- GlobalSettingsView.vue：`#goto-recent-project-btn`(:229)、`#account-llm-api-key`(:286)、`#account-llm-save`(:300)、`#account-llm-clear`(:312)、`#account-balance-refresh`(:318)、`#global-author-save`(:332)
- AuthorPreferencesForm.vue：`#author-daily-goal`(:28)、`#author-editor-font`(:42)、`#author-default-focus`(:59)
- ProjectSettingsView.vue：`#project-settings-goto-global`（:232 与 :266 **重复**，执行时改为两个不同 id 并全局 grep 同步测试）、`#project-settings-tab-author` / `#project-settings-tab-deep`（tabId :71-73）、`#project-settings-tab-panel`(:273)、`#deep-import-tab-save`(:294)、`#deep-import-tab-reset-all`(:306)、`#author-prefs-tab-save`(:321)；深度导入字段 `deep-import-{group}-{key}`（logic/deepImport.js:101-103）
- ThemePicker.vue：`#theme-toggle`(:4)、`#theme-menu`(:16)

**data-\* / class 语义钩子**

- `data-provider-id`(:255)、`data-tab`(:250)、`.field-reset[data-field="daily_goal|editor_font|default_focus_mode"]`(:35, :51, :68)、`.theme-option[data-theme-value="minimal|warm|dark"]`(:25)、`.author-prefs-tab[data-mode="project"]`(:313)、`.source-label.source-{project,global,system,unset}`

**role / 可访问名称（改名必须全局 grep 同步 e2e，§9）**

- radiogroup「模型模板」+ radio + `aria-checked` + roving tabindex（:244-258）
- tablist「项目偏好」+ tab + `aria-selected` + `aria-controls="project-settings-tab-panel"`（:244-256）；tabpanel 动态 `aria-labelledby`（:276）
- 「切换主题」+ `aria-haspopup="menu"` + `aria-controls` + `aria-expanded`（:9-12）；menu + menuitemradio + `aria-checked`（:16-24）
- `.rp-icon-button`「返回旅程」（:217-223）；各 section/按钮 `aria-busy`（:237, :307, :321, :327, :339）；加载态 `role="status"`（:334）
- 视图标题「账户与模型连接」「项目偏好」、tab 名「创作偏好」「高级导入」、按钮「保存作者偏好」为 e2e role 定位文案，修改需同步 spec。

## 8. 验收标准 + 验证命令

**验收标准**

1. §5 状态表 12 项全部有目标形态实现；项目页加载失败出现 `.error-card` + 重试，不再死锁「加载中…」。
2. 表单缩进链符合 §5.2：label 与控件间距 `--space-1`、控件 36px/触控 ≥44px、helper/error 分色（`--text-secondary` / `--error`）。
3. 校验失败、保存失败均有字段级内联 error；保存成功有持久就态标记。
4. `#theme-toggle` 收敛为单一来源规则（收编 ThemePicker.vue:121-125 非 scoped 样式，消除 styles.css:8766-8785 与 editorial-theme.css:193-214 的 `!important` 博弈）；editorial 下 toggle hover 不再是结构层灰；dark 主题菜单 hover 不被朱红覆层吃掉；三主题快照逐一过目。
5. `.form-row` 在 <760px 纵排，390px 无横向溢出。
6. 高级导入组名/字段名改用户语言（key 不变）；重复 id `#project-settings-goto-global` 拆分并同步测试。
7. §7 全部契约保留；settings 语义钩子收进 `e2e/helpers/selectors.js`。

**验证命令**

```bash
cd frontend-console
npm run test                                  # vitest（含 CSS 契约测试）
npx playwright test e2e/visual-settings.spec.js --update-snapshots   # 修正 spec 断言后重建基线
npx playwright test e2e/visual-settings.spec.js                      # 8 张快照全绿
```

- 视觉基线共 **8 张**：`settings-global-{minimal,warm,dark}.png` ×3 + `settings-project-{minimal,warm,dark}.png` ×3（6 张三主题）+ `settings-project-tab-deep-import.png` + `settings-project-tab-author.png` ×2（单主题 tab）。
- 重建前先修正 spec 漂移断言（:81「账户与模型连接」、:93「项目偏好」、:101「高级导入」、:105「创作偏好」、:35 移除失效 mask），再逐张人工过目后提交基线（README「验证命令速查」流程）。
- 收尾：`make docs-check BASE_REF=origin/main`（仓库根目录）通过或逐项说明无影响。
