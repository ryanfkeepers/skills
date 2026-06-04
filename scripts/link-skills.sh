#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"

mkdir -p "${SKILLS_DIR}"

# Remove any symlinks previously created by this script (pointing into this repo)
while IFS= read -r target; do
    link_dest="$(readlink "${target}")"
    if [[ "${link_dest}" == "${REPO_ROOT}"/* ]]; then
        rm "${target}"
        echo "removed symlink $(basename "${target}")"
    fi
done < <(find "${SKILLS_DIR}" -maxdepth 1 -type l)

while IFS= read -r skill_md; do
    skill_dir="$(dirname "${skill_md}")"
    skill_name="$(basename "${skill_dir}")"
    target="${SKILLS_DIR}/${skill_name}"
    rm -rf "${target}"
    cp -r "${skill_dir}" "${target}"
    echo "installed ${skill_name}"
done < <(find "${REPO_ROOT}" -mindepth 3 -maxdepth 3 -name "SKILL.md")

# Install shared resources
SHARED_SRC="${REPO_ROOT}/shared"
SHARED_DST="${HOME}/.claude/shared"
if [[ -d "${SHARED_SRC}" ]]; then
    rm -rf "${SHARED_DST}"
    cp -r "${SHARED_SRC}" "${SHARED_DST}"
    echo "installed shared"
fi
