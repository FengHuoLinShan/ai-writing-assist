---
id: T-20261013-capability-tail-fixes
title: 能力审计报告的自主收尾修复
status: active
created: 2026-10-13T22:07:41+08:00
updated: 2026-10-14T09:21:08+08:00
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

当前：32项逐项review、C10/C27补修、两路独立复审和本地最终门禁完成；实现已提交/推送为66da6b36d0408687d0eab376c143f4d6250bce18。已创建并附加[PR #222](https://github.com/FengHuoLinShan/ai-writing-assist/pull/222)，OPEN、非draft、base main。任务关闭，索引移除。远端CI已启动，记录时仍在运行，不宣称远端全绿或main验收；未合并/部署。

所有代码内容与EVIDENCE.json验证指纹一致，后续收尾仅更新本任务记录与索引。原根/其它worktree的WIP不写。隔离PG18482已停止并保留/tmp/novelcraft-tail-fixes/pgdata，API18484/Vite18485已退出；guimi未访问。日志/tmp/novelcraft-tail-fixes，不提交原文/Key。

下一步：本请求无待实现项；如获明确合并授权，先实时复核PR固定head/远端检查与main基线，再遵守合并门禁；C10校准、产品/生产/兼容/档案取舍仍按ITEMS边界单独处理。记录不新增授权。

## 2026-10-13 Review 与 PR 续办

用户明确恢复这次改动，要求全面review修复与32项处置，有问题直接修复，验证后提交并创建PR。origin/main fetch核实仍为974f0f5080d43472bc599d1d74782913c725057b，无现成主题PR；所有78个本任务改动仍未提交，根WIP保持。两路Skill只读审查规范与Spec，主Agent复现/修复/集成，不新增业务范围。已发现章节排除前导零不能撤销及200项上限静默截断，正在用回归测试固定。
当前：C10/C27遗漏已修复，两路独立复审无阻断项；61 eval/14组件、PG287及浏览器3条通过，文档/依赖/Prompt/lint/build/53个Python格式通过。32项完整复核见REVIEW.md。
完整test-ci已退出0：7746后端/2跳过、86.8%、2977前端；本任务PG已再次停止，浏览器API/Vite退出。
交付：提交/推送及PR创建完成，地址https://github.com/FengHuoLinShan/ai-writing-assist/pull/222。不要合并/部署。

## 2026-10-14 CI修复与合并续办

用户明确授权继续跟进PR #222，失败直接修复，全部检查通过后合并main。旧“不合并”仅是初轮边界，已由本轮授权更新；仍不部署、不调用真实模型、不触碰guimi或其它WIP。恢复时主题工作树干净，head 05da9a08e1bf68ecd1487432ba10bbce9b7a8f65；PR OPEN，frontend functional shard 1失败及聚合失败，其它16项成功。正在取失败日志并刷新main基线。

下一步：定位浏览器失败根因、必要修复/本地回归后提交推送；等待固定head全部远端检查成功，再用match-head-commit合并。保留原32项分类，不扩大功能范围。

CI根因：WebKit trace在setViewportSize(1024×768)后读到aria-expanded=true，无click，随后resize watcher进入compact关闭资料栏；测试因此等一个从未打开的dialog。响应式通用helper已有双requestAnimationFrame等待，失败用例未使用。改为runResponsiveMatrix复用既有切换同步，所有正文/选区/资料草稿/焦点/偏好/持久化断言原样保留，无提高timeout或retry，无生产代码修改。WebKit 11、Chromium 11移动核心用例全部通过；ESLint、docs BASE_REF和diff检查通过。准备提交推送，等待最终固定head远端检查，再合并。原main仍为974f0f5080d43472bc599d1d74782913c725057b。
