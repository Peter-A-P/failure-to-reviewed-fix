"""Test suite for mend.

A package rather than a loose directory so that `from tests.fixtures import ...` resolves
to exactly one module name. Without it both pytest and mypy can reach the same file as
`fixtures` and as `tests.fixtures`, and mypy refuses.
"""
