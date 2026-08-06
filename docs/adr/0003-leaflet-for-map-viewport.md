# ADR-0003 — 动态地图视口引擎选用 Leaflet 1.9.4

- **状态**: Accepted
- **日期**: 2026-06-14
- **交付修订**: 2026-08-06（固定 npm 依赖与本源静态资产取代 CDN）
- **背景**: 动态地图功能 PRD v1.1（[`map-prd-v1.1.md`](../references/map-prd-v1.1.md)）

## 背景与问题

动态地图功能需要一个支持平移、缩放、坐标换算、视口裁剪的 2D 视口引擎来承载六边形网格与多个业务图层。

当前前端由 Vite 构建 Vue 3 SFC，并保留 `mapView` 作为 Leaflet/Canvas 窄命令式 seam。
在此约束下，视口引擎有两条路：

1. **自研**：用 Canvas 2D 自行实现平移、缩放、屏幕↔世界坐标换算、视口裁剪、命中测试。
2. **引入成熟库**：Leaflet / OpenLayers / d3-zoom + 自绘等。

## 决策

引入 **Leaflet 1.9.4** 作为地图视口引擎，以锁定的 npm 生产依赖构建并由应用本源按需交付。

### 1. 选 Leaflet 而非自研

**理由**：
- 自研平移/缩放/坐标换算/视口裁剪/惯性滚动/触摸手势是一套约 600-1000 行的基础设施，与业务无关，且容易在边界条件（极小/极大缩放、抖动、resize）上踩坑。
- Leaflet 的稳定 API 与约 150KB 运行时避免重复实现通用视口基础设施。
- 自研收益（"零依赖"原则的纯洁性）小于工程成本（作者要的是地图功能，不是地图引擎）。

### 2. 选 Leaflet 而非 OpenLayers / d3-zoom

- OpenLayers 体积更大（~600KB），GIS 能力溢出本需求。
- d3-zoom 只提供手势，仍需自绘图层管理与坐标换算，未消除核心成本。
- Leaflet 的 `L.Map` + `L.LayerGroup` + Canvas overlay 正好契合本功能的"视口 + 自定义图层"模型。

### 3. 锁定 npm 依赖并自托管，而非运行时 CDN

加载方式：
```js
// frontend-console/views/leafletLoader.js
const [leafletModule] = await Promise.all([
  import("leaflet"),
  import("leaflet/dist/leaflet.css"),
])
```

**理由**：
- `package.json` 与 lockfile 精确固定 `leaflet@1.9.4`，不接受 `latest`，安装与生产镜像继续走既有锁文件门禁。
- Vite dynamic import 生成独立 JS/CSS chunk；只有地图视口首次进入时请求，非地图页面不下载。
- 浏览器只访问应用本源，不依赖 unpkg 可用性，也不需要 `window.L`、运行时 `<script>/<link>` 注入或 SRI 例外。
- 加载 Promise 在成功和进行中复用；失败后清除并允许作者原位重试，世界/写作等其他页面不受影响。
- 构建把 Leaflet BSD-2-Clause 许可复制到 `/licenses/leaflet-BSD-2-Clause.txt`，生产资产验证同时阻止 `unpkg.com` 回归并检查 CSS/许可存在。

### 4. Leaflet 的使用边界

Leaflet **只做视口引擎**（平移/缩放/手势/坐标换算）。六边形业务图层（地形、地点绑定、标记、势力范围）**全部自研 Canvas 叠加层**，通过 Leaflet 的 `L.LayerGroup` 或 Canvas overlay 挂载，不使用 Leaflet 的 `L.Polygon` 来画每一个六边形（600-2700 个 DOM 元素会拖垮性能）。

### 5. 不引入其他前端依赖

Leaflet 是地图视口的直接前端运行时依赖。后续若需要其他库（如图标库、动画库），需另起 ADR。

## 影响

- `script-src` 仅允许 `'self'`；`style-src` 不再允许外部 origin，仍暂保留既有 `'unsafe-inline'` 兼容。
- `frontend-console/views/leafletLoader.js` 拥有按需加载与 retry cache，`mapView.js` 只消费模块 API，不创建浏览器全局。
- `THIRD_PARTY_LICENSES.md` 记录直接运行时依赖，生产构建包含 Leaflet 原始许可。
- 地图资源失败时显示作者可读提示和原位重试，其他页面不受影响；API、schema、wire、地图状态机和核心交互不变。

## 备选方案（拒绝）

### A. 自研 vanilla Canvas 视口

**拒绝理由**：见决策 §1。成本高、收益低、边界条件多。

### B. 运行时 CDN

**拒绝理由**：第三方可用性会直接决定地图能否打开，并迫使 CSP 保留外部脚本/样式来源。
固定版本与 SRI 只能约束内容，不能消除外部网络依赖。

### C. 将压缩 Leaflet 文件直接提交到 git

**拒绝理由**：lockfile + Vite 已能生成可缓存的本源资产并保留依赖来源，不需要维护一份难以审查的 vendor 副本。

### D. OpenLayers

**拒绝理由**：见决策 §2。体积过大，GIS 能力溢出。

### E. 等地图功能验证后再补 ADR

**拒绝理由**：AGENTS.md §2.2 要求"未经用户明确要求或 ADR，不引入新的运行时基础设施"。Leaflet 是运行时依赖，必须先有 ADR。
