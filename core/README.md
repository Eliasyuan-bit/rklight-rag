# Core deployment code

此目录由 rklight-rag 主仓库维护，不拆分为独立 Git 仓库。

- model-gateway：管理三类 RK1828 JSONL daemon，并提供 LightRAG 使用的本地 HTTP 接口。
- ingest-router：将 Markdown 路由为 P 与 P! 两类 LightRAG 原生输入。
- document-vision：PDFium、DocLayout-YOLO 与 PPOCRv6 的本地文档视觉处理程序。
- lightrag-extensions：针对固定 LightRAG 上游版本的上传、文档分组、查询 FIFO 与 WebUI 扩展安装器。
