# 原生 Figma 重建插件

状态：代码已提供，本轮因 Figma MCP 额度限制未在 Figma 中执行。不能把离线测试当成原生运行通过。

## 使用

在 Figma Design 的开发插件入口创建一个带 UI 的本地插件，由 Figma 生成真实 `id` 和 `manifest.json`。将本目录 `code.js`、`ui.html` 放入该插件文件夹；把 `manifest.template.json` 的字段合并到它生成的 manifest 中，保留 Figma 分配的 `id`。不要编造插件 ID。然后在开发插件菜单运行。

首次建议选择“核心流程”。执行会新建一个页面，不修改现有页面。再次执行会再新建页面，不自动覆盖或删除旧稿；停止会保留已经创建的内容。选择全部将建立 49 个画板和本地组件/变量，耗时取决于 Figma 环境。

无需模型 Key，不访问网络，不含真实小说或账号数据，不包含字体文件。优先使用 Noto Sans SC / Noto Serif SC；环境缺字体时回退并报告。回退后要核对字宽与溢出。

## 可编辑性

文本为原生 text；容器为 frame；插画是矢量路径而非整页截图；按钮和状态使用本地组件实例及 Auto Layout；语义颜色绑定本地 variables。大屏页面是固定 HiFi 排布，响应式参考独立手机画板，不声称整个页面已做生产级 Auto Layout。

同一范围内的热点尝试创建原型连线；指向未导入画面的热点不会连接。连线失败会记录，不伪报成功。主文件 `design.json` 和 SVG 是一致的离线基线。

## 核对

核对 DS00、S06、S09、S20、S33、S37 的中文字体和画板边界；地图侧栏不遮挡关键标签；手机 sheet 不压住正文；实例文字保持居中；“永久删除”等按钮仅连接设计画面，不执行业务。

官方 manifest 说明：https://developers.figma.com/docs/plugins/manifest/
