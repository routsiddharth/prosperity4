#!/bin/bash
# Quick runner: tests every *.py in this dir, prints one-line summary per file.
cd "$(dirname "$0")"
for f in test*.py; do
    [ -f "$f" ] || continue
    out=$(prosperity4btest "$f" 1 --merge-pnl --no-out --no-progress 2>&1 | tail -20)
    total=$(echo "$out" | grep '^Total profit:' | tail -1 | awk -F: '{print $2}' | tr -d ' ,')
    aco_days=$(echo "$out" | grep 'ASH_COATED_OSMIUM:' | awk -F: '{print $2}' | tr -d ' ,' | paste -sd+ - | bc)
    ipr_days=$(echo "$out" | grep 'INTARIAN_PEPPER_ROOT:' | awk -F: '{print $2}' | tr -d ' ,' | paste -sd+ - | bc)
    printf "%-40s  total=%8s  ACO=%7s  IPR=%7s\n" "$f" "$total" "$aco_days" "$ipr_days"
done
