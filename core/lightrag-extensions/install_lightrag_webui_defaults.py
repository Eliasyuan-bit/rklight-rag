#!/usr/bin/env python3
"""Reproduce the board's bounded LightRAG WebUI query defaults."""

from pathlib import Path
import sys


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Expected one upstream anchor in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def install(webui_root: Path) -> None:
    settings = webui_root / "src/stores/settings.ts"
    query_settings = webui_root / "src/components/retrieval/QuerySettings.tsx"

    replace_once(
        settings,
        """        top_k: 40,
        chunk_top_k: 20,
        max_entity_tokens: 6000,
        max_relation_tokens: 8000,
        max_total_tokens: 30000,""",
        """        top_k: 10,
        chunk_top_k: 5,
        max_entity_tokens: 1000,
        max_relation_tokens: 1000,
        max_total_tokens: 3600,""",
    )
    replace_once(settings, "      version: 21,", "      version: 23,")

    replace_once(
        settings,
        """        return state
      }
    }
  )
)""",
        """        if (version < 22) {
          // Keep previous browser settings within the RK1828 context window.
          state.querySettings = {
            ...state.querySettings,
            top_k: 10,
            chunk_top_k: 5,
            max_entity_tokens: 1000,
            max_relation_tokens: 1000,
            max_total_tokens: 2800,
            stream: true,
            enable_rerank: true,
          }
        }
        if (version < 23) {
          state.querySettings = {
            ...state.querySettings,
            max_total_tokens: 3600,
          }
        }
        return state
      }
    }
  )
)""",
    )

    replace_once(
        query_settings,
        """    top_k: 40,
    chunk_top_k: 20,
    max_entity_tokens: 6000,
    max_relation_tokens: 8000,
    max_total_tokens: 30000""",
        """    top_k: 10,
    chunk_top_k: 5,
    max_entity_tokens: 1000,
    max_relation_tokens: 1000,
    max_total_tokens: 3600""",
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: install_lightrag_webui_defaults.py WEBUI_ROOT")
    install(Path(sys.argv[1]))
