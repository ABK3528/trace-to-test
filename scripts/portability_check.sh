#!/usr/bin/env bash
# 扫机制层（core/ checks/ skills/），出现禁用词即失败。
# 退出码：0 = 零命中；1 = 有命中；2 = 配置缺失。
set -euo pipefail
cd "$(dirname "$0")/.."

WORDS="scripts/business_words.txt"
WHITELIST="scripts/portability_whitelist.txt"
SCAN_DIRS=(core checks skills)

[[ -f "$WORDS" ]] || { echo "missing $WORDS" >&2; exit 2; }
[[ -f "$WHITELIST" ]] || { echo "missing $WHITELIST" >&2; exit 2; }

# 只扫存在的目录——分阶段落地时 skills/ 可能还没建
existing=()
for d in "${SCAN_DIRS[@]}"; do [[ -d "$d" ]] && existing+=("$d"); done
[[ ${#existing[@]} -gt 0 ]] || { echo "no scan dirs exist yet"; exit 0; }

# 词表 → 一个 alternation 正则；跳过空行与注释
pattern=$(grep -vE '^\s*(#|$)' "$WORDS" | paste -sd'|' -)
[[ -n "$pattern" ]] || { echo "word list is empty"; exit 0; }

hits=$(grep -rInE -i "\\b(${pattern})\\b" "${existing[@]}" 2>/dev/null || true)

# 逐条套白名单
if [[ -f "$WHITELIST" ]] && [[ -n "$hits" ]]; then
  while IFS=$'\t' read -r re _reason; do
    [[ -z "${re:-}" || "$re" == \#* ]] && continue
    hits=$(printf '%s\n' "$hits" | grep -vE -- "$re" || true)
  done < "$WHITELIST"
fi

if [[ -n "${hits// /}" ]]; then
  echo "🔴 portability check FAILED — 机制层出现业务词：" >&2
  printf '%s\n' "$hits" >&2
  exit 1
fi
echo "✅ portability check passed (${existing[*]})"
