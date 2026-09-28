# 当前板端状态固化盘点（2026-09-28）

目标：以当前 RK3588 板端运行状态为版本基准，使用 162 上的旧 RK3588 SDK 重新构建可重复交付的固件。现有 `/userdata/lightrag-data/`（含 UCM630x 已建库）是保留数据，不参与清理、重建或升级覆盖。

本文件记录只读盘点和程序快照。尚未构建或刷写新固件，也尚未在空白板上验证恢复。

## 当前可恢复快照

- 私有归档位于 162：`/home/rockchip-yn/data/rklight-rag-stage/releases/current-board-20260928/`。包含板端 `/userdata/rklight-rag`、2B/4B/Embedding/Reranker/视觉模型目录、实际 RKNN 运行库与 `rkllm3-server`、系统包列表、设备身份和软链接记录。原始板端配置含密钥，仅保存在这个私有归档中；仓库里的 `deploy/profiles/current-board-20260928.env` 已将密钥替换为占位符。
- **不包含** `/userdata/lightrag-data`。这个快照用于重建程序、模型和配置，不是 UCM630x 已建库的备份，也不能单独在新板上复现该库的问答结果。
- 已建库现在另有**独立私有备份**：`/home/rockchip-yn/data/rklight-rag-stage/releases/current-board-20260928-kg-backup/`。从板端只读复制了 `/userdata/lightrag-data` 的 235 个文件（约 247 MB），板端与副本的逐文件 SHA256 清单相同；原 PDF、整理后的 MD 和本地调试请求放在备份的 `source-docs/`。知识库不进入固件包，也不提交 Git。备份时 LightRAG/模型网关进程未运行。
- `SHA256SUMS` 是逐文件完整性清单；在 162 上执行 `bash scripts/firmware/verify-snapshot.sh <归档目录>` 校验。`.work` 仅为校验临时工作区，不属于发布文件。
- 原版 LightRAG 固定为提交 `7ecd8a0512c1f5b221456b24de225a71e1e002d8`。`deploy/patches/lightrag-7ecd8a0-board.patch` 保存板端 9 个已修改上游文件；`bash scripts/firmware/verify-board-source-patch.sh <归档目录>` 已验证：原版源码应用补丁后，9 个文件与板端逐字节一致。扩展模块文件另在程序快照和仓库 `core/lightrag-extensions` 中保存。
- `scripts/firmware/restore-snapshot-to-clean-board.sh` 仅面向**无现有程序和知识库的同型号空白板**，默认是校验和干跑，须显式 `--apply` 才安装。传入 `--kg-backup <独立备份目录>` 时，脚本先验证备份，再在启动服务之前恢复知识库并复核哈希。当前 UCM630x 板会被拒绝，不能用它做恢复试验。
- 162 SDK 的旧 `update.img` 带 `userdata.img`，**不能用于当前板保库升级**。要做正式固件，先核对 EVB10 的 DTS/分区、从本快照制作应用层并在备用板测试；保库升级包不能包含 `userdata` 分区。

截至本次归档，目录约 8.2 GB，`SHA256SUMS` 覆盖约 6100 个文件。162 上已通过清单核验和 9 文件补丁重建核验。最终哈希以归档内的清单及现场校验输出为准；归档所在上级目录权限为 `700`，原始配置文件为 `600`。

## 已确认的来源

| 层 | 当前来源与状态 | 固化动作 |
| --- | --- | --- |
| RK3588 SDK | 162：`/home/rockchip-yn/data/rk3588/aibox_3588/`，入口 `build.sh`/`Makefile`，当前 defconfig 为 `rockchip_rk3588_ai_box_v10_defconfig` | 以它为编译底座；当前板为 `RK3588 EVB10 V10`，SDK 内另有 `rockchip_rk3588_evb10_v10_defconfig`，不能盲用 AI Box 的 boot/DTS |
| 旧固件重打包 | 162：`/home/rockchip-yn/code/evb_rootfs/repack_aibox_20260917/` | 只作历史参考；旧 `update.img` 不能直接用于当前板升级 |
| LightRAG 上游 | 板端 `7ecd8a0512c1f5b221456b24de225a71e1e002d8`，包版本 1.5.7 | 固定提交；精确补丁已通过 9 文件逐字节验证 |
| LightRAG 扩展 | 板端上游源码有 9 个已修改文件、约 771 行新增；主要 Hook 源码在本仓库 | 板端有效源码和精确补丁均已归档，排除历史 `.before-*` 和 `.bak-*` 文件；Hook 从原版直接重放仍有依赖既有手工改动的问题 |
| WebUI | 板端两处 TypeScript 默认值和本地存储迁移被修改 | 已补入可重复安装脚本 `install_lightrag_webui_defaults.py`，构建 WebUI 前应用 |
| 模型网关与模型 | 问答 2B、建库 4B、Qwen3 Embedding/Reranker；模型权重在板端 `/userdata` | 锁定命令、设备 ID、二进制和模型文件哈希；只复制实际启用的资产 |
| PDF 解析 | 板端 `rkvision`，DocLayout-YOLO、PPOCRv6、Document Vision | 固定实际二进制、库、模型和 Python 插件版本 |
| 系统服务 | 本轮通过临时 systemd 单元运行；没有持久的 LightRAG/网关开机服务 | 制作正式 unit，验证冷启动与失败恢复 |
| 知识库 | `/userdata/lightrag-data/`，独立于程序 | 保留原样；新板测试使用独立目录，不以现有库作写入测试 |

## 已发现的重建缺口

1. 仓库的 `deploy/lightrag.env` 仍以 9B 为问答模型，板端实际配置为 2B，且板端配置有更多检索与建库参数。不能直接运行当前部署脚本覆盖板端配置；要先生成经过密钥脱敏和审核的“当前板配置”发布文件。
2. 原安装器未将 `rk_table_parent.py` 复制到 LightRAG 包；已补齐。WebUI 的两处板端源码修改也已补入构建前安装步骤。对现有 `core/lightrag-extensions`、`core/model-gateway`、`core/ingest-router` 的有效源码抽样做 SHA256 对比，除旧版 `lightrag-rk3588.env` 外，开发机与板端对应文件一致。原 Hook 链不能从固定原版独立生成板端代码：查询默认值 Hook 假设 Mix 预算块已存在。精确补丁是这次归档的可复现基准；后续可再整理 Hook 链，但不能以当前 Hook 链代替这个补丁。
3. 板端的 `/usr/bin/rkllm3-server` 是 2026-09-18 的单独二进制，已连同 Python venv、RKNN 库、模型文件按哈希冻结；仍需确认其放进旧 rootfs 后的运行兼容性。
4. 162 旧 `package-file` 包含 `userdata.img`，而知识库和模型都在 `/userdata`。出厂全量镜像与当前板保库升级包必须分开；后者不得写 `userdata` 分区或重建分区表，只能更新经验证的程序/模型目标路径。
5. 162 所在文件系统归档后约剩余 23 GB，旧固件工作目录已占约 70 GB。生成新镜像前须计算中间产物峰值，避免复制整块板的 `/userdata`。

## 已核对的当前板关键文件

以下 SHA256 是只读盘点值，用于后续发布包核对；完整逐文件清单已生成在私有归档 `SHA256SUMS`。

| 文件 | SHA256 |
| --- | --- |
| `/usr/bin/rkllm3-server` | `fb81d320407db09ce4c1b353dabb66e0fcd1833661fc2afaf99b07f07b466912` |
| `/usr/lib/librknn3_api_rkcp.so` | `60eae56c3d3a41ef0e263303ec92c317baeed94254910236848bfee30a049648` |
| `/userdata/Qwen3.5-2B/Qwen3.5-2B.weight` | `88444038cec1a3e87bfd22fc82f1c8ff79e0de78b1995c897a093ed8bb11cab2` |
| `/userdata/Qwen3.5-2B/Qwen3.5-2B.embed.bin` | `1014821eb1ecd1554be53855305701a402daced03fbc108ef7105223cdcd5d36` |
| `/userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.weight` | `46d155eece792e7d262857c4006b2ef4e7a00a961bb0c140b26ab37ed10af515` |
| `/userdata/RK1828-qwen3.5-4b-service/models/Qwen3.5-4B/Qwen3.5-4B.embed.bin` | `c78988d979f52a340f39cd69edd8e4b0a80218a5fa8d95b6158bfce4a3de2a34` |
| Embedding 0.6B `.weight` | `0b775f6a6e1996aa65294556b2d1a0a1e20789ccc7bf156d87593c6144b24bdd` |
| Reranker 0.6B `.weight` | `58b5cd9a599c9e5583998baee93e289a13b615c78f4bd038b3448b924063cc4b` |
| `rk1828_embedding_daemon` | `67aca27027e83802939f921d1109d9e532518ced9da3754be75db7d7c9047aa6` |
| `rk1828_reranker_daemon` | `bc17399c492b62464fe780097a2101446d27cb930e5ed67ca9477d9a82c33bf3` |

## 发布门禁

- 生成逐文件清单：来源、版本、SHA256、目的路径和安装顺序；密钥单独注入，不写入公共镜像。
- 在独立 staging 目录重放上游安装与全部 Hook，比较其有效文件和当前板，解释每个差异。
- 出厂镜像在空白板上验证首次启动、模型健康、WebUI、一次小文档建库和代表性问答。
- 保库升级在**知识库副本或备用板**上验证，不直接以当前 UCM630x 库做试验；升级前后比较数据清单和哈希。
- 使用独立备份在空白板上测试完整恢复；当前仅完成程序快照和知识库备份的静态哈希校验，未验证新系统镜像与冷启动恢复。
- 当前板升级前，明确刷写命令和受影响分区；任何可能写入 `userdata` 的命令都不能执行。

所有构建及传输中间产物遵守 [存储路径约定](storage-paths.md)，不写 `/tmp`。
