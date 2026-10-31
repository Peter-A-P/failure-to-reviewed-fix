"""The live workflow: a failing CI run in one of Peter's repositories, triaged, and the
result posted as a comment on that pull request (PLAN.md section 2.7, docs/live.md).

Comments only. Whatever the router says, nothing here opens a pull request, pushes, or
merges; an auto-propose verdict is posted as a suggestion like any other. The scope check
(mend.live.scope) refuses every repository but the one the workflow runs in, and only
the ones listed there.
"""
