# ADR-0003 — 动态地图视口引擎选用 Leaflet 1.9.4

- **状态**: Accepted
- **日期**: 2026-06-14
- **背景**: 动态地图功能 PRD v1.1（`docs/PRD-动态地图功能.md`）

## 背景与问题

动态地图功能需要一个支持平移、缩放、坐标换算、视口裁剪的 2D 视口引擎来承载六边形网格与多个业务图层。

此前端项目（`frontend-console/`）是零外部依赖的 vanilla JS SPA，README 明确声明"零外部依赖"，`index.html` 中所有 `<script>` 均为本地相对路径，`package.json` 仅 devDependencies（vitest / happy-dom / playwright）。在此约束下，视口引擎有两条路：

1. **自研**：用 Canvas 2D 自行实现平移、缩放、屏幕↔世界坐标换算、视口裁剪、命中测试。
2. **引入成熟库**：Leaflet / OpenLayers / d3-zoom + 自绘等。

## 决策

引入 **Leaflet 1.9.4** 作为地图视口引擎，通过 CDN 加载。

### 1. 选 Leaflet 而非自研

**理由**：
- 自研平移/缩放/坐标换算/视口裁剪/惯性滚动/触摸手势是一套约 600-1000 行的基础设施，与业务无关，且容易在边界条件（极小/极大缩放、抖动、resize）上踩坑。
- Leaflet 是该领域事实标准，体积 ~150KB（gzip ~42KB），API 稳定 10 年以上，CDN 可用性高。
- 自研收益（"零依赖"原则的纯洁性）小于工程成本（作者要的是地图功能，不是地图引擎）。

### 2. 选 Leaflet 而非 OpenLayers / d3-zoom

- OpenLayers 体积更大（~600KB），GIS 能力溢出本需求。
- d3-zoom 只提供手势，仍需自绘图层管理与坐标换算，未消除核心成本。
- Leaflet 的 `L.Map` + `L.LayerGroup` + Canvas overlay 正好契合本功能的"视口 + 自定义图层"模型。

### 3. CDN 加载而非 vendor 本地化

加载方式：
```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

**理由**：
- 版本写死（`@1.9.4`），无 supply chain 风险扩散（不接受 `@latest`）。
- vendor 本地化需要把 ~150KB 的压缩 JS 纳入 git，与项目"源码即文档、依赖靠 CDN"的当前风格不一致（项目无 node_modules 构建产物入库）。
- 降级策略：若 unpkg 不可达，地图子视图显示"地图引擎加载失败，请检查网络"提示，不影响 world 其他子视图（objects/relations/aliases）正常工作。

### 4. Leaflet 的使用边界

Leaflet **只做视口引擎**（平移/缩放/手势/坐标换算）。六边形业务图层（地形、地点绑定、标记、势力范围）**全部自研 Canvas 叠加层**，通过 Leaflet 的 `L.LayerGroup` 或 Canvas overlay 挂载，不使用 Leaflet 的 `L.Polygon` 来画每一个六边形（600-2700 个 DOM 元素会拖垮性能）。

### 5. 不引入其他前端依赖

Leaflet 是本功能唯一新增前端依赖。后续若需要其他库（如图标库、动画库），需另起 ADR。

## 影响

- `frontend-console/index.html` 新增 1 个 `<link>` + 1 个 `<script>`（CDN）。
- `frontend-console/views/mapView.js` 等模块通过全局 `window.L` 访问 Leaflet。
- 项目 README 的"零外部依赖"声明需更新为"零构建依赖、零 node_modules 运行时依赖；地图视图通过 CDN 加载 Leaflet"。
- 地图子视图在网络不可用时降级，world 其他子视图不受影响。

## 备选方案（拒绝）

### A. 自研 vanilla Canvas 视口

**拒绝理由**：见决策 §1。成本高、收益低、边界条件多。

### B. vendor 本地化 Leaflet

**拒绝理由**：见决策 §3。与项目风格不一致，git 仓库膨胀。

### C. OpenLayers

**拒绝理由**：见决策 §2。体积过大，GIS 能力溢出。

### D. 等地图功能验证后再补 ADR

**拒绝理由**：AGENTS.md §2.2 要求"未经用户明确要求或 ADR，不引入新的运行时基础设施"。Leaflet 是运行时依赖，必须先有 ADR。
