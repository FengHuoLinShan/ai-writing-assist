# 前端 UI/UX 规范入口

全站默认使用现代简约，支持浅色、深色、跟随系统和本浏览器主题资源包。

## 当前权威

- [用户画像与体验准则](../../product/user-personas.md)
- [设计标准](design-standard.md)：全站视觉、组件、响应式与保护要求
- [主题包规范](theme-packages.md)：外部配置与资源接口
- [ADR-0019](../../adr/0019-local-theme-resource-packages.md)：新设计与本地资源存储边界
- [前端模块](../../modules/14_frontend.md)：生产入口、稳定接口和状态恢复

## 页面验收

[写作](pages/writing.md) · [人物与世界](pages/world.md) · [写作首页](pages/today.md) ·
[故事结构](pages/outline-scene.md) · [查找](pages/rag.md) · [AI 工具](pages/generate.md) ·
[设置](pages/settings.md) · [作品](pages/project.md) · [互动故事](pages/rp-experience.md) · [地图](pages/map.md)

页面规范保留领域操作与恢复约束；旧三主题和纯视觉修复批次的像素示意由新设计标准取代。所有共享视觉从语义变量消费，不允许为单页建立第二套色板。复用既有菜单、模态、保存与会话实现。

## 覆盖要求

验证生产可达页面、子页、入口、弹窗、抽屉、批量操作、认证与恢复，不能仅看路由截图。
首次、正常、空态、加载、失败／冲突、保存、离开恢复和误操作保护都在覆盖范围。
作者与互动故事保持不同任务层级；一处决定一个主操作，诊断入口次级呈现。

开发服务器的 `/prototypes/design-system.html` 是组件展示页；从设置 → 外观可导入真实资源示例。

## 重设计覆盖记录（2026-09-07）

| 用户区域 | 覆盖内容 | 主要验证 |
|---|---|---|
| 公共入口、认证与账号 | 双入口、登录／恢复、账户弹窗、主题恢复提示 | home、auth、Shell/Auth 单测；入口与认证视觉基线 |
| 作品与导入 | 作品卡、搜索、管理、导入抽屉、失败恢复、回收站 | project、import、project-recycle-bin 与项目视觉基线 |
| 写作与计划 | 首页、计划、正文、统一手机编辑器、章节／资料抽屉、版本、候选与保存保护 | author-workspace、writing、themes 与写作视觉基线 |
| 人物与世界 | 资料库、资料页、对象、别名、关系、待处理决策、来源与历史 | world、world-bible、world-objects、world-review 与视觉基线 |
| 故事结构 | 总览、篇章、剧情线、场景、编辑与批量操作 | outline-scenes、outline-threads-arcs、scene-workbench 与视觉基线 |
| AI 工具 | 就地工具抽屉、参考资料确认、建议、失败与返修 | generate、writing、AI 参考资料与建议视觉基线 |
| 查找与维护 | 查询、更多条件、来源抽屉、范围修复与恢复 | rag 功能与视觉基线 |
| 地图 | 首次进入、画廊、候选审核、上传、来源与手机限制 | map-atlas 功能；桌面／手机浅深色首次进入基线 |
| 互动故事 | 旅程列表、开场、阅读、输入、分支、回顾、来源与设置返回 | interaction 功能；旅程与阅读浅深色视觉基线 |
| 设置与外观 | 账户连接、作品偏好、主题预览／导入／导出／删除、持久化失败 | settings、themes、主题校验单测及外观视觉基线 |
| 共享组件 | 导航、菜单、表单、模态、空态、通知、进度与可访问性 | 组件与 CSS 契约单测、全站功能回归、组件展示页 |

作者收益假设：正文空间更集中，手机无需切换两套编辑器，查资料不打断编辑会话。
读者收益假设：保留纯故事路径并共享舒适外观，进入设置后能回到原故事。
主要风险是旧习惯迁移、主题资源与动态重排；通过旧偏好迁移、声明式资源边界、焦点／草稿保护和窄屏验收控制。
尚未进行真实作者／读者的长期试用，自动化结果不代表已验证喜好或留存。

## 交付门禁

```bash
npm --prefix frontend-console run lint
npm --prefix frontend-console run test
npm --prefix frontend-console run build
# 浏览器命令须显式传入专用 PostgreSQL、PW_REUSE_EXISTING_SERVER=0 和受限 MinIO 配置
npm --prefix frontend-console run test:e2e:functional
npm --prefix frontend-console run test:e2e:visual
make docs-check BASE_REF=origin/main
git diff --check
```

视觉基线更新必须逐张检查实际图像；不得降低阈值掩盖差异。功能回归必须等到最终结果。
