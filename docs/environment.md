# 环境与配置说明

本项目的配置分为四类。不要把模型权重路径、构建机工具链和板端服务配置混在同一个文件里。

| 类别 | 位置 | 生效位置 | 用途 |
| --- | --- | --- | --- |
| 部署目标 | `deploy/board.env` | x86 开发机 | 指定 ADB 目标和板端安装目录。 |
| LightRAG 运行时 | `deploy/lightrag.env` | RK3588 板端 | 指定 WebUI、数据目录、本地模型 Gateway 和检索参数。 |
| 交叉编译环境 | 当前 Shell 环境变量 | x86 开发机 | 构建 RK1828 模型服务与 RK3588 PDF sidecar。 |
| 模型资产 | 各服务的 `models/` | RK3588 板端 | 存放 `.rknn`、`.weight`、词表和 embedding 表。 |

`deploy/board.env` 与 `deploy/lightrag.env` 包含机器相关配置和可能的密钥，不提交到 Git；从 `.example` 创建即可。

## 1. 部署目标：`deploy/board.env`

在 x86 开发机创建：

```bash
cp deploy/board.env.example deploy/board.env
```

当前板端的最小示例：

```bash
export ADB_SERIAL=172.16.15.195:5555

export BOARD_APP_ROOT=/userdata/rklight-rag
export BOARD_DATA_ROOT=/userdata/lightrag-data

# cloud：官方 MinerU；rkvision：本地 PDFium + DocLayout-YOLO + PPOCRv6。
export PDF_PARSER_MODE=rkvision

export LLM_SERVICE_ROOT=/userdata/RK1828-qwen3.5-9b-2cards-service
export VECTOR_SERVICE_ROOT=/userdata/RK1828-qwen3-embedding-reranker-service
export PPOCR_SERVICE_ROOT=/userdata/ppocrv6-rknn-service
export LAYOUT_SERVICE_ROOT=/userdata/doclayout-yolo-rknn-service
```

`ADB_SERIAL` 是唯一必须按目标板修改的字段。执行 `adb -s "$ADB_SERIAL" get-state` 应返回 `device`。

## 2. LightRAG：`deploy/lightrag.env`

创建文件：

```bash
cp deploy/lightrag.env.example deploy/lightrag.env
```

通常保留默认值；需要关注的字段为：

| 字段 | 默认值 | 作用 |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `9621` | WebUI 与 API 监听地址。 |
| `WORKING_DIR` | `/userdata/lightrag-data` | LightRAG 知识库、图谱、向量和缓存数据目录。 |
| `LLM_MODEL` | `qwen3.5-9b-110k` | Gateway 暴露的本地 LLM 名称。 |
| `EMBEDDING_MODEL` | `qwen3-embedding-0.6b` | Gateway 暴露的本地向量模型名称。 |
| `RERANK_MODEL` | `qwen3-reranker-0.6b` | Gateway 暴露的本地重排模型名称。 |
| `OPENAI_LLM_MAX_COMPLETION_TOKENS` | `1024` | 单次回答最大生成 token 数。 |

若 `PDF_PARSER_MODE=cloud`，还必须在该文件中加入：

```bash
MINERU_API_TOKEN=<你的 MinerU API Token>
```

若使用 `rkvision`，不需要 MinerU Token。

## 3. RK1828 模型服务的交叉编译变量

这些变量只在执行一键构建的 x86 Shell 中设置，不写入 `board.env`：

```bash
export RKNN3_MODEL_ZOO_ROOT=/home/yn/sdk/182x/rknn/rknn3-model-zoo
export GCC_COMPILER=<path-to-aarch64-gcc>
```

脚本从 `GCC_COMPILER` 自动推导同目录的 `g++`。只有 GCC 与 G++ 不遵循标准同名规则时，才需要显式设置 `RK1828_C_COMPILER`、`RK1828_CXX_COMPILER` 两个完整路径。

模型服务的一键入口为：

```bash
bash scripts/setup-model-services.sh
```

## 4. 本地 RKVision PDF sidecar 的构建变量

只有 `PDF_PARSER_MODE=rkvision` 时需要。以下变量是**构建机路径**，不是板端 `/userdata` 路径：

```bash
export RK3588_SDK_ROOT=/path/to/rk3588-sdk
export PDFIUM_ROOT=/path/to/pdfium-aarch64
export RK_VISION_PPOCR_SERVICE_ROOT=/path/to/RK3588-ppocrv6-service
export RK_VISION_DOCLAYOUT_SERVICE_ROOT=/path/to/RK3588-docling-service
```

这两个变量明确表示主机上的已构建服务目录；不要使用 `board.env` 的 `PPOCR_SERVICE_ROOT`、`LAYOUT_SERVICE_ROOT`，后两者是板端目录。

## 5. 板端模型文件布局

模型权重不由部署脚本复制，应预先放在各服务目录内：

```text
/userdata/RK1828-qwen3.5-9b-2cards-service/
└── models/qwen3.5-9b/

/userdata/RK1828-qwen3-embedding-reranker-service/
├── models/qwen3-embedding-0.6b/
└── models/qwen3-reranker-0.6b/
```

服务自身的 `config/*.json` 已使用上述绝对路径。不要再在 `/userdata` 顶层创建单独的 Qwen 模型目录。
