import re
from pathlib import Path


FRONTEND_SOURCE = Path(__file__).resolve().parents[1] / "frontend" / "src"
FORBIDDEN_COMMERCIAL_METERING_COPY = (
    re.compile(r"(?:字符包|文字包|字包)"),
    re.compile(r"(?:消耗|扣除)\s*(?:\$\{[^}]+\}|\d+)\s*(?:字符|字数|字)"),
    re.compile(r"(?:确认扣除字数|模型消耗|扣费|充值|购买额度|账户余额)"),
)


def test_frontend_has_no_commercial_text_package_or_metering_copy() -> None:
    violations: list[str] = []
    for path in sorted(FRONTEND_SOURCE.rglob("*.ts")):
        if path.name.endswith(".test.ts"):
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_COMMERCIAL_METERING_COPY:
            if pattern.search(source):
                violations.append(f"{path.name}: {pattern.pattern}")

    assert violations == []
