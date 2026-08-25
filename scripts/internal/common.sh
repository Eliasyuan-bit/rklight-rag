#!/usr/bin/env bash
# Shared terminal diagnostics for deployment scripts. This file is sourced.

if [[ -t 2 ]]; then
  _C_RESET=$'\033[0m'
  _C_RED=$'\033[1;31m'
  _C_YELLOW=$'\033[1;33m'
  _C_CYAN=$'\033[1;36m'
else
  _C_RESET=''
  _C_RED=''
  _C_YELLOW=''
  _C_CYAN=''
fi

error() { printf '%s[错误]%s %s\n' "$_C_RED" "$_C_RESET" "$*" >&2; }
warning() { printf '%s[提示]%s %s\n' "$_C_YELLOW" "$_C_RESET" "$*" >&2; }
hint() { printf '%s[操作]%s %s\n' "$_C_CYAN" "$_C_RESET" "$*" >&2; }

require_variables() {
  local missing=() name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || missing+=("$name")
  done
  ((${#missing[@]} == 0)) && return 0
  error "缺少必需环境变量：${missing[*]}"
  return 1
}
