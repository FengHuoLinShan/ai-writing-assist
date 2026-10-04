# 世界对象游戏化卡片设计 Spec

**状态**：设计定稿  
**关联模块**：`frontend-console/views/worldView.js`、`backend/modules/world`  
**设计目标**：为全部世界对象类型提供受 D&D / Baldur's Gate 3 启发的游戏化卡片 UI，直接使用后端结构化数据，零外部图库依赖。

---

## 1. 设计参考

| 参考 | 可借鉴元素 |
|------|-----------|
| D&D 5e 法术/物品卡 | 顶部类型色带、图标勋章、属性条、风味文本、稀有度颜色 |
| Baldur's Gate 3 提示卡 | 左侧动作图标、标签云、关键数值徽章、暗色羊皮纸纹理 |
| 万智牌（MTG） | 类型行、分隔线、底部信息栏、稀有度符号位置 |

核心借鉴点：
- **类型色带** + **图标勋章** 让玩家 1 秒识别卡片类别。
- **稀有度/重要度徽章** 用颜色映射信息优先级。
- **属性条** 把后端字段转成可视化数值/标签。
- **隐藏区封印** 区分作者视角与公开信息，防止剧透。

---

## 2. 数据资产清单

### 2.1 公共字段（所有卡片）
来自 `CoreEntity` / `CoreEntityResponse`：

| 字段 | 用途 |
|------|------|
| `name` | 卡片主标题 |
| `entity_type` | 类型判定、图标、色带 |
| `summary` | 公开描述（风味文本） |
| `public_info` | `summary` 为空时作为备选 |
| `importance` / `importance_level` | 稀有度/重要度徽章 |
| `reveal_level` | 隐藏区可见性控制 |
| `status` | 状态徽章（正史/草稿/候选/废弃/已合并） |
| `source` | 来源标签（手动 / AI 生成 / 深度导入） |
| `content_json.aliases` | 别名云 |
| `content_json.image_url` | 可选卡片插画（背景图） |

### 2.2 作者专属字段（封印区）
仅在作者安全模式下展开：

| 字段 | 来源 |
|------|------|
| `hidden_truth` | `CoreEntity` |
| `secret` | `Character` / `SecretProfile` |
| `risk_level` | `SecretProfile` |
| `reveal_status` | `SecretProfile` |
| `weakness` | `Character` |
| `fear` | `Character` |

### 2.3 类型专属字段

#### character / characters 表
`role`, `appearance`, `personality`, `desire`, `fear`, `secret`, `weakness`, `current_goal`, `current_state`, `current_emotion`, `stance`, `voice_style`, `behavior_rules`, `relationship_summary`

#### creature（无单独表，用 CoreEntity + 可能 SpeciesProfile）
`origin_summary`, `physiology_summary`, `lifespan`, `abilities_json`, `weaknesses_json`, `culture_summary`, `language_summary`

#### location / location_profiles
`climate`, `population_summary`, `resources_json`, `hazards_json`, `controlling_faction_ids_json`

#### faction / faction_profiles
`ideology_summary`, `leader_entity_ids_json`, `member_rules`, `territory_refs_json`, `resources_json`

#### item / item_profiles
`item_class`, `powers_json`, `limitations_json`, `owner_entity_ids_json`, `origin_summary`

#### event / events 表
`occurrence_time_label`, `timeline_order`, `location_entity_id`

#### rule / rule_profiles
`rule_domain`, `principle_summary`, `constraints_json`, `exceptions_json`, `consequences_json`

#### power_system（无单独表，用 CoreEntity + 可能 generic/profile）
依赖 `data_json` / `powers_json`

#### secret / secret_profiles
`truth_summary`, `holder_entity_ids_json`, `risk_level`, `reveal_status`, `linked_target_refs_json`

#### legend / resource / concept / skill / other
依赖 `summary`、`content_json`、`genericEntityProfile.data_json`。

---

## 3. 卡片解剖

```
┌─────────────────────────────────────────┐  ← 4px 类型色带
│ [icon]  名称           [稀有度] [状态]  │  ← 标题行
│ 类型标签                                │
├─────────────────────────────────────────┤
│                                         │
│           插画区 / 默认纹理              │  ← 高度 96px
│                                         │
├─────────────────────────────────────────┤
│ 属性1  属性2  属性3  属性4              │  ← 属性条
├─────────────────────────────────────────┤
│ 摘要 / 风味文本（2-3 行截断）            │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ 🔒 隐藏真相（作者视角）              │ │  ← 封印区
│ └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│ 来源 · 复核 · 关系数                    │  ← 元信息栏
├─────────────────────────────────────────┤
│ [复核] [编辑] [地图] [⋯]               │  ← 操作栏
└─────────────────────────────────────────┘
```

### 3.1 各区域规范

#### 类型色带
- 高度 4px，圆角上方继承卡片圆角。
- 颜色见「类型视觉映射」。

#### 图标勋章
- 40×40px，圆形，白色或半透明背景，类型色填充图标。
- 图标内嵌 SVG path，不使用图片文件。

#### 稀有度徽章
- 右上角 16px 菱形/星形。
- 颜色映射：
  - `core` → 传说橙 `#F59E0B`
  - `important` → 史诗紫 `#8B5CF6`
  - `normal` → 稀有蓝 `#3B82F6`
  - `temporary` → 普通灰 `#9CA3AF`

#### 插画区
- 默认：CSS `linear-gradient` + 伪元素类型纹理。
- 自定义：`content_json.image_url` 作为背景图，失败回退默认纹理。
- 必须覆盖暗色/纸张主题。

#### 摘要
- 最多 3 行，超出省略。
- 优先 `summary`，其次 `public_info`，最后「暂无描述」。

#### 封印区
- 默认折叠，显示「🔒 隐藏真相」按钮。
- 点击展开，背景使用半透明暗色或羊皮纸纹理。
- 仅在 `reveal_level` 为 `author_only` 或存在 `hidden_truth`/`secret` 时显示。

---

## 4. 类型视觉映射

| entity_type | 中文标签 | 色带 | 图标 | 默认纹理 | 属性条 |
|-------------|----------|------|------|----------|--------|
| character | 人物 | `#6366F1` 靛蓝 | 面具/头像 | 柔光圆斑 | role、current_emotion、stance |
| creature | 生物/怪物 | `#DC2626` 暗红 | 爪痕 | 齿状撕裂 | abilities 数、weaknesses 数、lifespan |
| location | 地点 | `#16A34A` 森林绿 | 地标 | 六边形网格 | climate、population_summary、hazards 数 |
| faction | 组织/势力 | `#D97706` 金色 | 旗帜 | 纹章菱形 | ideology_summary、leader 数、territory 数 |
| item | 物品 | `#9333EA` 紫晶 | 宝箱 | 魔法光晕 | item_class、powers 数、limitations 数 |
| event | 事件 | `#EA580C` 橙色 | 火焰/时钟 | 时间线波纹 | occurrence_time_label、timeline_order、location |
| rule | 规则 | `#475569` 青灰 | 天平 | 符文线条 | rule_domain、constraints 数、exceptions 数 |
| power_system | 能力体系 | `#2563EB` 电蓝 | 闪电 | 能量流动 | powers 数、principle_summary |
| secret | 秘密 | `#7C3AED` 暗紫 | 锁 | 锁链纹样 | risk_level、reveal_status、holder 数 |
| legend | 传说 | `#92400E` 古铜 | 书卷 | 羊皮纸 | 摘要关键词 |
| resource | 资源 | `#B45309` 土黄 | 麦穗/矿石 | 自然纹理 | 资源关键词 |
| concept | 概念 | `#64748B` 银白 | 思想泡泡 | 几何网格 | 概念关键词 |
| skill | 技能 | `#DC2626` 红 | 剑/符文 | 动作光效 | 技能关键词 |
| other / generic | 其他 | `#6B7280` 灰 | 问号 | 简洁渐变 | 通用关键词 |

---

## 5. 图标资产

图标统一使用 24×24 viewBox 的 SVG path，存储于 `frontend-console/shared/worldObjectIcons.js`。

```js
const ICONS = {
  character: "M12 12c2.2 0 4-1.8 4-4s-1.8-4-4-4-4 1.8-4 4 1.8 4 4 4zm0 2c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4z",
  creature:  "M4 4l5 6-5 6M12 4l5 6-5 6M20 4l-3 6 3 6",
  location:  "M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5c-1.4 0-2.5-1.1-2.5-2.5s1.1-2.5 2.5-2.5 2.5 1.1 2.5 2.5-1.1 2.5-2.5 2.5z",
  faction:   "M4 4h16v2H4zm0 4h12v2H4zm0 4h16v2H4zm0 4h10v2H4z",
  item:      "M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6-4.8-6 4.8 2.4-7.2-6-4.8h7.6z",
  event:     "M12 2a10 10 0 100 20 10 10 0 000-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z",
  rule:      "M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm-1 15h2v2h-2v-2zm0-10h2v8h-2V7z",
  power_system: "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  secret:    "M12 2C9 2 6.5 4.5 6 7.5C4.5 8.5 3.5 10.5 3.5 13c0 3.5 3 6.5 7 6.5h1c4 0 7-3 7-6.5 0-2.5-1-4.5-2.5-5.5C15.5 4.5 15 2 12 2zm0 10c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z",
  legend:    "M6 2h12v2H6zm0 4h12v16l-6-4-6 4V6z",
  resource:  "M12 2l-8 6h3v10h10V8h3L12 2z",
  concept:   "M12 2a7 7 0 100 14 7 7 0 000-14zm0 12a5 5 0 110-10 5 5 0 010 10z M21 6a2 2 0 110 4 2 2 0 010-4z",
  skill:     "M7 21l-2-2 4-4L3 9l2-2 6 6 6-6 2 2-6 6 6 6-2 2-6-6-6 6z",
  other:     "M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm0 16c-.6 0-1-.4-1-1s.4-1 1-1 1 .4 1 1-.4 1-1 1zm1-5h-2V7h2v6z",
}
```

> 实际实现时可简化 path 以减小体积，并确保描边/填充统一。

---

## 6. 主题适配

| 主题 | 卡片背景 | 文字 | 边框 | 封印区背景 |
|------|----------|------|------|------------|
| light | `#FFFFFF` | `#334155` | `#E2E8F0` | `rgba(15,23,42,0.04)` |
| dark | `#1E293B` | `#E2E8F0` | `#334155` | `rgba(0,0,0,0.25)` |
| paper | `#FAF8F3` | `#3D3D3D` | `#DCD7CE` | `rgba(139,90,43,0.08)` |

类型色带颜色在不同主题下保持色相，只调整饱和度/亮度以保证可读。

---

## 7. 可选插画策略

1. **默认**：CSS 纹理，无网络请求。
2. **用户图片**：读取 `content_json.image_url`，作为 `.card-art` 的 `background-image`。
3. **生成图片（未来扩展）**：后端任务根据 `name` + `entity_type` 生成并写入 `image_url`；前端无需改动。

前端图片处理要求：
- URL 必须经 `esc()` 输出。
- 设置 `onerror` 回退到默认纹理。
- 不将外部 URL 作为 `innerHTML` 拼接。

---

## 8. 分类卡片与导航交互

### 8.1 分类卡片设计

分类卡片是世界对象库的一级入口，每张卡片代表一个 `entity_type`：

| 元素 | 规范 |
|------|------|
| 尺寸 | 约 160px × 120px，圆角 12px |
| 色带 | 顶部 6px 类型色带，悬停时加宽至 10px |
| 图标 | 居中 24px SVG 图标，置于 42px 圆形勋章内 |
| 名称 | 14px 中文类型名，加粗 |
| 说明 | 11px 一句话描述该类型用途 |
| 数量徽章 | 该类型下实体数量 |

### 8.2 筛选模式

- 分类卡片横向排列在页面顶部。
- 点击分类卡片后，下方实体卡片网格实时过滤为对应类型。
- 「全部」卡片用于重置筛选，默认展示全部对象。

适用场景：对象库管理页，需要快速浏览和批量操作。

### 8.3 图鉴模式

- 分类卡片作为首页唯一内容，默认不展示详细对象。
- 点击分类卡片后进入该类型专区，显示该类型的实体卡片。
- 专区顶部显示类型图标、名称、描述、数量与「返回图鉴首页」按钮。

适用场景：更像游戏内图鉴/卡片册的沉浸式浏览。

### 8.4 模式决策

**不在同一份界面中做「筛选/图鉴」切换按钮**，而是将两种交互实现为两份独立视图/路由：

- `world-card-mockup-filter.html`：筛选模式样例
- `world-card-mockup-gallery.html`：图鉴模式样例

正式实现时可根据页面上下文选择其中一种，或分别作为 `/world` 下的「对象库」与「世界图鉴」两个子视图。

## 9. 静态样例

已提供三份可浏览器直接打开的样例：

1. `frontend-console/prototypes/world-card-mockup.html`：综合样例，包含完整卡片与主题切换。
2. `frontend-console/prototypes/world-card-mockup-filter.html`：筛选模式，顶部分类卡片 + 下方可过滤实体网格。
3. `frontend-console/prototypes/world-card-mockup-gallery.html`：图鉴模式，分类卡片作为首页，点击进入类型专区。

样例使用虚拟数据展示色带、图标、属性条、封印区、分类卡片与暗色切换。

---

## 10. 实现接口

### 10.1 新增文件
- `frontend-console/shared/worldObjectIcons.js` — 图标映射。
- `frontend-console/shared/worldObjectCard.js` — 实体卡片渲染函数。
- `frontend-console/shared/worldObjectCategory.js`（可选）— 分类卡片渲染函数。
- `frontend-console/prototypes/world-card-mockup.html` — 综合设计样例。
- `frontend-console/prototypes/world-card-mockup-filter.html` — 筛选模式样例。
- `frontend-console/prototypes/world-card-mockup-gallery.html` — 图鉴模式样例。
- `frontend-console/tests/worldObjectCard.test.js` — 渲染测试。

### 10.2 修改文件
- `frontend-console/views/worldView.js`
  - `_renderEntityCard` 调用 `renderWorldObjectCard(entity, profile)`。
  - 可选在列表接口附带 `profile_kind` 或按需 fetch `/world/profiles/{entity_id}`。
- `frontend-console/styles.css`
  - 新增 `.world-object-card--gamified` 及变体。
  - 新增 `.world-object-category-card` 及变体。
  - 保留旧 `.world-object-card` 样式作为回退。

### 10.3 函数签名
```js
// shared/worldObjectCard.js
export function renderWorldObjectCard(entity, options = {})
// options: { profile, showActions, onAction, revealMode }

// shared/worldObjectCategory.js
export function renderWorldObjectCategoryCard(type, count, options = {})
// options: { active, layout: "compact" | "hero" }
```

---

## 11. 验收标准

- [ ] 全部 14 种核心类型 + 7 种强类型档案都有对应卡片模板。
- [ ] 动态文本经 `esc()` 转义，无 `innerHTML` 注入。
- [ ] 暗色/纸张主题下卡片可读、色带不刺眼。
- [ ] `worldView.test.js` 与新增 `worldObjectCard.test.js` 通过。
- [ ] `make lint` 无新增告警。

---

## 12. 未决问题

1. 是否允许在世界对象列表接口中一次性返回 `profile_kind` + `profile_fields` 以减少请求？
2. 是否需要在卡片上显示实体关系数量？当前 API 需单独查询关系列表。
3. 是否提供「旧版简洁卡片」切换？建议保留以降低用户学习成本。
