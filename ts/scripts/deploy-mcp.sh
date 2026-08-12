#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
requested_ref="${1:-HEAD}"
source_commit="$(git rev-parse --verify "${requested_ref}^{commit}")"
deploy_root="${LAKATOTREE_MCP_DEPLOY_ROOT:-${repo_root}/.runtime/mcp}"

case "${deploy_root}" in
  ""|"/"|"${repo_root}"|"${repo_root}/")
    echo "refusing unsafe deployment root: ${deploy_root}" >&2
    exit 2
    ;;
esac

work_root="$(mktemp -d "${TMPDIR:-/tmp}/lakatotree-mcp-build.XXXXXX")"
cleanup() {
  rm -rf -- "${work_root}"
}
trap cleanup EXIT

source_root="${work_root}/source"
artifact_root="${work_root}/artifact"
mkdir -p "${source_root}" "${artifact_root}" "${deploy_root}"

git archive "${source_commit}" | tar -x -C "${source_root}"
pnpm --dir "${source_root}/ts" install --frozen-lockfile --ignore-scripts
pnpm --dir "${source_root}/ts" verify

cp -R "${source_root}/ts/dist" "${artifact_root}/dist"
mkdir -p "${artifact_root}/spec"
cp "${source_root}/ts/spec/tool-surface.v0.json" "${artifact_root}/spec/tool-surface.v0.json"
cp "${source_root}/ts/package.json" "${artifact_root}/package.json"
cp "${source_root}/ts/pnpm-lock.yaml" "${artifact_root}/pnpm-lock.yaml"
cp "${source_root}/ts/pnpm-workspace.yaml" "${artifact_root}/pnpm-workspace.yaml"
printf '%s\n' "${source_commit}" > "${artifact_root}/SOURCE_COMMIT"
pnpm --dir "${artifact_root}" install --prod --frozen-lockfile --ignore-scripts
node "${source_root}/ts/scripts/smoke-mcp-artifact.mjs" \
  "${artifact_root}/dist/entrypoints/mcp.js"

payload_digest() {
  local root="$1"
  (
    cd "${root}"
    find dist spec -type f -print
    printf '%s\n' package.json pnpm-lock.yaml pnpm-workspace.yaml SOURCE_COMMIT
  ) | LC_ALL=C sort | while IFS= read -r path; do
    printf '%s  %s\n' "$(sha256sum "${root}/${path}" | cut -d ' ' -f 1)" "${path}"
  done | sha256sum | cut -d ' ' -f 1
}

artifact_digest="$(payload_digest "${artifact_root}")"
printf '%s\n' "${artifact_digest}" > "${artifact_root}/ARTIFACT_SHA256"

destination="${deploy_root}/${source_commit}"
if [[ -e "${destination}" ]]; then
  [[ -f "${destination}/ARTIFACT_SHA256" ]] && \
    [[ "$(cat "${destination}/ARTIFACT_SHA256")" == "${artifact_digest}" ]] || {
    echo "existing deployment differs for commit ${source_commit}" >&2
    exit 3
  }
  node "${source_root}/ts/scripts/smoke-mcp-artifact.mjs" \
    "${destination}/dist/entrypoints/mcp.js"
else
  mv "${artifact_root}" "${destination}"
  chmod -R a-w "${destination}"
fi

next_link="${deploy_root}/.current.$$.tmp"
ln -s "${source_commit}" "${next_link}"
mv -Tf "${next_link}" "${deploy_root}/current"
printf '%s\n' "${destination}/dist/entrypoints/mcp.js"
