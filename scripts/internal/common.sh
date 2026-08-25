#!/usr/bin/env bash
# Shared terminal diagnostics for deployment scripts. This file is sourced.

if [[ -t 2 ]]; then
  _C_RESET=$'\033[0m'
  _C_RED=$'\033[1;31m'
  _C_YELLOW=$'\033[1;33m'
  _C_CYAN=$'\033[1;36m'
  _C_GREEN=$'\033[1;32m'
else
  _C_RESET=''
  _C_RED=''
  _C_YELLOW=''
  _C_CYAN=''
  _C_GREEN=''
fi

error() { printf '%s[ERROR]%s %s\n' "$_C_RED" "$_C_RESET" "$*" >&2; }
warning() { printf '%s[WARNING]%s %s\n' "$_C_YELLOW" "$_C_RESET" "$*" >&2; }
hint() { printf '%s[ACTION]%s %s\n' "$_C_CYAN" "$_C_RESET" "$*" >&2; }
step() { printf '%s==> %s%s\n' "$_C_YELLOW" "$*" "$_C_RESET"; }
success() { printf '%s[OK]%s %s\n' "$_C_GREEN" "$_C_RESET" "$*"; }

require_variables() {
  local missing=() name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || missing+=("$name")
  done
  ((${#missing[@]} == 0)) && return 0
  error "Missing required environment variables: ${missing[*]}"
  return 1
}
