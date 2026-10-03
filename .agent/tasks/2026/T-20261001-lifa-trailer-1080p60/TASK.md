---
id: T-20261001-lifa-trailer-1080p60
title: 理法之环宣传片（1080p60，全新脚本）
status: completed
created: 2026-10-01T00:00:00+09:00
updated: 2026-10-01T01:10:00+09:00
---

## 恢复快照
- 状态：已交付 output/lifa-trailer-1080p60-20261001/理法之环-宣传片-1080p60.mp4（164 s）。
- 若需返修：改 src/scenes.js → `python3 render.py --stills <t…> --scale 0.5` 目检 → `python3 render.py --start 0 --end 164 --workers 5 --out build/video.mkv`（约 8 分钟）→ `./finish.sh`。仅改配乐：`python3 score.py` 后按下方母带链重做 score_master.wav 再 `./finish.sh`。

## 目标与验收
- 用户要求：为“理法之环”做宣传片；不使用本机 ad 技能，不受 T-20260930 旧脚本约束；规格 1920×1080、60fps。
- 内容须充分展示：①逻辑严密自洽的“可实现魔法”；②理法之环当前庞大的幻想空间；③对其他幻想世界的兼容性。
- 验收：ffprobe 确认 1920×1080/60fps/H.264+AAC；逐段关键帧目检；上屏事实均可回溯 Vault 正典或明示为方法论/示意。

## 来源与边界
- 实时 Vault：/Users/tywww/Library/Mobile Documents/iCloud~md~obsidian/Documents/wiki（只读，不写正典，不改 _raw）。
- 核心页：concepts/真名回响/理法之环.md；concepts/真名回响宣传词.md（“同一套物理账本，撑得起蒸汽朋克、修仙、克苏鲁——只要它自洽”）。
- 兼容性属于世界观方法论宣传，不得写成 Tellus 内存在修仙/克苏鲁等正典。

## 交付路径
- 工程与成片：output/lifa-trailer-1080p60-20261001/（gitignored，本地产物）。

## 关键决定
- 渲染：自研 HTML Canvas 场景（纯函数 t→帧，确定性）+ Playwright 多进程截帧管道进 ffmpeg；配乐 numpy 本地合成。
- 视觉语言全新（暗底蓝图 + WebGL 行星），不复用 T-20260930 的 33 张动漫图。
- 结构：表层引火术 → 底层蓝图（步骤/五本账）→ 七种失败面 → 五层架构 → 真实 Vault 关系图 → 兼容（五种载体→六位、三河十一谱、四个外来母题、180 构想审查）→ 片名。
- 兼容性只用正典原话支撑（基础咒式单元“咒辞、手势、阵图、材料次序或身体节律承载同一责任”、法术谱系“文化接口”、三河十一谱、宣传词），Explore 推断的“修仙/克苏鲁→某正典”映射不上屏。
- 失败面用 concepts/法术谱系 当前术语（构形失败…系统异常），不用旧 meta 页“编译错误”。
- 候选内容（15 个候选文明圈、180 构想审查）上屏均标“候选/待作者裁定”。

## 上屏事实来源（均为只读 Vault）
- 引火术数值（5–15 W、350–400 °C、0.004–0.020 °C/s、默算两位数乘法、编译 0.3–1 s、共鸣深度 1、物质账零、两句原话）：concepts 引火术相关页。
- Tellus 半径约 8000 km、海洋约六成、约 18–20 个一级地理舞台（作者创作预算）：Tellus.md。
- 双月 60°、光行约 1.5 s、银月/苍月分工；星锻环 ~0.05 AU 分布式轨道群、约 8 分钟、P_tx 式：理法之环/天体相关页。
- 三河尺度与三河无应海/千阶城/折光塔原话：对应地区页。PHI-09/PHI-10：设计原则页。
- 图谱数字 301 页 / 5,493 条引用 / 141 万字：extract_graph.py 于 2026-10-01 对 wiki/ 实时统计（含候选与审查页，屏上已注明）。

## 验证
- ffprobe：H.264 High@4.2、1920×1080、yuv420p、60/1、BT.709（primaries/transfer/matrix 均已标）、9840 帧、164.000 s、约 9.0 Mbps；AAC LC 48 kHz 立体声 320k；+faststart。
- 响度：成片音轨 -14.02 LUFS、真峰 -1.62 dBTP、LRA 7.0。母带链：score_raw → EQ(80 Hz -2.5 dB, 3 kHz 高架 +5 dB) → +3 dB → 192 kHz 过采样 alimiter 0.79 → 48 kHz；编码时 -0.23 dB。
- 同步：成片音轨与母带互相关偏移 0 样本；画面与配乐同由 cues.json 驱动。
- 画质：CRF16 版对无损母版 PSNR 平均 39 dB，最差帧在星图快速变焦（~21 dB，目视无可见劣化）；最终采用 CRF14。
- 目检：两轮关键帧修正后，从成片抽 23 帧覆盖全部 8 场，均正常解码、无越界/遮挡。
- 未验证：配乐未经人耳试听；未在手机/电视等实际播放器上观看；未在具体发布平台上传测试。

## 产物
- 成片：理法之环-宣传片-1080p60.mp4（约 182 MB）。
- 无损母版：build/video.mkv（14 GB，libx264rgb qp0，可删除，重渲约 8 分钟）；配乐：build/score_raw.wav、build/score_master.wav。
- 工程：src/（core/planet/scenes/graph.js + film.html）、render.py、score.py、extract_graph.py、cues.json、finish.sh。
