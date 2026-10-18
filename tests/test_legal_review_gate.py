from types import SimpleNamespace

from src.api.main import _qualified_assignment_matches


def test_lawyer_verification_requires_matching_qualified_assignment():
    assignment = SimpleNamespace(
        reviewer_name="Elena Petrova",
        reviewer_jurisdiction="North Macedonia",
        qualification_reference="Bar register verification 2026-07-31",
    )

    assert _qualified_assignment_matches(assignment, "elena petrova")
    assert not _qualified_assignment_matches(assignment, "Different Reviewer")


def test_lawyer_verification_rejects_incomplete_or_missing_assignment():
    incomplete = SimpleNamespace(
        reviewer_name="Elena Petrova",
        reviewer_jurisdiction="North Macedonia",
        qualification_reference=None,
    )

    assert not _qualified_assignment_matches(incomplete, "Elena Petrova")
    assert not _qualified_assignment_matches(None, "Elena Petrova")
