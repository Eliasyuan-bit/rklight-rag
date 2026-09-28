#!/usr/bin/env python3
"""Make the engineered document retrieval path the LightRAG API default."""
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "# RK3588_DEFAULT_QUERY_MODE_V5"
OLD_MARKERS = (
    "# RK3588_DEFAULT_QUERY_MODE_V4",
    "# RK3588_DEFAULT_QUERY_MODE_V3",
    "# RK3588_DEFAULT_QUERY_MODE_V2",
    "# RK3588_DEFAULT_QUERY_MODE_V1",
)
ANCHOR = '''    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = Field(
        default="mix",
        description="Query mode",
    )
'''
INSERT = '''    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = Field(
        default=os.getenv("RK_DEFAULT_QUERY_MODE", "mix"),
        description="Query mode",
    )
    # RK3588_DEFAULT_QUERY_MODE_V5
'''
USER_PROMPT_ANCHOR = '''    user_prompt: Optional[str] = Field(
        default=None,
        max_length=MAX_QUERY_CHARS,
        description="User-provided prompt for the query. If provided, this will be used instead of the default value from prompt template.",
    )
'''
USER_PROMPT_INSERT = '''    user_prompt: Optional[str] = Field(
        default=os.getenv("RK_DEFAULT_USER_PROMPT") or None,
        max_length=MAX_QUERY_CHARS,
        description="User-provided prompt for the query. If provided, this will be used instead of the default value from prompt template.",
)
'''
MIX_BUDGET_ANCHOR = '''            param.max_entity_tokens = min(param.max_entity_tokens or 500, 500)
            param.max_relation_tokens = min(param.max_relation_tokens or 300, 300)
'''
MIX_BUDGET_V3 = MIX_BUDGET_ANCHOR + '''            # Direct diagnostic questions are grounded by reranked source
            # passages. Broad graph descriptions can attach a neighbouring
            # test item's cause to the requested item, especially with a 2B
            # answer model, so do not render KG records for this query class.
            diagnostic_terms = ("错误", "故障", "失败", "异常", "为什么", "原因")
            if any(term in self.query.casefold() for term in diagnostic_terms):
                param.max_entity_tokens = 0
                param.max_relation_tokens = 0
'''
MIX_BUDGET_INSERT = MIX_BUDGET_ANCHOR + '''            # Direct diagnostic and exact lexical questions are grounded by
            # source passages. Broad graph descriptions can attach a related
            # but unsupported command or test item, especially with a 2B
            # answer model, so do not render KG records for these query types.
            from lightrag.rk_lexical_retrieval import query_retrieval_profile
            diagnostic_terms = ("错误", "故障", "失败", "异常", "为什么", "原因")
            if (
                any(term in self.query.casefold() for term in diagnostic_terms)
                or query_retrieval_profile(self.query)
                in ("exact", "document_fact")
            ):
                param.max_entity_tokens = 0
                param.max_relation_tokens = 0
'''


def inject_diagnostic_budget(source: str) -> str:
    if 'in ("exact", "document_fact")' in source:
        return source
    old_exact_condition = 'or query_retrieval_profile(self.query) == "exact"'
    if old_exact_condition in source:
        return source.replace(
            old_exact_condition,
            'or query_retrieval_profile(self.query)\n'
            '                in ("exact", "document_fact")',
            1,
        )
    if MIX_BUDGET_V3 in source:
        return source.replace(MIX_BUDGET_V3, MIX_BUDGET_INSERT, 1)
    if "diagnostic_terms =" in source:
        raise SystemExit("unsupported LightRAG source; unknown diagnostic budget block")
    if source.count(MIX_BUDGET_ANCHOR) != 1:
        raise SystemExit("unsupported LightRAG source; expected one mix budget anchor")
    return source.replace(MIX_BUDGET_ANCHOR, MIX_BUDGET_INSERT, 1)


def install(path: Path) -> None:
    source = path.read_text()
    if MARKER in source:
        print(f"already installed: {path}")
        return
    old_marker = next((value for value in OLD_MARKERS if value in source), None)
    if old_marker:
        if old_marker == OLD_MARKERS[-1]:
            if source.count(USER_PROMPT_ANCHOR) != 1:
                raise SystemExit("unsupported LightRAG source; expected one user prompt anchor")
            source = source.replace(USER_PROMPT_ANCHOR, USER_PROMPT_INSERT, 1)
        source = inject_diagnostic_budget(source)
        source = source.replace(old_marker, MARKER, 1)
        path.write_text(source)
        print(f"upgraded: {path}")
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit(
            f"unsupported LightRAG source; expected one query mode anchor, got {source.count(ANCHOR)}"
        )
    backup = path.with_suffix(path.suffix + ".before-rk3588-query-default")
    if not backup.exists():
        backup.write_text(source)
    source = source.replace(ANCHOR, INSERT, 1)
    if source.count(USER_PROMPT_ANCHOR) != 1:
        raise SystemExit("unsupported LightRAG source; expected one user prompt anchor")
    source = source.replace(USER_PROMPT_ANCHOR, USER_PROMPT_INSERT, 1)
    path.write_text(inject_diagnostic_budget(source))
    print(f"installed: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    install(args.path)


if __name__ == "__main__":
    main()
