#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${APP_DIR}/dist"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BUNDLE_DIR="${DIST_DIR}/pocket-web-${STAMP}"
TAR_PATH="${DIST_DIR}/pocket-web-${STAMP}.tar.gz"
MANIFEST_PATH="${DIST_DIR}/deployment-manifest-${STAMP}.json"

mkdir -p "${BUNDLE_DIR}/static/vendor" "${DIST_DIR}"

cp "${APP_DIR}/server.py" "${BUNDLE_DIR}/server.py"
cp "${APP_DIR}/run-pocket-web.sh" "${BUNDLE_DIR}/run-pocket-web.sh"
cp "${APP_DIR}/package-pocket-web.sh" "${BUNDLE_DIR}/package-pocket-web.sh"
cp "${APP_DIR}/requirements.txt" "${BUNDLE_DIR}/requirements.txt"
cp "${APP_DIR}/DATA.md" "${BUNDLE_DIR}/DATA.md"
cp "${APP_DIR}/LICENSE-CODE" "${BUNDLE_DIR}/LICENSE-CODE"
cp "${APP_DIR}/LICENSE-DATA" "${BUNDLE_DIR}/LICENSE-DATA"
cp "${APP_DIR}/static/index.html" "${BUNDLE_DIR}/static/index.html"
cp "${APP_DIR}/static/detail.html" "${BUNDLE_DIR}/static/detail.html"
cp "${APP_DIR}/static/app.js" "${BUNDLE_DIR}/static/app.js"
cp "${APP_DIR}/static/detail.js" "${BUNDLE_DIR}/static/detail.js"
cp "${APP_DIR}/static/styles.css" "${BUNDLE_DIR}/static/styles.css"
cp "${APP_DIR}/static/vendor/3Dmol-min.js" "${BUNDLE_DIR}/static/vendor/3Dmol-min.js"
cp "${APP_DIR}/static/vendor/3Dmol-min.js.LICENSE.txt" "${BUNDLE_DIR}/static/vendor/3Dmol-min.js.LICENSE.txt"

cat > "${MANIFEST_PATH}" <<EOF
{
  "bundle_created_at_utc": "${STAMP}",
  "app_dir": "${APP_DIR}",
  "startup_command": "bash ${APP_DIR}/run-pocket-web.sh",
  "web_port": 8766,
  "code_bundle": "${TAR_PATH}",
  "data_bundle": "see DATA.md; the resource bundle is distributed separately",
  "required_external_paths": {}
}
EOF

tar -C "${DIST_DIR}" -czf "${TAR_PATH}" "$(basename "${BUNDLE_DIR}")"
rm -rf "${BUNDLE_DIR}"

echo "Created code bundle: ${TAR_PATH}"
echo "Created manifest: ${MANIFEST_PATH}"
