# fixtures/phase1/stubborn/iter2.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 100   # BUG: minutes are 60s, not 100s
    raise ValueError(f"bad duration: {s}")
