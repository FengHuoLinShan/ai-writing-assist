# Round 12/20 — i18n / Accessibility / Responsive / Cross-Browser

**Status**: PASS  
**Goal**: 国际化、可访问性深度、响应式/移动端、跨浏览器兼容  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 国际化 (i18n) | ~500 | 架构缺失 | — | — | — |
| 可访问性 (a11y) | 22 | 0 | 7 | 10 | 5 |
| 响应式与移动端 | ~8 | 0 | 1 | 2 | ~5 |
| 跨浏览器兼容 | ~12 | 2 | 2 | 4 | ~4 |
| **合计** | **~542** | **2** | **10** | **16** | **~14** |

---

## 国际化 — 成熟度 0/10（架构级缺失）

**项目完全以简体中文设计，未考虑多语言，当前架构无 i18n 基础设施**

🔴 无 i18n 框架、无 `locales/` 目录、无语言配置文件、`<html lang="zh-CN">` 硬编码
🔴 全部前端 UI 文本硬编码中文（~450+ 处，遍布 44+ 视图文件和模板）
🔴 后端错误消息硬编码中文（~30 处 `DomainError("中文消息")`），无错误码系统
🟡 11 处日期格式化硬编码 `"zh-CN"` locale 参数而非浏览器默认
🟡 CSS 物理属性（`margin-left`/`padding-right` 等 ~120+ 处）无 RTL 逻辑属性替代
✅ 唯一可用的多语言暗示：`Project.language` 字段（用于 LLM 提示中的语言约束）

**预估修复**: 10-15 天，60% 为字符串提取体力活，建议路线：i18next → 共享 UI 字符串 → 按模块迁移 → 错误码系统 → CSS 逻辑属性

---

## 可访问性 (a11y) — 22 个发现（7 HIGH + 10 MEDIUM + 5 LOW）

### Top 3
🔴 **模态框 ARIA 三重缺失**（`index.html:165` + `modal.js`）：无 `role="dialog"`、`aria-modal="true"`、`aria-labelledby`；打开无焦点陷阱、关闭无焦点恢复
🔴 **侧栏导航键盘不可达**（`index.html:53-127`）：`<li>` 元素有 click 但无 `tabindex`、无 `role="button"`、无键盘事件 → Tab 键完全跳过主导航
🔴 **三级文本对比度失败**（`styles.css:21,153,281`）：`--text-tertiary` 默认/深色/暖色主题分别为 2.6:1、3.5:1、4.1:1（需 AA 4.5:1），影响 9px `.nav-label`、提示文本等
🟡 编辑器 `<textarea>` 和 `<input>` 无 `aria-label`；`<h1>` 缺失；导航项无 `aria-current`
🟡 `outline: none` 在多处移除焦点指示器；`prefers-reduced-motion` 覆盖不完整

---

## 响应式与移动端 — ~8 个发现（1 HIGH + 2 MEDIUM）

**总体架构意识良好**：完整的断点体系（1100/900/760/720/640/600px）、`clamp()`/`minmax()` 技术到位、表格和 rails 折叠策略合理、存在 `mobileQuickNote` 子模块和 E2E 响应式测试

🔴 **触屏 hover 失效**（`styles.css` 多处）：tooltip、操作菜单、装饰效果纯 `:hover`，无 `@media (hover)`/`@media (pointer)` 降级 → 触屏设备卡死粘滞 hover
🟡 模态框手机无全屏适配（固定 560px、`max-width:90vw`）
🟡 窄屏侧栏无覆盖层模式（仅缩至 48px，占 ~12% 屏幕宽度），无汉堡菜单

---

## 跨浏览器兼容 — ~12 个发现（2 CRITICAL + 2 HIGH）

🔴 **CRITICAL**: `state.js:103` 的 `Proxy` 无 fallback — IE11/旧 WebView 应用完全不可用
🔴 **CRITICAL**: 无构建 transpilation — `vite.config.js` 无 `build.target`，无 Babel，无 browserslist；可选链/空值合并 200+ 处、ES Modules 未降级
🟠 HIGH: CSS `:has()`(19处) + `color-mix()`(14处) 无降级 — Firefox < 121 布局错乱
🟠 HIGH: `backdrop-filter` 无 `-webkit-` 前缀；`appearance: none` 无 `-moz-appearance`
🟡 零 polyfill、无 autoprefixer、无 `@supports` 特性检测、Playwright 仅跑 chromium
🟡 `-webkit-overflow-scrolling: touch` 已 deprecated
