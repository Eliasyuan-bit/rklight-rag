# 脚本目录

日常只使用以下三个入口：

| 脚本 | 作用 |
| --- | --- |
| `setup-board.sh` | 从交叉编译到板端 WebUI 启动的完整部署入口。 |
| `setup-model-services.sh` | 只构建、打包并部署 RK1828 的 LLM、Embedding 和 Reranker 服务。 |
| `deploy-lightrag.sh` | 模型服务已准备好时，仅部署官方 LightRAG、Hook、PDF 解析器与 WebUI。 |

三个入口都应通过 `bash scripts/<name>.sh` 在 x86 开发机执行。

`internal/` 存放由入口脚本调用的原子步骤：配置校验、子模块同步、核心代码推送、PDF sidecar 构建、上游 LightRAG 安装、Hook 安装、启动和验证。不要在日常部署中逐一调用它们。

板端实际安装的启动器位于 `../core/board-launcher/start-rklight-rag`；部署后路径为 `/userdata/rklight-rag/bin/start-rklight-rag`。
