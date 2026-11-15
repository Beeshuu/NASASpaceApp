import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
code = {m[0]: m[1] for m in re.findall(r'^(CRON_\w+) = "([^"]+)"', src, re.M)}
assert set(code) == {"CRON_MAINTENANCE", "CRON_REMINDER", "CRON_REPORT"}, code

text = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
text = re.sub(r'^\s*//.*$|(?<=[,{\[\s])//[^"\n]*$', "", text, flags=re.M)  # line comments
text = re.sub(r",(\s*[}\]])", r"\1", text)  # trailing commas
crons = json.loads(text)["triggers"]["crons"]
assert sorted(crons) == sorted(code.values()), (crons, code)
print("crons ok")
