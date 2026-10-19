# 工作树处置与保留

2026-10-19 核对45个原工作树，新增一个整理工作树。39个闲置树已移除，保留6个任务工作区；额外整理临时树在关闭记录合入后移除。

| 保留工作区 | 用途与边界 |
|---|---|
| 仓库根目录 | 新地图联动codex/map-linkage-impl及未提交笔记；研究output保留本机 |
| `/Users/tywww/.codex/worktrees/desktop-local-app/ai-writing-assist` | 桌面发行验收；`codex/desktop-release-acceptance`，签名/公证、最终原生窗口和升级验收仍待 |
| `.worktrees/director-scales-impl` | 多尺度探索主实施与第五批准备；PR #255已合并，第五批真实模型/作者验收仍待 |
| `.worktrees/wave3-evidence` | 第三批A2/G7b/P4-E未完成，不自动合入3个独立提交 |
| `.worktrees/wave3-guimi-v3` | 固定v3现场、冻结运行脚本和标记；保存额外快照提交但原HEAD/index不变 |
| `.worktrees/wave3-r1` | 第三批历史与恢复笔记；保存额外快照提交但原HEAD/index不变 |

移除范围：临时基线检查、CI工作树、24个导演实施子树、导演规划树、9个map-fix树、旧文档刷新树、旧模型池树、G6b树。后13个dirty树均先形成仅本地归档提交；旧补丁已有主干交付/后继修订，不重放旧实现。

私有恢复目录为共同Git目录下 `cleanup-archives/worktrees-20261019/`。源码用 `refs/archive/worktree-cleanup/20261019/<key>` 恢复；清单包含来源分支、原HEAD与快照提交。配置、测试/运行证据和其他非依赖ignored文件逐文件/符号链接核验后保存为私有tar；不将其加入源码或推送。可再生依赖和缓存未归档。

G6b首轮/拒答修复及G6c留出已有completed记录；其原始副本以本地快照和私有文件归档保留，未重放实验。第三批的三个独立树保留，不能据前序校准完成宣布第三批终验完成。

清理前核对进程cwd和保留树软链接，无目标目录依赖。普通源码和非ignored未跟踪文件均已保存至Git快照；`.env`仅进入本地私有tar，未输出内容、未提交或外发。
