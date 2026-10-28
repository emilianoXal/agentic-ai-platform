#!/usr/bin/env bash
# Build the Strands Lambda layer tree (committed, not built in CI).
#
# The CI terraform image has no python/pip, so run this once locally. It
# produces modules/agent/layers/strands/python/ which is committed so
# archive_file can zip it at plan time.
set -euo pipefail

cd "$(dirname "$0")"

# Install the Strands SDK for the python3.12 x86_64 Lambda runtime.
python3 -m pip install -r requirements.txt \
  --target python \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --python-version 3.12 \
  --implementation cp

# Drop SDK packages the python3.12 Lambda runtime already provides so the
# layer stays thin and never shadows the runtime copies.
rm -rf \
  python/boto3 \
  python/botocore \
  python/s3transfer \
  python/dateutil \
  python/jmespath \
  python/urllib3
rm -rf python/*.dist-info/RECORD
