"""The benchmark subset: sampled once, stratified, and not resampled afterwards.

The rule this protects is "report the hit rate as it falls": the subset is chosen before
the first run and its ids committed, with no excluding hard tasks after the fact. The
tests worth writing are therefore about the refusals and about coverage, not about the
sampling arithmetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mend.data.swebench import Task, allocate, load_subset, load_tasks, sample, write_subset


def tasks(counts: dict[str, int]) -> list[Task]:
    return [
        Task(
            instance_id=f"{repo.replace('/', '__')}-{i}",
            repo=repo,
            base_commit=f"{i:040d}",
            problem_statement=f"something is wrong in {repo}",
        )
        for repo, n in counts.items()
        for i in range(n)
    ]


SKEWED = {"django/django": 200, "sympy/sympy": 80, "astropy/astropy": 12, "pylint/pylint": 3}


def test_every_repository_survives_stratification() -> None:
    """The mitigation in PLAN.md section 8: a run cut short still covers every repository."""
    allocation = allocate(SKEWED, 40)
    assert sum(allocation.values()) == 40
    assert all(count >= 1 for count in allocation.values())
    assert set(allocation) == set(SKEWED)


def test_allocation_follows_the_population() -> None:
    allocation = allocate(SKEWED, 40)
    assert allocation["django/django"] > allocation["sympy/sympy"]
    assert allocation["sympy/sympy"] > allocation["pylint/pylint"]


def test_allocation_never_asks_for_more_than_a_repository_has() -> None:
    allocation = allocate(SKEWED, 120)
    for repo, count in allocation.items():
        assert count <= SKEWED[repo]


def test_allocation_refuses_an_impossible_request() -> None:
    with pytest.raises(ValueError, match="cannot sample"):
        allocate(SKEWED, 1000)
    with pytest.raises(ValueError, match="at least"):
        allocate(SKEWED, 2)


def test_sampling_is_reproducible_from_the_seed() -> None:
    """The difference between sampling before the run as a claim and as a fact."""
    population = tasks(SKEWED)
    first = sample(population, size=40, seed=7, source="verified")
    second = sample(population, size=40, seed=7, source="verified")
    assert first.instance_ids == second.instance_ids

    different = sample(population, size=40, seed=8, source="verified")
    assert different.instance_ids != first.instance_ids


def test_a_subset_records_how_it_was_drawn() -> None:
    subset = sample(tasks(SKEWED), size=40, seed=7, source="SWE-bench Verified")
    assert len(subset) == 40
    assert subset.seed == 7
    assert subset.sampled_at
    assert subset.source == "SWE-bench Verified"
    assert sum(subset.per_repo.values()) == 40


def test_a_committed_subset_is_not_overwritten(tmp_path: Path) -> None:
    """Resampling after seeing results, even innocently, is what this refusal prevents."""
    path = tmp_path / "subset.json"
    subset = sample(tasks(SKEWED), size=40, seed=7, source="verified")
    write_subset(subset, path)

    with pytest.raises(FileExistsError, match="already holds a committed subset"):
        write_subset(sample(tasks(SKEWED), size=40, seed=9, source="verified"), path)


def test_a_subset_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "subset.json"
    subset = sample(tasks(SKEWED), size=40, seed=7, source="verified")
    write_subset(subset, path)
    assert load_subset(path).instance_ids == subset.instance_ids


def test_the_task_type_cannot_carry_hidden_tests(tmp_path: Path) -> None:
    """Hidden tests are never read (PLAN.md section 2.1).

    The dataset row carries them; Task has no field they could be lifted into, so a model
    prompt built from a Task cannot contain them even by accident.
    """
    path = tmp_path / "tasks.jsonl"
    row = {
        "instance_id": "django__django-1",
        "repo": "django/django",
        "base_commit": "abc",
        "problem_statement": "bug",
        "PASS_TO_PASS": ["tests.test_a"],
        "FAIL_TO_PASS": ["tests.test_secret"],
        "patch": "the gold patch",
        "test_patch": "the hidden tests",
        # Harness 5.x also embeds the hidden test patch and its test command here.
        "eval_script": "git apply the hidden tests && run them",
        "image": "swebench/sweb.eval.x86_64.django_1776_django-1:latest",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    loaded = load_tasks(path)[0]
    fields = set(type(loaded).__dataclass_fields__)
    assert "FAIL_TO_PASS" not in fields
    assert "test_patch" not in fields
    assert "patch" not in fields
    assert "hidden" not in " ".join(fields)
    assert "eval_script" not in fields
    assert "the hidden tests" not in repr(loaded)
    # The image is not hidden: it is the broken commit's environment, which the harness
    # pulls by this name.
    assert loaded.image == row["image"]

    serialised = json.dumps({k: getattr(loaded, k) for k in fields})
    assert "hidden tests" not in serialised
    assert "gold patch" not in serialised


def test_there_is_no_way_to_filter_the_subset() -> None:
    """Guard against the excluding-hard-tasks flag that would one day seem reasonable.

    Scans the module source for the shape it would take. Blunt, and cheaper than finding
    out from a reader that the headline number was computed over a convenient subset.
    """
    import mend.data.swebench as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("def exclude", "exclude_ids", "skip_failed", "drop_hard", "def filter"):
        assert forbidden not in source, f"{forbidden} would let the subset be trimmed after a run"


def test_the_validation_split_and_the_main_run_partition_the_draw() -> None:
    from mend.data.swebench import split_validation

    tasks = [
        Task(
            instance_id=f"{repo.split('/')[1]}-{i}",
            repo=repo,
            base_commit="c",
            problem_statement="",
        )
        for repo, n in (("a/a", 40), ("b/b", 20), ("c/c", 5))
        for i in range(n)
    ]
    drawn = sample(tasks, size=30, seed=7, source="test")
    validation, main = split_validation(tasks, drawn, validation_size=10)
    assert set(validation.instance_ids) | set(main.instance_ids) == set(drawn.instance_ids)
    assert not set(validation.instance_ids) & set(main.instance_ids)
    assert len(validation) == 10 and len(main) == 20
    assert set(validation.per_repo) == {"a/a", "b/b", "c/c"}
    assert split_validation(tasks, drawn, validation_size=10) == (validation, main)
