---
id: T-20261013-capability-tail-fixes
title: 能力审计报告的自主收尾修复
status: active
created: 2026-10-13T22:07:41+08:00
updated: 2026-10-13T23:22:20+08:00
---

# 能力审计报告的自主收尾修复

## 目标与验收

用户目标：依据报告逐项修复无需用户决策的未完成收尾，授权单文件拆分级重构。32类完整处置见 [ITEMS.csv](ITEMS.csv)，实现/验证/保留边界见 [DELIVERY.md](DELIVERY.md)。不把公开接口退役、真实模型质量、新产品闭环或生产部署作为普通内部实现。

## 上下文与边界

独立工作树 .worktrees/capability-tail-fixes，codex/capability-tail-fixes，origin/main@974f0f5080d43472bc599d1d74782913c725057b。根codex/guided-flow-borrowing及其审计/比较任务WIP不写；其它Codex工作树及真实ledger归原任务。前一轮未委派/提交/推送/合并/部署；本轮用户明确授权全面review、直接修复、验证后提交并创建PR。按code-review Skill要求委派两路只读审查；允许提交/推送/PR，不合并/部署、不调用真实模型，guimi保护不变。

## 进度

- [x] 逐项当前调用链与处置矩阵。
- [x] 自主实现与三个服务大文件拆分；保留外部class、状态和调用合同。
- [x] 完整后端7743/86.8%、完整PG287、前端2974、桌面/390px/世界移动浏览器、实际图片UI替身，文档/lint/Prompt/依赖门禁。
- [x] 最后一轮完整test-ci退出0，所有代码内容指纹复核不变。
- [x] 本任务PG18482已fast停止，数据目录保留；Playwright自建API/Vite已退出。

## 决策与发现

完整保留边界见DELIVERY。私有window adapter无生产消费者可删，window/历史job整体退役仍需兼容处置。PG World/relations原仅宿主run/hash差异，统一既有sample语义manifest后四消费者证明复用而仍新attempt重物化。静态扫描路径迁至实际文件、章锚沿延迟Story facade后基线未放宽。图片原浏览器因未配置存储桶失败，内存存储替身复验成功，不当作MinIO证据。

## 验证与限制

日志/tmp/novelcraft-tail-fixes。test-ci初轮7失败已修正并由最终完整test-ci复验（退出0，详DELIVERY）；非真实模型PG全绿。未修改存量可选格式差异未全库重写；50本次Python文件格式通过。曾临时覆盖test_world已立即从本任务HEAD恢复后只加目标断言，错误结果作废重跑。

## 恢复快照

初轮结束：自主项实现、完整test-ci/PG/浏览器已完成，Git仍本地WIP；初轮任务曾completed，当前因明确review/PR授权恢复active。未写原根与其它工作树。
后续：用户选择提交/PR或明确兼容/产品/生产范围后，核对本工作树与实时origin/main及EVIDENCE指纹再继续。此记录不新增授权；32类处置均已说明，自主项无pending。PG已关闭且保留数据。
PG目录/tmp/novelcraft-tail-fixes/pgdata，仅本任务库novelcraft_capability_tail_test/novelcraft_capability_tail_browser_test；不要触碰其它PG端口或guimi。无阻塞，外部授权范围不执行。

## 2026-10-13 Review 与 PR 续办

用户明确恢复这次改动，要求全面review修复与32项处置，有问题直接修复，验证后提交并创建PR。origin/main fetch核实仍为974f0f5080d43472bc599d1d74782913c725057b，无现成主题PR；所有78个本任务改动仍未提交，根WIP保持。两路Skill只读审查规范与Spec，主Agent复现/修复/集成，不新增业务范围。已发现章节排除前导零不能撤销及200项上限静默截断，正在用回归测试固定。
当前：C10/C27遗漏已修复，两路独立复审无阻断项；61 eval/14组件、PG287及浏览器3条通过，文档/依赖/Prompt/lint/build/53个Python格式通过。32项完整复核见REVIEW.md。
完整test-ci已退出0：7746后端/2跳过、86.8%、2977前端；本任务PG已再次停止，浏览器API/Vite退出。
下一步：提交/推送并创建、附加PR；发布后关闭本任务索引。不要合并/部署。
