#!/usr/bin/env bash
set -uo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
python_bin=${PYTHON:-python3}
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/terse-src.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT

files=()
while IFS= read -r -d '' source_path; do
  files+=("$source_path")
done < <(find "$root_dir/src" -type f -name '*.te' -print0 | sort -z)

if ((${#files[@]} == 0)); then
  printf 'No .te files found under src\n' >&2
  exit 1
fi

compiled=0
ran=0
skipped=0
failed=0
fallback_count=0

for source_path in "${files[@]}"; do
  relative_path=${source_path#"$root_dir/"}
  if ! grep -Eq '^[[:space:]]*go([[:space:]]|[({]|$)' "$source_path"; then
    printf 'SKIP %s (module; no go entrypoint)\n' "$relative_path"
    skipped=$((skipped + 1))
    continue
  fi

  executable_name=${relative_path#src/}
  executable_name=${executable_name//\//_}
  executable="$tmp_dir/$executable_name"
  compile_log="$tmp_dir/$executable_name.compile.log"
  printf '\nBUILD %s\n' "$relative_path"
#  if ! "$python_bin" "$root_dir/compiler/tersec.py" build "$source_path" -o "$executable"; then
  "$root_dir/tc" "$source_path" -o "$executable" 2>&1 | tee "$compile_log"
  compile_status=${PIPESTATUS[0]}
  if grep -q 'tc: falling back to tersec.py' "$compile_log"; then
    fallback_count=$((fallback_count + 1))
  fi
  if ((compile_status != 0)); then
    printf 'FAIL build %s\n' "$relative_path" >&2
    failed=$((failed + 1))
    continue
  fi
  compiled=$((compiled + 1))

  printf 'RUN   %s\n' "$relative_path"
  if (cd "$root_dir" && "$executable"); then
    ran=$((ran + 1))
  else
    printf 'FAIL run %s\n' "$relative_path" >&2
    failed=$((failed + 1))
  fi
done

printf '\nSummary: %d compiled, %d ran, %d skipped, %d failures, %d fallbacks\n' \
  "$compiled" "$ran" "$skipped" "$failed" "$fallback_count"
if ((failed > 0)); then
  exit 1
fi