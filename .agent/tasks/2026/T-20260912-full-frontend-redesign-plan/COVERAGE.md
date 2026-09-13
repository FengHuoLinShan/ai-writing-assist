# 全前端设计覆盖

预览：`http://localhost:8097/prototypes/redesign.html`。默认写作；支持`page`、`state`、`section`与`theme`初始参数。

设计归属与业务接回分开：下表51个基础单元均有本地实现/明确证据；真实API、保存、账户、模型、文件读写全部未接。工作稿等成功状态必须带演示标识。
页面状态由“设计预览”选择；领域更深状态在本页的身份选择、状态演示或处理步骤中进入。刷新回初始示例，本次导航保留局部状态。

## 逐项归属

| ID | 设计范围 | 实际实现/记录 | 入口与状态检查位置 |
|---|---|---|---|
| A01 | 作者入口清点 | `A01-INVENTORY.md` | 只读证据 |
| A02 | 世界/结构/地图/查找清点 | `A02-A03-INVENTORY.md` | 只读证据 |
| A03 | 身份/读者/设置/AI清点 | `A02-A03-INVENTORY.md` | 只读证据 |
| S01 | 共享视觉与三种外壳 | `redesign.css / workspace-details.css / motion.css` | writing、reading、world |
| S02 | 寻址和会话返回 | `RedesignApp.vue` | page/state/section/theme与返回路径 |
| P01 | 本地标题正文、身份、保存保护 | `WritingPreview.vue` | writing；稿件身份与演示下一状态 |
| P02 | 章节搜索管理与计划入口 | `WritingPreview.vue` | writing；目录管理/新建/历史恢复 |
| P03 | 候选比较、审查与返修 | `CandidateReview.vue` | 写作伙伴→候选→状态演示 |
| P04 | 版本比较恢复与正式确认 | `VersionReview.vue` | writing→版本历史 |
| P05 | 本章场景资料/证据/地图/检查 | `WritingPreview.vue / ConflictReview.vue` | writing→本章资料/写作伙伴→检查 |
| P06 | 作品档案创建编辑与回收 | `WorkspacePreview.vue` | projects |
| P07 | 创作概览与作者计划 | `WorkspacePreview.vue` | today、tasks |
| P08 | 导入准备与章节检查 | `ImportPreview.vue` | import |
| D01 | 世界列表卡片分类搜索 | `WorldPreview.vue` | world |
| D02 | 资料详情编辑与图片状态 | `WorldDetail.vue` | world→资料详情 |
| D03 | 待决定/关系/别名审阅 | `WorldReview.vue` | world→需要决定/关系审阅/别名 |
| D04 | 关系与知识图谱 | `WorldConnections.vue` | world→关系 |
| D05 | 世界书导入健康与历史 | `WorldImport.vue` | world→世界书 |
| D06 | 总览与篇章 | `StructurePreview.vue` | outline→故事总览/篇章 |
| D07 | 剧情线与伏笔揭示 | `StructurePreview.vue` | outline→剧情线→详情 |
| D08 | 场景目录与本场 | `StructurePreview.vue` | outline→场景 |
| D09 | 剧本排演与过期 | `StructurePreview.vue` | outline→场景→工作台 |
| D10 | 地图浏览与地点 | `MapPreview.vue` | map→浏览/图层 |
| D11 | 地图结构与变更审阅 | `MapPreview.vue` | map→地图结构/变更审阅 |
| D12 | 地图时点与排演 | `MapPreview.vue` | map→时点与排演 |
| D13 | 查找范围结果与修复 | `SearchPreview.vue` | search；页面失败状态 |
| D14 | 来源预览定位钉选 | `SearchPreview.vue` | search→来源预览 |
| E01 | AI意图与讨论历史 | `AssistantPreview.vue` | assistant或写作伙伴抽屉 |
| E02 | 任务进度停止恢复重开 | `AssistantPreview.vue` | assistant→任务与结果 |
| E03 | 批次范围、部分完成与重查 | `AssistantPreview.vue / CandidateReview.vue` | assistant→批次审阅 |
| E04 | 整理范围/质量/审阅/查漏/记录 | `ImportPreview.vue` | import→准备资料→整理示例 |
| E05 | 提醒与持续检查设置 | `AssistantPreview.vue` | assistant→提醒 |
| F01 | 互动故事列表 | `JourneyPreview.vue` | journeys |
| F02 | 直接开场与来源准备 | `JourneySetup.vue` | journeys&section=setup或source |
| F03 | 阅读输入分支与流式反馈 | `ReaderPreview.vue` | reading |
| F04 | 回顾约定来源与设置返回 | `ReaderPreview.vue` | reading→阅读辅助 |
| F05 | 身份与账户状态 | `IdentityPreview.vue / SettingsPreview.vue` | identity、settings |
| F06 | 模型/图片/账户和作品偏好 | `SettingsPreview.vue` | settings→相应类别 |
| F07 | 外观主题资源与帮助 | `SettingsPreview.vue` | settings→外观/快捷键与帮助 |
| G01 | 写作与审阅手机平板 | `WritingPreview.vue / PreviewDialog.vue / workspace-details.css` | writing；章节/资料模态抽屉 |
| G02 | 阅读与开场手机平板 | `ReaderPreview.vue / JourneySetup.vue` | reading、journeys |
| G03 | 世界密集资料适配 | `world-preview.css` | world |
| G04 | 结构与场景适配 | `workspace-details.css` | outline |
| G05 | 地图查找来源适配 | `workspace-details.css / SearchPreview.vue` | map、search |
| G06a | 作品计划导入适配 | `workspace-details.css / ImportPreview.vue` | projects、tasks、import |
| G06b | AI任务适配 | `AssistantPreview.vue / workspace-details.css` | assistant |
| G06c | 身份账户设置适配 | `IdentityPreview.vue / workspace-details.css` | identity、settings |
| H01 | 组件展示与控件清单 | `ExperiencePreview.vue / CONTROL-COVERAGE.md` | components |
| H02 | 连续路径回归 | `previewContinuity.test.js / VALIDATION.md` | 文稿→查找返回；候选重开；阅读→设置返回 |
| H03 | 独立审查 | `BROWSER-INDEPENDENT-REVIEW.md / WORLD-INDEPENDENT-REVIEW.md` | 见报告实际范围 |
| H04 | 修复收口与最终验证 | `VALIDATION.md / TASK.md` | 门禁、证据和后续边界 |

## 验证解读

- 实现覆盖不等于每个真实业务可用；测试与浏览器结果以[VALIDATION.md](VALIDATION.md)为准。
- [控件覆盖](CONTROL-COVERAGE.md)用于逐项查找动效与状态，不是新的DOM、CSS、尺寸或截图像素门禁。
- [独立浏览器评审](BROWSER-INDEPENDENT-REVIEW.md)明确实际操作范围；世界域[独立浏览器报告与修复复验](WORLD-BROWSER-REVIEW.md)已完成。未观测的组合不写成通过。
- 移动目前是浏览器窗口模拟与键盘操作验收，不包含真实软键盘、物理触摸设备或屏幕阅读器实机。
- Apple式熟悉感为视觉方向与设计判断，不声称Apple归属或已经过用户盲测。

## 后续业务接回

在单独授权的接回阶段，将各域状态演示替换为已有领域接口和确认回执，保留鉴权、项目隔离、来源重验、保存恢复与幂等性。当前原型不接管正式路由，不替换生产页面；无需为视觉重设计维护旧截图。
