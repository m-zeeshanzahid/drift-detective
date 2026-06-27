#!/usr/bin/env bash
# Build Lambda deployment ZIPs for all three functions.
#
# Terraform's archive_file data source already zips these directories at
# `terraform apply` time, so this script is OPTIONAL — use it only if you want
# to deploy a Lambda manually via the AWS CLI or test the packaging step.
#
# boto3 ships in the Lambda Python runtime, so no vendored dependencies are
# bundled; the handlers import only the standard library plus boto3.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FUNCTIONS=("drift_detector" "drift_classifier" "drift_remediator")

for fn in "${FUNCTIONS[@]}"; do
  echo "Packaging $fn ..."
  rm -f "${fn}.zip"
  (cd "$fn" && zip -qr "../${fn}.zip" . -x "*.pyc" "__pycache__/*")
  echo "  -> ${fn}.zip"
done

echo "Done. Built: ${FUNCTIONS[*]/%/.zip}"
