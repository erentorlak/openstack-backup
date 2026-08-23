from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
    ValidationReport,
)


def test_check_result_default_data() -> None:
    r = CheckResult(name="x", kind=CheckKind.STATE, status=CheckStatus.PASS, message="ok")
    assert r.data == {}


def test_report_passed_all_pass() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.SNAPSHOT,
        results=(
            CheckResult("a", CheckKind.ACCESS, CheckStatus.PASS, "ok"),
            CheckResult("b", CheckKind.STATE, CheckStatus.PASS, "ok"),
        ),
    )
    assert report.passed is True


def test_report_passed_false_on_fail() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.SNAPSHOT,
        results=(CheckResult("a", CheckKind.STATE, CheckStatus.FAIL, "boom"),),
    )
    assert report.passed is False


def test_report_by_kind_filters() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.BACKUP,
        results=(
            CheckResult("a", CheckKind.ACCESS, CheckStatus.PASS, "ok"),
            CheckResult("b", CheckKind.STATE, CheckStatus.FAIL, "boom"),
            CheckResult("c", CheckKind.STATE, CheckStatus.PASS, "ok"),
        ),
    )
    state = report.by_kind(CheckKind.STATE)
    assert [r.name for r in state] == ["b", "c"]
