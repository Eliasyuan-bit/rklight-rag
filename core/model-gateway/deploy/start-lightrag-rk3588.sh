#!/bin/sh
set -eu

cd /userdata/lightrag
exec lightrag-server --host 0.0.0.0 --port 9621
