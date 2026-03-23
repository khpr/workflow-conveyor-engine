#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/state/WO-SMOKE.json"
STEPS="$ROOT/tests/steps.json"
BACKUP_DIR="$(cd "$ROOT/../.." && pwd)/var/backups"

rm -f "$STATE"

python3 "$ROOT/scripts/conveyor.py" init --flow FLOW-SMOKE --title "smoke test" --steps-json "$STEPS" --state "$STATE" >/dev/null

python3 "$ROOT/scripts/conveyor.py" tick --state "$STATE" >/dev/null
python3 "$ROOT/scripts/conveyor.py" tick --state "$STATE" >/dev/null

# should be done
python3 "$ROOT/scripts/conveyor.py" status --state "$STATE" \
  | python3 -c 'import json,sys; j=json.load(sys.stdin); assert j["done"] is True; print("OK done")'

# fuse dry-run should create backup tar
TMP_JSON="$(mktemp)"
python3 "$ROOT/scripts/conveyor.py" fuse --state "$STATE" --backup-dir "$BACKUP_DIR" --dry-run > "$TMP_JSON"
TMP_JSON="$TMP_JSON" python3 -c 'import json,os; j=json.load(open(os.environ["TMP_JSON"],"r",encoding="utf-8")); assert j["dry_run"] is True; p=j["backup"]; assert os.path.exists(p); print("OK fuse", p)'
rm -f "$TMP_JSON"
