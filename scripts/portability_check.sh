#!/usr/bin/env bash
# 扫机制层（core/ checks/ skills/），出现禁用词即失败。
# 退出码：0 = 零命中；1 = 有命中；2 = 配置/用法错误（含“扫了个寂寞”）。
#
# fail-open 路径必须堵死：空词表、零扫描目录、grep 搜索错误、白名单列错位。
# 白名单只豁免 (文件, 词) 二元组，绝不豁免整行。
set -euo pipefail
cd "$(dirname "$0")/.."

WORDS="scripts/business_words.txt"
WHITELIST="scripts/portability_whitelist.txt"
SCAN_DIRS=(core checks skills)

[[ -f "$WORDS" ]] || { echo "missing $WORDS" >&2; exit 2; }
[[ -f "$WHITELIST" ]] || { echo "missing $WHITELIST" >&2; exit 2; }

existing=()
for d in "${SCAN_DIRS[@]}"; do [[ -d "$d" ]] && existing+=("$d"); done
[[ ${#existing[@]} -gt 0 ]] || {
  echo "none of ${SCAN_DIRS[*]} exist — wrong tree?" >&2; exit 2; }

# Build the alternation while allowing an empty/comment-only file to reach the explicit error.
pattern=$(awk '!/^[[:space:]]*(#|$)/ { if (terms++) printf "|"; printf "%s", $0 }' "$WORDS")
[[ -n "$pattern" ]] || {
  echo "$WORDS has no terms — the gate would pass vacuously" >&2; exit 2; }

HITS=$(mktemp)
WINPUT=$(mktemp)
KEPT=$(mktemp)
trap 'rm -f "$HITS" "$WINPUT" "$KEPT"' EXIT

# Validate column structure with awk: bash read + tab IFS collapses adjacent whitespace delimiters.
awk -F '\t' -v out="$WINPUT" '
  /^[[:space:]]*(#|$)/ { next }
  {
    for (i = 1; i <= NF; i++) {
      if ($i == "") {
        printf "whitelist line %d: empty column\n", NR > "/dev/stderr"
        bad = 1; next
      }
    }
  }
  NF != 3 {
    printf "whitelist line %d: need exactly 3 tab-separated columns (path<TAB>term<TAB>reason), got %d\n", NR, NF > "/dev/stderr"
    bad = 1; next
  }
  $1 == "" || $2 == "" || $3 == "" {
    printf "whitelist line %d: empty column\n", NR > "/dev/stderr"
    bad = 1; next
  }
  { print > out }
  END { exit bad ? 1 : 0 }
' "$WHITELIST" || exit 2

# A regex must be valid and must not match the empty string: 1=valid/no match, 0=matches empty, 2=invalid.
check_re() {
  local re="$1" label="$2" rc
  set +e
  printf '\n' | grep -qE -- "$re" 2>/dev/null
  rc=$?
  set -e
  case $rc in
    1) return 0 ;;
    0) echo "whitelist $label matches the empty string ($re) — it would exempt everything" >&2; exit 2 ;;
    *) echo "whitelist $label is not a valid regex ($re)" >&2; exit 2 ;;
  esac
}

while IFS=$'\t' read -r path_re term_re _reason; do
  [[ -z "$path_re" ]] && continue
  check_re "$path_re" "path regex"
  check_re "$term_re" "term regex"
done < "$WINPUT"

# -o only emits matched terms; -H -n provides file:line:term.
set +e
grep -rHoEn -i "\\b(${pattern})\\b" "${existing[@]}" > "$HITS" 2>/dev/null
rc=$?
set -e
[[ $rc -le 1 ]] || { echo "grep failed with exit $rc" >&2; exit 2; }

if [[ ! -s "$HITS" ]]; then
  echo "✅ portability check passed (${existing[*]})"
  exit 0
fi

while IFS= read -r hit; do
  [[ -z "$hit" ]] && continue
  file=${hit%%:*}; rest=${hit#*:}; term=${rest#*:}
  exempt=0
  while IFS=$'\t' read -r path_re term_re _reason; do
    [[ -z "$path_re" ]] && continue
    if [[ "$file" =~ $path_re ]] && [[ "$term" =~ $term_re ]]; then exempt=1; break; fi
  done < "$WINPUT"
  [[ $exempt -eq 1 ]] || printf '%s\n' "$hit" >> "$KEPT"
done < "$HITS"

if [[ -s "$KEPT" ]]; then
  echo "🔴 portability check FAILED — 机制层出现业务词：" >&2
  cat "$KEPT" >&2
  exit 1
fi
echo "✅ portability check passed (${existing[*]})"
