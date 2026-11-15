import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import report

D = 86_400_000
T0 = 1_714_521_600_000  # 1 May 2024
daily = [{"day": T0 + i * D, "domain": "cardiovascular", "metric": "heart_rate", "avg": 60 + 2 * i, "n": 10} for i in range(7)]
daily += [{"day": T0 + i * D, "domain": "immune", "metric": "body_temperature", "avg": 36.7, "n": 10} for i in range(7)]
labels = {"cardiovascular/heart_rate": ("Heart rate", "bpm")}
md = report.weekly_report("okafor", T0, T0 + 7 * D, daily, [{"severity": "act", "message": "Heart rate high", "fired_ts": T0 + D}], 5, labels)
assert "# Weekly health report: okafor" in md and "1 May to 8 May" in md
assert "5 of 7 days" in md
assert "Heart rate: averaged 66.0 bpm, up over the week." in md
assert "Body temperature: averaged 36.7, steady over the week." in md
assert "2 May, act: Heart rate high" in md
empty = report.weekly_report("reyes", T0, T0 + 7 * D, [], [], 0, {})
assert "No readings were recorded this week." in empty and "No alerts this week." in empty
print("report ok")
