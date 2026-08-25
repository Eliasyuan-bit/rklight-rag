#!/bin/sh
set -eu

. /userdata/lightrag-rk1828-model-gateway/deploy/rk3588.env
exec python3 /userdata/lightrag-rk1828-model-gateway/rk1828_model_gateway.py
