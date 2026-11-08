# The site at triage.peterparker.ca

The site is `web/`: two pages (`index.html` and `architecture.html`) with `{{tokens}}` for
every measured number, one stylesheet, one script (`app.js`), two fonts, the link-preview card
(`og.png`), the host's configuration (`staticwebapp.config.json`) and `robots.txt`. There is no
backend, so hosting it is a file upload and one DNS record, the same path as the other project
pages on peterparker.ca, and it is styled like them.

**Every number comes from the committed results.** `mend site` writes
`data/site/values.json` (strings for the tokens) and `web/data.json` (the series the charts
draw) from the same files `mend report` writes the README's tables from, and from the live runs'
records in `results/live/`. `tools/site.py build` fills the tokens, refuses one with no value
and refuses a value no page uses; `tools/site.py check` refuses an unfilled token, inline script
or style, an off-site request, typographic dashes and a missing card. When a result changes,
run `mend report`, then `mend site`, and commit the README, `data/site/` and `web/data.json`
together. In ci, `tests/test_site.py` fails if the committed numbers have fallen behind the
results, if the page asks for a number it is not given, or if the script looks for an element
the page does not have.

`tools/site.py` is the portfolio's shared site builder, copied unchanged so it can be refreshed;
ruff leaves it alone for that reason. The architecture page is rendered from
`docs/architecture.md` and its four diagrams, which are generated from a specification, not
drawn.

**The walk-through** on the front page is 03's live run of 2026-10-31, read from
`results/live/ai-release-gate-41237394546/`: the failing tests and the tickets are recomputed
from its JUnit report by the same capture and clustering the workflow ran, and the test, the
patch and the review are the run's own record.

**The film** at the top of the page is 36 seconds, with sound, of that same run.
`video/film.html` draws one frame for a time t from `web/data.json` and `data/site/values.json`;
`video/render.py` screenshots it at 30 frames a second in a headless Edge, encodes the frames
with the track `video/sound.py` synthesises (the instruments project 17's film uses) and writes
`web/video/film.mp4` and its poster, committed, with `film.json`, a fingerprint of the numbers
it drew. `tests/test_site.py` fails when those numbers move and the film was not rendered
again:

    uv run --no-project --with playwright --with imageio-ffmpeg --with numpy python video/render.py

`--social` writes the cut with the site's address on its last screen to `video/out/`, for
posting elsewhere. It replaced an in-page step-through animation that was too slow and too
static for a reader who is not technical.

**The content security policy allows this origin and nothing else**: no inline script, no style
attribute, no font, script or request from anywhere else. The fonts (Newsreader and Inter, SIL
Open Font License) are served from the site itself for that reason.

**Deployed 2026-11-08.** The app is `triage-peterparker-ca` in resource group `rg-portfolio-2`
(subscription `PAP-POCs 2`, East US 2, Free plan), served at
`lemon-island-02c9f730f.4.azurestaticapps.net`. The deploy token is the repository secret
`AZURE_STATIC_WEB_APPS_API_TOKEN`, the repository variable `SITE` is `on`, and
`.github/workflows/site.yml` builds, checks and uploads the site on every push to `main` that
changes it. Before upload the built page was served locally and rendered in Edge at 390, 768 and
1280 pixels in both themes. Cost: the Free plan, CA$0.
