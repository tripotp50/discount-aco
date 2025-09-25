import json, os, time

CODES_PATH = "codes.json"
WL_FILES = [
    ("wl_5.txt", 5),
    ("wl_10.txt", 10),
    ("wl_15.txt", 15),
]

def read_lines(p):
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

1) load whitelist (union) with value mapping
value_by_code = {}
for p, v in WL_FILES:
    for code in read_lines(p):
        value_by_code[code] = v

if not value_bycode:
    raise SystemExit("No whitelist codes found. Check your wl*.txt files.")

print(f"Loaded {len(value_by_code)} whitelist codes.")

2) load codes.json
if not os.path.exists(CODES_PATH):
    raise SystemExit(f"Missing {CODES_PATH}")
with open(CODES_PATH, "r", encoding="utf-8") as f:
    original = json.load(f)

3) build pruned
pruned = {}
kept, dropped, added = 0, 0, 0
for code, val in value_by_code.items():
    if code in original:
        prev = original.get(code, {})
        pruned[code] = {"used": bool(prev.get("used", False)), "value": val}
        kept += 1
    else:
        pruned[code] = {"used": False, "value": val}
        added += 1

dropped = len(original) - kept

4) write backup and new file
backup = CODES_PATH.replace(".json", f".backup.{int(time.time())}.json")
with open(backup, "w", encoding="utf-8") as f:
    json.dump(original, f, indent=2)
with open(CODES_PATH, "w", encoding="utf-8") as f:
    json.dump(pruned, f, indent=2)

print(f"""
Done!
Kept (from original): {kept}
Added (new from whitelist): {added}
Dropped (not in whitelist): {dropped}
Final total: {len(pruned)}
Backup saved as: {backup}
""")