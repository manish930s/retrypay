"""Coverage enforcement script for multi-tiered package thresholds.

Thresholds:
- Overall project coverage: >= 80%
- Core safety packages (retrypay.domain, retrypay.policy, retrypay.evaluation): >= 95%
"""

import json
import sys
from pathlib import Path

PACKAGE_THRESHOLDS = {
    "retrypay.domain": 95.0,
    "retrypay.policy": 95.0,
    "retrypay.evaluation": 95.0,
}

OVERALL_THRESHOLD = 80.0


def validate_coverage(coverage_file: Path) -> bool:
    """Validate JSON coverage report against multi-tiered thresholds."""
    if not coverage_file.exists():
        print(f"Error: Coverage file '{coverage_file}' not found.")
        return False

    with open(coverage_file, encoding="utf-8") as f:
        data = json.load(f)

    totals = data.get("totals", {})
    overall_percent = totals.get("percent_covered", 0.0)

    print("=" * 60)
    print("RETRYPAY MULTI-TIER COVERAGE REPORT")
    print("=" * 60)
    print(f"Overall Coverage: {overall_percent:.2f}% (Threshold: {OVERALL_THRESHOLD:.2f}%)")

    passed = True

    if overall_percent < OVERALL_THRESHOLD:
        print(f"FAIL: Overall coverage {overall_percent:.2f}% is below {OVERALL_THRESHOLD:.2f}%")
        passed = False
    else:
        print(f"PASS: Overall coverage meets {OVERALL_THRESHOLD:.2f}% threshold.")

    print("-" * 60)
    print("Package-Level Thresholds:")

    files = data.get("files", {})
    package_stats: dict[str, dict[str, int]] = {
        pkg: {"covered": 0, "total": 0} for pkg in PACKAGE_THRESHOLDS
    }

    for file_path, file_data in files.items():
        summary = file_data.get("summary", {})
        covered_lines = summary.get("covered_lines", 0)
        num_statements = summary.get("num_statements", 0)

        normalized_path = file_path.replace("\\", "/")

        for pkg in PACKAGE_THRESHOLDS:
            pkg_path = pkg.replace(".", "/")
            is_match = (
                f"/{pkg_path}/" in normalized_path
                or normalized_path.startswith(f"{pkg_path}/")
                or normalized_path.endswith(f"{pkg_path}.py")
            )
            if is_match:
                package_stats[pkg]["covered"] += covered_lines
                package_stats[pkg]["total"] += num_statements

    for pkg, required_pct in PACKAGE_THRESHOLDS.items():
        stats = package_stats[pkg]
        if stats["total"] == 0:
            pkg_pct = 100.0
        else:
            pkg_pct = (stats["covered"] / stats["total"]) * 100.0

        print(f"  - {pkg}: {pkg_pct:.2f}% (Required: {required_pct:.2f}%)")
        if pkg_pct < required_pct:
            print(f"    FAIL: {pkg} coverage {pkg_pct:.2f}% is below {required_pct:.2f}%")
            passed = False

    print("=" * 60)
    return passed


if __name__ == "__main__":
    report_path = Path("coverage.json") if len(sys.argv) < 2 else Path(sys.argv[1])
    success = validate_coverage(report_path)
    sys.exit(0 if success else 1)
