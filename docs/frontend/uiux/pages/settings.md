# 设置页 UI/UX 执行规范（账户设置 / 当前作品设置）

> 依据：`docs/frontend/uiux/design-standard.md`、`docs/product/user-personas.md`。
> 本页只约束前端呈现与交互，不改变设置 API、schema、wire contract、数据语义或 `novel_id` 隔离。

## 1. 页面定位

- `/#settings` 服务作者的低频账户任务：连接 AI 文本服务、按需连接图片服务、修改通用创作偏好。
- `/#workbench/:id/project-settings` 服务当前作品：覆盖创作偏好、调整高级导入参数。
- RP 补连接入口只显示连接任务，成功后返回原旅程位置，不展示作者偏好或作品范围切换。
- 产品价值仍是待真实作者验证的假设：作者应能快速确认当前服务、放心保存设置，并在离开后可靠恢复。

## 2. 当前信息层级

设置外壳只有一个页面标题，并以正常路由提供范围切换：

```text
账户设置
├─ AI 文本服务（主任务）
├─ 图片生成连接（默认折叠，按需展开）
└─ 通用创作偏好

当前作品设置
├─ 创作偏好（默认页签）
└─ 高级导入（专家页签，内部按作者问题折叠）
```

- 范围切换使用 `aria-current="page"`，不是页内 tab；刷新、前进、后退和项目切换必须恢复正确页面。
- “创作偏好 / 高级导入”才是同一页面内的 tab，保持 `tablist`、`tab`、`tabpanel` 和方向键、Home/End 契约。
- 不重复显示页面标题、当前作品入口或相同能力按钮。

## 3. 已落地的交互契约

### 3.1 加载与失败

- 账户连接、通用偏好、图片连接、项目偏好加载失败时显示贴近区域的 `role="alert"` 错误和“重新加载”。
- 加载失败不能伪装成空列表，也不能永久停在“加载中”。未知基线未恢复前不显示可覆盖服务端设置的表单。
- 正常主流程不得产生浏览器控制台 error 或 5xx 请求。

### 3.2 编辑与保存

- 空 Key、日更目标越界和高级导入越界在字段旁持续显示错误，控件设置 `aria-invalid` 并获得焦点；toast 只能作辅助反馈。
- 操作区持续显示“有未保存修改 / 保存中 / 已保存 / 保存失败”。保存失败保留输入。
- 两页有未保存输入时都拦截路由离开、项目切换和窗口关闭。切换文本服务导致已输入 Key 丢失前必须确认。
- 项目设置写入成功但二次读取失败时，明确区分“已保存”和“暂时无法重新读取”，不能把成功提交误报为失败。
- 清除 Key、恢复整组默认等危险操作继续二次确认。

### 3.3 用户语言与安全边界

- 主界面不展示 provider 内部配置、raw ID、JSON、token、Prompt 或数据库枚举。
- API Key 使用密码输入，不回显、复制或展示尾号；界面只呈现连接状态。Key 仍由服务端账户连接保存。
- 项目页不提供项目级 provider、model 或 Key，只提供进入账户连接的入口。
- 作者偏好显示中文字体和布尔状态，但保存、传输和存储继续使用稳定底层值。
- 高级导入只改显示文案和分组，不改任何请求 key。

## 4. 视觉与响应式

- 页面使用扁平分区和 hairline 分隔，避免卡片套卡片；主任务优先，图片连接与高级导入渐进展开。
- 字段顺序为 label → control → helper/error；错误与说明占同一信息层级，不靠 placeholder 传达持久状态。
- 桌面作者偏好可三栏；`760px` 以下单栏。设置范围和页签在窄屏换行，不依赖横向滚动。
- 390×844 必须无文档横向溢出；可见设置按钮高度至少 42px；顶栏三段不能重叠。
- 三主题视觉基线覆盖账户页、项目页、两个项目页签及 390px 账户/项目页面。

## 5. 稳定锚点

- 账户：`#account-llm-api-key`、`#account-llm-save`、`#account-llm-clear`、`#account-balance-refresh`、`#global-author-save`。
- 作者偏好：`#author-daily-goal`、`#author-editor-font`、`#author-default-focus`。
- 项目：`#project-settings-empty-goto-account`、`#project-settings-goto-global`、`#project-settings-tab-author`、`#project-settings-tab-deep`、`#project-settings-tab-panel`、`#deep-import-tab-save`、`#deep-import-tab-reset-all`、`#author-prefs-tab-save`。
- 深度导入字段继续使用 `deep-import-{group}-{key}`；模型卡继续使用 `data-provider-id`。
- 调整可访问名称或上述锚点时必须同步 Vitest、功能 E2E 和视觉 E2E。

## 6. 尚未处理

- 主题切换器仍横跨组件样式、结构样式和主题覆层，后续触及顶栏主题体验时应收敛单一视觉所有者。
- 设置 E2E 选择器仍分散在 spec；只有出现跨文件重复维护成本时才集中到 selectors helper。
- 保存冲突目前沿用后端错误语义；没有 revision/CAS 契约，不在纯前端任务中虚构并发能力。

## 7. 验证

```bash
cd frontend-console
npm test
npm run build
npx playwright test e2e/settings_flow.spec.js
npx playwright test -c playwright.visual.config.js e2e/visual-settings.spec.js
```

浏览器回归必须覆盖：正常进入、加载失败重试、字段校验、保存、刷新、前进/后退、项目切换、未保存确认、RP 返回、桌面与 390px、控制台和 5xx 请求。

收尾运行 `make docs-check BASE_REF=origin/main`。
