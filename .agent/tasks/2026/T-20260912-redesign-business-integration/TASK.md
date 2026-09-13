---
id: T-20260912-redesign-business-integration
title: 全站新设计接入真实业务与演示项目验收
status: completed
created: 2026-09-12T23:25:15+08:00
updated: 2026-09-13T00:59:26+08:00
---

## 目标与验收
用户授权全站新设计接入真实业务，本地真机使用持久演示项目验证；允许真实DeepSeek Flash调用，型号以实际为准，允许合理使用Luna/Terra/Sol子代理。当前正式入口覆盖全部领域，原型独立保留。

## 恢复快照
- 实现与真实流程已完成；逐项目标证据见[VALIDATION.md](VALIDATION.md)、[页面覆盖](evidence/final-pages/README.md)。收尾文档门禁与diff检查已通过。
- 工作区 /Users/tywww/Desktop/项目/ai-writing-assist，分支codex/redesign-regression；前轮精简/原型及其他WIP均保留，源码备份见BASELINE.json。未提交、合并、推送、部署。
- 真实服务8080生产构建、8000后端与独立worker仍运行；启动/重复演示说明见[RUN.md](RUN.md)。schema guard已通过。原演示app目录源码未覆盖。
- 本地演示项目937c86f1-a2c3-4db5-963d-f3181095f339，数据库ai_novel_acceptance_guimi。备份位于演示backup/redesign-business-20260912-233013/database.dump。未清库/重导入/改原稿。
- 本轮新增61章验收稿最终271字、一个已完成作者任务、一个资料工作稿、私人互动旅程d529051e-02ce-4a43-acc4-4bb8fd7135cd。全程保留可追踪身份。原60章摘要未变，当前演示项目无pending/running任务。
- 实际生成provenance.model是deepseek-flash；没有把旧全局配置deepseek-v4-flash当实际型号。模型显示改为真实当前账户连接metadata。
- 下一步：用户可按RUN.md打开或重新启动演示；本任务无剩余实现。提交、合并、推送和部署仍需另行授权。

## 进度
- [x] 规则/WIP核对、源码和数据库备份、已有约束修复迁移检查。
- [x] 正式shell/写作/世界/故事/地图/查找/维护/设置/身份/互动新设计与真实控制器接入。
- [x] 真实生成、incomplete保护、重审PASS、确认采用、保存重复/断网/刷新/双窗冲突与合并。
- [x] 资料与作者任务持久化、偏好保存并恢复原值、私人互动行动/续写/草稿恢复。
- [x] 独立审计、16页真实浏览器覆盖、关键录屏及减少运动/窄窗口。
- [x] 全前端188文件2452测试、全lint、后端语义审查16测试、最终build53JS/85资产。
- [x] 收尾docs-check BASE_REF=origin/main与git diff --check通过，任务完成。

## 关键决定与证据
- 保留现有Vue/bridge/router/controller/API及鉴权、项目隔离、来源确认、并发与幂等，未把原型成功状态带入正式路径。
- 修复URL章节恢复、候选选择与incomplete假成功；冲突恢复采用显式备份→确认→读服务器新版本→手工合并，保留成功/失败晚响应守卫。
- DeepSeek首审把不适用说明写入not_checked，澄清prompt后真实重审通过；没有删除not_checked阻断或自动把说明解释成PASS。
- 首次导出事件观察工具超时，但实际Downloads文件存在且含A/B；旧导入浮层遮挡点击经截图定位后收起，未清理其历史数据。
- 子代理独占文件域；主代理整合、真实写入、独立审计裁决与最终证据。页面记录原误放repo/evidence，已移入本任务指定位置。
- 全测试/tmp/redesign-acceptance-tests.log，全lint/tmp/redesign-acceptance-lint.log，最终构建/tmp/redesign-delivery-build.log，后端/tmp/redesign-business-semantic-tests.log。

## 边界
真实验收是本机Chrome/内置浏览器+真实数据库/模型；不冒称物理手机、IME合成、屏幕阅读器或远端注册认证。未调用图片生成、不部署；既有图片/导入等链路按实际修改范围保留并检查，未重新消耗原稿。详见VALIDATION的覆盖边界。

## 收尾
本地实现与验收完成；收尾门禁日志/tmp/redesign-delivery-docs.log。服务与真实演示入口保留；项目原始60章最终完整性核验通过。未提交、合并、推送或部署。
