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
failed_files=()
passed_files=()

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
  "$root_dir/tc" "$source_path" -o "$executable" 2>&1 | tee "$compile_log"
  compile_status=${PIPESTATUS[0]}
  if grep -q 'tc: falling back to tersec.py' "$compile_log"; then
    fallback_count=$((fallback_count + 1))
  fi
  if ((compile_status != 0)); then
    printf 'FAIL build %s\n' "$relative_path" >&2
    failed=$((failed + 1))
    failed_files+=("BUILD $relative_path")
    continue
  fi
  compiled=$((compiled + 1))

  printf 'RUN   %s\n' "$relative_path"
  if (cd "$root_dir" && "$executable"); then
    run_status=$?
    ran=$((ran + 1))

    # Parse expectations from source file
    expectations_found=false
    expect_exit_code=0
    expect_stdout_lines=()
    expect_not_stdout_lines=()

    while IFS= read -r line; do
      if [[ $line =~ ^[[:space:]]*\/\/[[:space:]]*EXPECT-EXIT:[[:space:]]*(.*)$ ]]; then
        expectations_found=true
        expect_exit_code="${BASH_REMATCH[1]}"
      elif [[ $line =~ ^[[:space:]]*\/\/[[:space:]]*EXPECT-STDOUT:[[:space:]]*(.*)$ ]]; then
        expectations_found=true
        expect_stdout_lines+=("${BASH_REMATCH[1]}")
      elif [[ $line =~ ^[[:space:]]*\/\/[[:space:]]*EXPECT:[[:space:]]*(.*)$ ]]; then
        expectations_found=true
        expect_stdout_lines+=("${BASH_REMATCH[1]}")
      elif [[ $line =~ ^[[:space:]]*\/\/[[:space:]]*EXPECT-NOT:[[:space:]]*(.*)$ ]]; then
        expectations_found=true
        expect_not_stdout_lines+=("${BASH_REMATCH[1]}")
      fi
    done < "$source_path"

    if $expectations_found; then
      # Capture actual output
      actual_output=$(cd "$root_dir" && "$executable" 2>/dev/null)
      actual_exit=$?

      # Check exit code
      if [[ $actual_exit -ne $expect_exit_code ]]; then
        printf 'FAIL %s (exit code: expected %d, got %d)\n' "$relative_path" "$expect_exit_code" "$actual_exit" >&2
        failed=$((failed + 1))
        failed_files+=("EXIT   $relative_path (expected $expect_exit_code, got $actual_exit)")
        continue
      fi

      # Check EXPECT-NOT lines must not appear
      if [[ ${#expect_not_stdout_lines[@]} -gt 0 ]]; then
        not_found_mismatch=false
        for not_expected in "${expect_not_stdout_lines[@]}"; do
          if [[ "$actual_output" == *"$not_expected"* ]]; then
            printf 'FAIL %s (expected NOT to contain "%s", but it did)\n' "$relative_path" "$not_expected" >&2
            not_found_mismatch=true
            break
          fi
        done
        if $not_found_mismatch; then
          failed=$((failed + 1))
          failed_files+=("OUTPUT $relative_path (unexpected content)")
          continue
        fi
      fi

      # Check EXPECT lines must appear in order in the output
      if [[ ${#expect_stdout_lines[@]} -gt 0 ]]; then
        # Split actual output into lines
        actual_lines=()
        while IFS= read -r line; do
          actual_lines+=("$line")
        done <<< "$actual_output"

        # Match expected lines in order (extra output lines allowed)
        actual_idx=0
        mismatch=false
        for expected in "${expect_stdout_lines[@]}"; do
          found=false
          while [[ $actual_idx -lt ${#actual_lines[@]} ]]; do
            if [[ "${actual_lines[$actual_idx]}" == "$expected" ]]; then
              found=true
              actual_idx=$((actual_idx + 1))
              break
            fi
            actual_idx=$((actual_idx + 1))
          done
          if ! $found; then
            printf 'FAIL %s (expected "%s" not found in output)\n' "$relative_path" "$expected" >&2
            mismatch=true
            break
          fi
        done

        if $mismatch; then
          failed=$((failed + 1))
          failed_files+=("OUTPUT $relative_path (content mismatch)")
          continue
        fi
      fi

      printf 'PASS %s\n' "$relative_path"
      passed_files+=("$relative_path")
    else
      # No expectations specified, just check it runs
      printf 'PASS %s (no expectations)\n' "$relative_path"
      passed_files+=("$relative_path")
    fi
  else
    printf 'FAIL run %s\n' "$relative_path" >&2
    failed=$((failed + 1))
    failed_files+=("RUN   $relative_path")
  fi
done

printf '\nSummary: %d compiled, %d ran, %d skipped, %d failures, %d fallbacks\n' \
  "$compiled" "$ran" "$skipped" "$failed" "$fallback_count"

if [[ ${#passed_files[@]} -gt 0 ]]; then
  printf '\nPassed files:\n'
  for entry in "${passed_files[@]}"; do
    printf '  %s\n' "$entry"
  done
fi

if ((failed > 0)); then
  printf '\nFailed files:\n' >&2
  for entry in "${failed_files[@]}"; do
    printf '  %s\n' "$entry" >&2
  done
  exit 1
fi