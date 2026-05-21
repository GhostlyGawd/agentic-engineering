# fixtures/phase1/stubborn/iter1.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    return int(s.rstrip("s"))
