# fixtures/phase1/stubborn/iter3.py
def parse_duration(s: str) -> int:
    if not s:
        raise ValueError("empty")
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    raise ValueError(f"bad duration: {s}")  # still no combined "1h30m"
