# RAG 引用预览改动说明

更新日期：2026-09-15。本文记录本仓库对 LightRAG 引用展示与文档预览所做的扩展；此前为提高问答准确性进行的评测、检索与生成修改见 [RAG 准确性回归记录](rag-accuracy-validation.md)。

## 用户现在看到什么

1. 回答末尾的 `References` 按同一次上传的文档合并为一行：例如 `.kg.md` 和 `.text.md` 同源时显示 `工程部署指南.md · 2 处命中`。引用链接携带所有命中的 chunk ID，阅读栏仍能切换它们；查询 API 的原始 `references` 列表仍按证据 chunk 返回，避免丢失评测所需的追溯数据。
2. 点击引用时，问答页面保持原位，右侧打开 Markdown 阅读栏。上方是可读的证据卡片（章节和短摘录），下方是保留前后文的完整入库文档；点击卡片切换位置。命中 chunk 以浅色底和左侧细线标出，不使用大面积黄色高亮；手机窄屏时阅读栏占满屏幕。
3. 同一回答中、同一上传文档的多个命中在上方显示为多张证据卡片。入库路径和 chunk ID 收在“检索详情”中，也保留“打开整页”的入口。阅读栏的背景、文字、边框、muted、primary 和圆角跟随 LightRAG WebUI 的主题变量，文档 iframe 的明暗模式跟随网页设置而不是操作系统设置。
4. 历史回答中的旧 `/query/references/{chunk_id}` 链接仍可被阅读栏识别。不存在的 chunk 返回 `404`，不通过任意路径读取板端文件。

例如《工程部署指南.md》这次查询命中 `.kg` 与 `.text` 两条入库路径。它们的 `full_doc_id` 不同，但文档状态中的上传 `track_id` 相同，所以回答末尾只显示一份文档，阅读栏保留两处命中；不同批次上传的同名文件不会因此合并。没有可查的上传信息时保守地不合并。历史回答中的旧 chunk 级引用继续可用。

## 实现位置

| 位置 | 改动 |
| --- | --- |
| `core/lightrag-extensions/rk_chunk_citations.py` | 为保留下来的证据 chunk 分配 `reference_id`，带出 `file_path`、`chunk_id` 和可识别的章节。 |
| `core/lightrag-extensions/rk_reference_markdown.py` | 生成回答末尾的引用链接，隐藏 `.kg`、`.text` 入库后缀。 |
| `core/lightrag-extensions/rk_reference_preview.py` | 提供有大小上限的 chunk 元数据、上传分组标识，以及安全的 Markdown 整页渲染与高亮。 |
| `core/lightrag-extensions/install_lightrag_document_reference_footer_hook.py` | 查出引用 chunk 所属的真实上传批次，在回答尾注中按文档合并；真正流式生成时在答案 token 之后查，不延迟首字。缓存命中或非流式响应会在返回完整回答前查；原始证据 API 不变。 |
| `core/lightrag-extensions/install_lightrag_reference_preview_hook.py`、`install_lightrag_reference_group_hook.py` | 给 LightRAG 查询路由增加 chunk 元数据和整页阅读接口；分组标识通过 `full_doc_id → doc_status.track_id` 获取。 |
| `core/lightrag-extensions/webui/reference-reader.js` | 处理网页引用点击、右侧阅读栏、同一回答内的文档分组和命中位置切换。 |
| `core/lightrag-extensions/webui/query-status-banner.js` | 移除旧的新标签页点击拦截；仍负责查询状态和既有网页默认参数。 |
| `scripts/internal/install-lightrag-extensions.sh` | 在安装 LightRAG 扩展时同步 Python 模块、安装接口 Hook，并将阅读栏脚本加入 WebUI。 |

阅读接口：`GET /query/references/{chunk_id}` 返回 chunk 元数据；`GET /query/references/{chunk_id}/view` 返回完整的 Markdown 阅读页。页面中的原始 HTML 被禁用，引用 ID 被校验，不使用客户端传入的文件路径读取文档。

## 已验证

- 扩展测试共 37 项通过，两个 WebUI 脚本通过 JavaScript 语法检查；板端真实 mix 查询返回 2 个 chunk 证据，但尾注只显示 1 份《工程部署指南.md》（2 处命中），链接能在阅读栏切换两处原文。
- 162 的 ADB 板端 LightRAG 服务保持 `active`；阅读栏脚本和整页接口均可通过板端 HTTP 地址访问。
- 《工程部署指南》的 `.kg` chunk 与 `.text` chunk 返回相同的 `source_group_id`，并且各自的阅读页能够定位、高亮一处命中；未知 chunk 返回 `404`。

视觉调整参考了 [Google 对 NotebookLM 引用交互的说明](https://blog.google/innovation-and-ai/products/notebooklm-new-features-availability/)：点击引用后在原文上下文中检查命中证据。这里借鉴的是交互层次，并非复制 NotebookLM 配色或声称已有逐句引用能力；阅读栏继续沿用当前 WebUI 的样式系统。

## 当前边界与下一步

- **同一份文档只显示一行，但仍有多个命中。** 链接带上全部 chunk ID，阅读栏逐处展示；生成上下文里的 chunk 引用编号和查询 API 尚未按文档重新编号，所以文档行保留第一处命中的编号（例如后续文档可能为 `[3]`）。逐句引用如需同一套编号，必须在生成上下文时同步改为文档级 ID。
- **预览的是入库版本，不一定是原始上传文件。** 当前普通 Markdown 上传会分流为 `.kg`/`.text`，随后删除原始 MD；旧文档因此无法精确回到原始 MD 的段落。要实现真正的原文定位，需要保留原件并记录分流段落到原文的映射；已有文档若无原件则需重新入库。
- **高亮范围是证据 chunk，不是逐句引用。** 当前 `References` 表示检索后保留的证据，不保证回答的每句话都直接使用了该 chunk。逐句引用需要另做答案与证据对齐、校验。
- 阅读栏目前作为官方 WebUI 静态资源的独立扩展安装，尚未移入上游 React 源码。重建官方 WebUI 静态文件后，需要重新安装本仓库的 WebUI 扩展。

相关提交：`4da0a86`（结构化引用尾注）、`4145785`（隐藏入库后缀）、`36fc95e`（chunk 预览）、`7709bb6`（Markdown 整页高亮）、`98b8fa7`（旧链接兼容）、`197c2f7`（上传分组标识）、`4225b07`（右侧阅读栏）、`ee06a32`（阅读栏内去重标题）。
