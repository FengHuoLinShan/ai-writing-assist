---
id: T-20261001-novelcraft-intro-video
title: NovelCraft 项目介绍视频（1080p60，含真实界面）
status: completed
created: 2026-10-01T01:30:00+09:00
updated: 2026-10-01T04:30:00+09:00
---

## 恢复快照
- 状态：已交付 output/novelcraft-intro-1080p60-20261001/NovelCraft-介绍片-1080p60.mp4（156 s）；本地 8131/8132 服务已停。
- 若需返修：改 src/scenes.js → `python3 render.py --stills <t…> --scale 0.5` 目检 → `python3 render.py --start 0 --end 156 --workers 5 --out build/video.mkv`（约 9 分钟）→ `./finish.sh`。重截界面需先按原方式在复制库起前后端，再 `python3 capture.py <名称>`。仅改配乐：`python3 score.py` 后按下方母带链重做 score_master.wav 再 `./finish.sh`。

## 目标与验收
- 用户要求：做第二份视频介绍 ai-writing-assist（NovelCraft），部分画面使用实际 UI 界面。
- 规格沿用上一支：1920×1080、60fps、H.264 + AAC。
- 验收：ffprobe 规格；关键帧目检；上屏的功能描述与 README/模块文档一致，默认关闭或实验能力如实标注；UI 画面来自当前代码真实运行。

## 来源与边界
- 产品事实：README.md（2026-09-28 核对）与模块 README。
- UI 数据：复制 `ai_novel_acceptance_guimi` 为本任务专用库 `ai_novel_promo_intro_20261001` 后只读浏览；原库不改，不起 worker，不调用付费模型。
- 演示内容为《诡秘之主》前 60 章演示项目（用户已作为线上演示使用）；画面避免长段原文，公开发布的内容权利由用户确认。
- 不沿用 T-20260911 的 90 秒录屏计划（其 P0–P4 产品补强不在本任务范围），仅复用其封面母版与视觉色调。

## 交付路径
- 工程与成片：output/novelcraft-intro-1080p60-20261001/（gitignored）。

## 关键决定
- 结构 156 s：开场问题（60 章/212,868 字）→ 品牌与首页 → 01 写清楚（今日/人物与设定/场景/正文/地图）→ 02 有据可查（证据闸门、观察语义、关系依据）→ 03 由你决定（项目助手、提案-确认-重验流程、大纲版本、导入候选）→ 04 走进故事（旅程列表/旅程/分支树）→ 05 可恢复可审查（12 模块、lease 与返回重验）→ 结尾封面。
- 真实界面约占三分之一，均标“实际界面 · 本地运行的演示项目”；其余为 Canvas 动效示意。
- 避开测试遗留数据：today 右侧【新版接入验收】卡不入镜；项目助手改在大纲页打开重截；正文原文只短暂、压暗出现，结尾署名原作版权。
- 项目助手标“Alpha · 服务端默认关闭”；片头与结尾标“Alpha · 工程验证阶段”。
- 渲染：本地 127.0.0.1 临时 HTTP 服务（避免 file:// 图片污染 canvas）+ 上一支的确定性多进程截帧管道；配乐 D 大调毛毡钢琴，本地合成。

## 验证
- ffprobe：H.264 High@4.2、1920×1080、yuv420p、60/1、BT.709（primaries/transfer/matrix/range 均已标）、9360 帧、156.000 s、约 10.4 Mbps；AAC LC 48 kHz 立体声约 306 kbps；moov 前置（+faststart）。
- 响度：成片音轨 -14.0 LUFS、真峰 -1.7 dBTP、LRA 3.4。母带链：score_raw → EQ(80 Hz -2 dB, 3 kHz 高架 +2 dB) → +5.4 dB → 192 kHz 过采样 alimiter 0.79 → 48 kHz。
- 同步：成片音轨与母带前 30 s 互相关偏移 0 样本；画面与配乐提示点同源（cues.json 由场景常量生成）。
- 目检：静帧逐段两轮修正（镜头推近、测试数据避让、标注框坐标、片段重叠）；从成片抽 24 帧覆盖 8 场，均正常解码、无越界/遮挡。
- 未验证：配乐未经人耳试听；未在手机/电视等实际播放器与发布平台上测试。

## 产物
- 成片：NovelCraft-介绍片-1080p60.mp4（约 208 MB）。
- 无损母版：build/video.mkv（19 GB，可删除，重渲约 9 分钟）；配乐 build/score_raw.wav、build/score_master.wav。
- 工程：src/（core/ui/scenes.js + film.html + assets/cover-master.png）、ui/（13 张 2x 截图 + page-text.json）、capture.py、render.py、score.py、cues.json、finish.sh。
- 专用复制库 `ai_novel_promo_intro_20261001` 仍在 ai-novel-db 容器中，确认不再重截后可删除；原库未改动。
