# 第三批运行时修复

关联主任务：同目录 TASK.md。本文件只记录可独立审查的基础修复；实际诡秘双臂验收继续使用冻结工作树和私有回执，未宣称全链或真人验收通过。

隐式模型请求已经由项目客户端解析为 Luna，但步骤摘要曾写回 schema 默认模型，导致 confirmed_scope 在调用前拒绝。现在仅显式 model 覆盖已解析配置，仍拒绝显式跨模型请求。

带真实 usage 的 provider 无效输出曾遗漏 failed structured_usage。现在保留该失败用量后原样抛出；无 usage 不填零，不增加重试，不放宽普通 scene_world 的人工核对门禁。

验证：同一文件内容的 Project/Account、Imports、Evolution sampler、LLM 和 Evidence 相关 610 项回归通过；make lint、secret-hygiene、docs-check BASE_REF=origin/main 及独立只读审查通过。新增测试覆盖隐式继承完整审计调用链、显式跨模型拒绝，以及已知/真实零/未知失败用量。

未执行浏览器或原生窗口验收；本次不改 UI、本机目录或窗口生命周期。不修改原 guimi/原 v3 数据，不包含发布或合并授权。
