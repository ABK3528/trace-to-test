#!/usr/bin/env bash
# 扫机制层（core/ checks/ skills/），出现禁用词即失败。
# 退出码：0 = 零命中；1 = 有命中；2 = 配置/用法错误（含"扫了个寂寞"）。
#
# 🔴 三条 fail-open 路径必须堵死，否则这个闸会安静地绿：
#   ① 词表为空          → 闸没在守任何东西
#   ② 一个扫描目录都没有 → 脚本指错了地方（不是"干净"）
#   ③ grep 出错被 || true 吞掉 → 把"搜失败"当成"没搜到"
# 还有一条：白名单只豁免 (文件, 词) 二元组，绝不豁免整行。
set -euo pipefail
cd "$(dirname "$0")/.."

WORDS="scripts/business_words.txt"
WHITELIST="scripts/portability_whitelist.txt"
SCAN_DIRS=(core checks skills)

[[ -f "$WORDS" ]] || { echo "missing $WORDS" >&2; exit 2; }
[[ -f "$WHITELIST" ]] || { echo "missing $WHITELIST" >&2; exit 2; }

# 分阶段落地允许只存在一部分扫描目录（skills/ 后到），但一个都没有就是走错树了
existing=()
for d in "${SCAN_DIRS[@]}"; do [[ -d "$d" ]] && existing+=("$d"); done
[[ ${#existing[@]} -gt 0 ]] || {
  echo "none of ${SCAN_DIRS[*]} exist — wrong tree?" >&2; exit 2; }

pattern=$(awk '!/^[[:space:]]*(#|$)/ { if (terms++) printf "|"; printf "%s", $0 }' "$WORDS")
[[ -n "$pattern" ]] || {
  echo "$WORDS has no terms — the gate would pass vacuously" >&2; exit 2; }

# -o 只吐命中的词，-H -n 给 文件:行:词
set +e
hits=$(grep -rHoEn -i "\\b(${pattern})\\b" "${existing[@]}" 2>/dev/null)
rc=$?
set -e
# grep 约定：0 = 有命中，1 = 无命中，>=2 = 出错
[[ $rc -le 1 ]] || { echo "grep failed with exit $rc" >&2; exit 2; }

if [[ -z "$hits" ]]; then
  echo "✅ portability check passed (${existing[*]})"
  exit 0
fi

tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
while IFS= read -r hit; do
  [[ -z "$hit" ]] && continue
  file=${hit%%:*}; rest=${hit#*:}; term=${rest#*:}
  exempt=0
  while IFS=$'\t' read -r path_re term_re _reason; do
    [[ -z "${path_re:-}" || "$path_re" == \#* ]] && continue
    if [[ "$file" =~ $path_re ]] && [[ "$term" =~ $term_re ]]; then exempt=1; break; fi
  done < "$WHITELIST"
  [[ $exempt -eq 1 ]] || printf '%s\n' "$hit" >> "$tmp"
done <<< "$hits"

if [[ -s "$tmp" ]]; then
  echo "🔴 portability check FAILED — 机制层出现业务词：" >&2
  cat "$tmp" >&2
  exit 1
fi
echo "✅ portability check passed (${existing[*]})"
