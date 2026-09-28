# Workspace storage rules

- Do not write project files, staging files, logs, PID files, downloads, test artifacts, or build artifacts to `/tmp` on the development host, host 172.16.15.162, or the board. Do not rely on the default `mktemp` or Python `tempfile` location; set `TMPDIR` to a managed directory before using them.
- On this development host, use `runtime/tmp/` for disposable project work and other named directories under `runtime/` for logs or generated state. `runtime/` is ignored by Git.
- On host 172.16.15.162, use `/home/rockchip-yn/data/rklight-rag-stage/` for transfer and build staging. On the board, use `/userdata/rklight-rag/runtime/` for disposable application work.
- `/userdata/lightrag-data/` is the existing knowledge base, including the built UCM630x index. Treat it as preserved data: do not clear, rebuild, replace, or include it in a firmware image or staging cleanup unless the user explicitly requests that operation.
- Before invoking a third-party build or test tool, check whether it writes to `/tmp` implicitly and redirect its temporary directory when possible. If this cannot be controlled, stop and ask rather than run it.
- Do not delete or move existing `/tmp` contents as part of this policy; they may belong to other processes or users.
