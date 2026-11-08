"""Render the site's short film: video/film.html drawn at 30 frames a second for 31 seconds,
each frame screenshot by a headless browser, the frames encoded to H.264 MP4 and
video/sound.py's track laid under them.

    uv run --no-project --with playwright --with imageio-ffmpeg --with numpy python video/render.py

The page reads web/data.json and data/site/values.json (written by `mend site`), so run that
first when the results change. It uses the machine's own Edge (Playwright's `channel`; pass
another as the first argument) and imageio-ffmpeg's bundled ffmpeg, so none needs installing.

Writes the page's cut to web/video/ (film.mp4 with sound, and its poster frame), committed,
with film.json, a fingerprint of the numbers it was drawn from: tests/test_site.py fails when
the site's numbers move and the film was not rendered again. `--social` writes the cut with
the address on its last screen to video/out/ instead (gitignored), for posting elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
# film.html's schedule is drawn on 24 seconds; the film plays it SLOW times slower.
SLOW = 1.3
SECONDS = 24.0 * SLOW
POSTER_AT = 20.9  # the result, with its three cards in, in film.html's time
# The site values film.html shows; only these stamp it, so a new test elsewhere does not.
USED = [
    "resolved",
    "tasks",
    "hit_pct",
    "auto_hit_pct",
    "auto_right",
    "auto_count",
    "cost_resolved",
    "wrong_pct",
]


def film_data() -> dict[str, Any]:
    """What film.html is drawn from: the followed run and the site's values."""
    data = json.loads((ROOT / "web" / "data.json").read_text(encoding="utf8"))
    values = json.loads((ROOT / "data" / "site" / "values.json").read_text(encoding="utf8"))
    return {"follow": data["follow"], "values": {k: values[k] for k in USED}}


def fingerprint(d: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def main() -> None:
    import imageio_ffmpeg  # type: ignore[import-untyped]
    from playwright.sync_api import sync_playwright

    social = "--social" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    channel = args[0] if args else "msedge"
    d = film_data()
    out = ROOT / "video" / "out" if social else ROOT / "web" / "video"
    out.mkdir(parents=True, exist_ok=True)
    frames = Path(tempfile.mkdtemp(prefix="film-frames-"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=channel)
            page = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.goto((ROOT / "video" / "film.html").as_uri())
            page.evaluate("d => { window.D = d; }", d)
            page.evaluate("k => { window.TIMING = k; }", {"site": not social})
            page.evaluate("document.fonts.ready")
            for i in range(round(SECONDS * FPS)):
                page.evaluate("t => render(t)", i / FPS / SLOW)
                page.screenshot(path=str(frames / f"f{i:04d}.png"))
            page.evaluate("t => render(t)", POSTER_AT)
            page.screenshot(path=str(out / "film-poster.jpg"), type="jpeg", quality=86)
            browser.close()

        sys.path.insert(0, str(Path(__file__).parent))
        import sound

        f = d["follow"]
        left, right = sound.track(
            len(f["failing"]), [t["size"] for t in f["tickets"]], len(f["suspects"]), SECONDS, SLOW
        )
        sound.write_wav(frames / "track.wav", left, right)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "f%04d.png"),
                "-i",
                str(frames / "track.wav"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "23",
                "-preset",
                "slow",
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar",
                "48000",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out / "film.mp4"),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(frames, ignore_errors=True)
    if not social:
        (out / "film.json").write_text(
            json.dumps({"fingerprint": fingerprint(d)}, indent=2) + "\n", encoding="utf8"
        )
    print(f"wrote film.mp4 and film-poster.jpg to {out}")


if __name__ == "__main__":
    main()
