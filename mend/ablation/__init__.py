"""The ablations (PLAN.md section 1, the last row): which parts of the design carry the result.

Each one takes a piece out and runs the rest unchanged, on tasks the main run already
attempted, so the comparison is paired task by task. They live here, outside mend.graph,
on purpose. The graph's state machine has no edge into a patch without a failing test and
refuses a review by the fixer's own vendor, and an ablation that removed either rail by a
flag on the graph would leave a switch in the shipped pipeline that turns its guarantees
off. An ablation here builds no IssueState past localisation, produces no Proposal, and
cannot be reached from mend.graph; what it writes is a record for the harness and the
release gate, nothing else.
"""
