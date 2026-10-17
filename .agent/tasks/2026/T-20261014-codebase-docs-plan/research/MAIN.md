# 主代理共享文档事实核对

基线 22bb499789cba89fea92e918fd853ab768688e07；静态阅读，不做业务模型/数据库调用。

- Project restore_project_llm_execution_settings 在 llm_runtime.py:208 拒绝含local_agent的旧文本snapshot；executor_service.task_snapshot_client拒绝旧_local_agent设置。正常新文本任务使用账户连接。
- api.claim_invocation 只按device/pending选择，未按image mode过滤；companion._job 非image仍走_run_text_job；test_companion_image_job.py的合成文本job测试保留。因此不能写所有历史文本都被拒绝，也没有现况DB证明旧pending是否存在。
- docs/00_整体设计、CONTEXT、module-architecture图源和HTML仍描述可选文字Agent CLI，需统一当前图片范围及旧job兼容。数据库表/字段保留，不作为文字能力仍开放的证据。
- Writing services.py已是稳定聚合；真实实现是draft/conflict/generation服务，facade公开版本锁，候选采用同键重放。bootstrap提供DI注册，不拥有领域事实；Evidence稳定facade继续委托回读/编译。

共享文档改动由主代理独占；L1的旧job发现补充了保证边界，后续图文必须窄化。

## P2/P3 共享裁定

- 7领域共72claims：26处对应文档修订，43项按原说明保留；1项模型接线未知、2项关系历史反例覆盖限制单列，不新增业务测试或调用。标记的是claim处置，不是72项实测。
- L1/L2/L3/L4/L5/L7在独立writer树修改明确白名单，父检查并复制具体文件；L6无需要改的平台模块文件，共享DI与eval文字由父校准。
- ADR决策保留，只在ADR29索引区别目标与当前历史兼容；未把旧job兼容重新授权为文字能力。
- 新用户指南为唯一当前源，旧Word源和DOCX保留历史身份，不声称新版Word已导出/渲染。父校准RP审查前hold不可公开、停止清私有状态；同节点正式化仅visible非空。
- 不保留复制的权威目录。新增阅读指南和运行图源/HTML登记原TOML；维护协议链接新入口与附加图源验证，未改权限规则。
- 图片图限定世界对象生成链（候选先DB暂存，作者采用时existing upload到私有桶）；绑定作品RP图限定固定作品版本旅程，不把直接世界开场都套进去。
- Prompt静态26项合约通过由L6执行；父docs-check带BASE_REF通过。图表XML/ID/edges与20标签一致、390/768/1440离线阅读/键盘/减少运动检查通过；截图只证明文档视觉，图源是XML几何预览而非native Draw.io渲染。最后标签/说明修订后静态XML与HTML 20标签逐项一致检查通过；独立浏览器被file://策略阻断，停止相关操作，不将旧截图称为最终版。

- R1反证补充：runtime_policy.clear_private_agent_state保留knowledge_hold（正文/回执）供审计，清掉的是可恢复消息；父此前仅读调用点的概括不够，已纠正文档。停止无visible为cancelled，有visible走partial，hold始终不公开。
