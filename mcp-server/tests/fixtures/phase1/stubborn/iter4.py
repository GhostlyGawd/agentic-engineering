# fixtures/phase1/stubborn/iter4.py
import re

_UNIT = {"h": 3600, "m": 60, "s": 1}
_TOKEN = re.compile(r"(\d+)([hms])")


def parse_duration(s: str) -> int:
    if not s or not s.strip():
        raise ValueError("empty duration")
    pos = 0
    total = 0
    matched = False
    for m in _TOKEN.finditer(s):
        if m.start() != pos:
            raise ValueError(f"bad duration: {s!r}")
        total += int(m.group(1)) * _UNIT[m.group(2)]
        pos = m.end()
        matched = True
    if not matched or pos != len(s):
        raise ValueError(f"bad duration: {s!r}")
    return total
