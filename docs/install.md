# 安装与部署

## 前置条件

- 四个模型服务已按各自仓库完成交叉编译、模型准备和板端部署；
- 主机可通过 ADB 连接 RK3588；
- 板端可访问 Git 仓库和 Python 软件源，且 `python3 -m pip` 可用；
- 使用 `rkvision` 时，主机还需准备 RK3588 工具链与 PDFium。

模型权重、RKNN 文件、词表和知识库数据不由本仓库传输。

## 构建 RK1828 模型服务

在 x86 开发机执行，不在 RK3588 板端执行。先提供 RKNN3 model-zoo 与 aarch64 交叉编译器：

```bash
export RKNN3_MODEL_ZOO_ROOT=/path/to/rknn3-model-zoo
export RK1828_C_COMPILER=/path/to/aarch64-linux-gnu-gcc
export RK1828_CXX_COMPILER=/path/to/aarch64-linux-gnu-g++
```

模型权重需预先放入各服务目录的 `models/` 下。使用公开入口可一条命令完成构建、打包和 ADB 推送：

```bash
bash scripts/setup-model-services.sh
```

加 `--verify` 会额外在板端初始化两卡 Qwen3.5-9B 并执行 daemon 冒烟验证。

## 配置

```bash
git clone --recurse-submodules <this-repository-url> rklight-rag
cd rklight-rag
cp deploy/board.env.example deploy/board.env
cp deploy/lightrag.env.example deploy/lightrag.env
```

编辑 `deploy/board.env`：ADB 设备、板端目录、模型服务目录和 `PDF_PARSER_MODE`。

编辑 `deploy/lightrag.env`：模型名称、端口和模型 gateway 配置。云端 PDF 解析还需设置：

```bash
MINERU_API_TOKEN=<your_mineru_api_key>
```

## 一键部署

完整部署（模型服务 + LightRAG WebUI）使用：

```bash
bash scripts/setup-board.sh --pdf-parser rkvision
```

`setup-board.sh` 在 x86 开发机执行；它先交叉编译、打包并 ADB 部署两个 RK1828 模型服务，再执行下方的 LightRAG 编排安装。若暂时使用 MinerU 云端 PDF 解析，将参数改为 `--pdf-parser cloud`。

仅部署已准备好模型服务的 LightRAG 编排时，使用：

```bash
# 默认：MinerU 官方云端解析 PDF
bash scripts/deploy-lightrag.sh --pdf-parser cloud

# 可选：RK3588 本地 RKVision 解析 PDF
bash scripts/deploy-lightrag.sh --pdf-parser rkvision
```

`deploy-lightrag.sh` 依次初始化子模块、检查 ADB、同步编排代码、安装固定版本的官方 LightRAG、安装 Hook、启动服务并验证健康状态。`rkvision` 模式额外构建和部署 Document Vision。

## PDF 解析模式

| 模式 | LightRAG 规则 | 前置条件 |
| --- | --- | --- |
| `cloud` | `pdf:mineru-R,*:legacy-R` | `MINERU_API_TOKEN` |
| `rkvision` | `pdf:rkvision-R,*:legacy-R` | 本地 PDFium、DocLayout-YOLO、PPOCRv6 |

解析 profile 位于 `deploy/parser-profiles/`。RKVision 通过 `lightrag.parsers` entry point 注册为第三方 Parser；当前输出阅读顺序文本，因此使用 `R` 分块。

## 官方 LightRAG

上游仓库与固定提交在 `deploy/lightrag-upstream.env`：

```bash
LIGHTRAG_UPSTREAM_URL=https://github.com/HKUDS/LightRAG.git
LIGHTRAG_UPSTREAM_REVISION=7ecd8a0512c1f5b221456b24de225a71e1e002d8
```

安装脚本会克隆该提交并执行 `python3 -m pip install -e ".[api]"`。固定提交保证 Hook 的目标文件和锚点保持可验证；升级上游前应重新验证 Hook 安装、上传和查询。

## 脚本入口

| 命令 | 适用场景 |
| --- | --- |
| `bash scripts/setup-board.sh --pdf-parser rkvision` | 完整本地部署。 |
| `bash scripts/setup-model-services.sh` | 只构建并部署 RK1828 模型服务。 |
| `bash scripts/deploy-lightrag.sh --pdf-parser cloud` | 模型服务已准备好时，只安装 LightRAG WebUI 与编排。 |

`scripts/internal/` 是上述入口调用的内部步骤，不作为日常操作入口。
