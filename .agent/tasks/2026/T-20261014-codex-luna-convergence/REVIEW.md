# G2 固定版本复核

基线：e02137f79fc4e8f5ba4f79f541b66b5dbaa47a05。被审HEAD：904530e891d3ac2f0720cc5028f23b83eb6251a3。使用Code Review技能两路独立只读复核，不调用业务模型或数据库。此报告记录发现；修后复核与最终CI尚待完成。

## Standards

两项P2：

- GlobalSettingsView.vue原634行将独立图片Key输入/错误区域也受文本Codex条件隐藏；默认Codex时用户无法连接或替换图片服务。违反AGENTS.md外部契约和正常/失败流规则。恢复图片区域独立显示。
- health.py原275行将原生未知分类与白名单诊断压为codex_unavailable；imports/workflow.py实际保存llm_health及phase_errors，丢失可核验证据。与infrastructure/llm/README.md“连接验证保留这些字段”不符。需要保留分类/字段，或让原生预检不执行模型。

未发现值得单独整改的新增代码异味；稳定facade符合项目约定。此轴未发现自动重放证据。

## Spec

一项P1：

计划第90行要求“当前授权……unknown不自动重放”。原health.py264—279直接执行无项目范围的verify_codex_connection，再将unknown压成codex_unavailable；workflow.py160—176标可恢复，orchestrator.py1508—1513恢复阶段pending，重发固定验证请求且无journal。等待槽期间撤销连接也不能经Project再验。原生导入预检应只核验当前已验证项目连接，模型验证留到账户显式入口。

其余检查的owner、包装快照、普通unknown、取消/轮换、跨进程账户槽、旧文本拒绝/回执可读、迁移降级守卫及评测隔离均有对应实现。报告未宣称旧unknown根因或Guimi全量完成。

两轴分别计数：Standards 2项、最高P2；Spec 1项、最高P1。修复须通过对应回归和新固定HEAD复核，不能将本报告当绿色签收。
