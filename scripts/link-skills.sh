#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"

mkdir -p "${SKILLS_DIR}"

while IFS= read -r skill_md; do
    skill_dir="$(dirname "${skill_md}")"
    skill_name="$(basename "${skill_dir}")"
    target="${SKILLS_DIR}/${skill_name}"
    # Remove existing real directory so ln -sfn replaces it, not nests inside it
    if [[ -d "${target}" && ! -L "${target}" ]]; then
        rm -rf "${target}"
    fi
    ln -sfn "${skill_dir}" "${target}"
    echo "linked ${skill_name}"
done < <(find "${REPO_ROOT}" -mindepth 3 -maxdepth 3 -name "SKILL.md")
