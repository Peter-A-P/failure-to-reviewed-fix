"""The film's sound track, synthesised: a soft pad under the whole film, and a sound for each
thing that happens on screen, timed by the schedule video/film.html draws to (its T).

- each test that fails: a dull tick and a low note;
- the failures fly into tickets: a sweep, and a note as each ticket lands; the biggest rises;
- locating: a soft tick as the scan passes each file, a bright note when it locks;
- the new test runs: a rising sweep, and a thud when it fails;
- the fix: a falling sweep as the old line is struck, notes climbing as the new one types,
  a two-note chime when the test passes;
- the review: a scanning sweep, and a marimba chord for the verdict;
- the comment: a wooden note for each line and each chip;
- the result: a swell landing on the headline with a low impact and a bell chord, a note per
  card, and a long bell under the address.

The instruments are the ones project 17's film uses. 48 kHz stereo, peak at -1 dBFS. numpy only.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

SR = 48_000
Arr = npt.NDArray[np.float64]

# A minor pentatonic from A4 up: the graph features' pass climbs it.
SCALE = [440.0, 523.25, 587.33, 659.26, 783.99, 880.0, 1046.5, 1174.66, 1318.51, 1567.98, 1760.0]


def _t(n: int) -> Arr:
    return np.arange(n) / SR


def pluck(freq: float, dur: float = 0.9, decay: float = 5.0, bright: float = 0.35) -> Arr:
    """A plucked note: a fundamental with two soft harmonics and an exponential decay."""
    t = _t(int(dur * SR))
    tone = (
        np.sin(2 * np.pi * freq * t)
        + bright * np.sin(4 * np.pi * freq * t)
        + 0.12 * np.sin(6 * np.pi * freq * t)
    )
    env = np.minimum(t / 0.006, 1.0) * np.exp(-decay * t)
    out: Arr = tone * env
    return out


def thud(freq: float = 82.0, dur: float = 0.45) -> Arr:
    t = _t(int(dur * SR))
    out: Arr = (
        np.sin(2 * np.pi * freq * t * (1 - 0.25 * t)) * np.minimum(t / 0.004, 1) * np.exp(-9 * t)
    )
    return out


def tick(rng: np.random.Generator, dur: float = 0.05) -> Arr:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    smooth = np.convolve(noise, np.ones(12) / 12, mode="same")  # a soft click, not a hiss
    out: Arr = smooth * np.exp(-60 * _t(n))
    return out


def sweep(f0: float, f1: float, dur: float) -> Arr:
    t = _t(int(dur * SR))
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t * t / (2 * dur))
    env = np.sin(np.pi * t / dur) ** 2
    out: Arr = np.sin(phase) * env
    return out


def bell(freq: float, dur: float = 3.0, index: float = 2.2, ratio: float = 1.41) -> Arr:
    """An FM bell: a carrier modulated at an inharmonic ratio, the brightness fading first."""
    t = _t(int(dur * SR))
    mod = index * np.exp(-2.5 * t) * np.sin(2 * np.pi * freq * ratio * t)
    env = np.minimum(t / 0.003, 1.0) * np.exp(-1.6 * t)
    out: Arr = np.sin(2 * np.pi * freq * t + mod) * env
    return out


def marimba(freq: float, dur: float = 0.8) -> Arr:
    """A wooden note: the fundamental, a fourth partial and a little of the tenth, dying fast."""
    t = _t(int(dur * SR))
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(8 * np.pi * freq * t) * np.exp(-25 * t)
    tone += 0.06 * np.sin(20 * np.pi * freq * t) * np.exp(-40 * t)
    out: Arr = tone * np.minimum(t / 0.002, 1.0) * np.exp(-7 * t)
    return out


def impact(dur: float = 1.8) -> Arr:
    """A low hit: a sine falling from 62 to 41 Hz under a short soft burst."""
    t = _t(int(dur * SR))
    f = 41 + 21 * np.exp(-6 * t)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-2.2 * t)
    rng = np.random.default_rng(3)
    burst = np.convolve(rng.standard_normal(len(t)), np.ones(24) / 24, mode="same") * np.exp(
        -30 * t
    )
    out: Arr = (body + 0.6 * burst) * np.minimum(t / 0.002, 1.0)
    return out


def riser(dur: float) -> Arr:
    """A swell that grows to its end: soft noise and a tone rising an octave, cut at the top."""
    t = _t(int(dur * SR))
    rng = np.random.default_rng(5)
    noise = np.convolve(rng.standard_normal(len(t)), np.ones(16) / 16, mode="same")
    tone = np.sin(2 * np.pi * (220 * t + 220 * t * t / (2 * dur)))
    out: Arr = (0.7 * noise + 0.5 * tone) * (t / dur) ** 2.5
    return out


def pad(dur: float, chord: list[float], fade: float) -> Arr:
    t = _t(int(dur * SR))
    out = np.zeros_like(t)
    for i, f in enumerate(chord):
        lfo = 0.75 + 0.25 * np.sin(2 * np.pi * (0.13 + 0.05 * i) * t + i)
        out += lfo * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 1.003 * t))
    env = np.minimum(np.minimum(t / fade, 1.0), np.minimum((dur - t) / fade, 1.0))
    res: Arr = out / len(chord) * env
    return res


def track(
    fails: int,
    tickets: list[int],
    suspects: int,
    seconds: float,
    slow: float = 1.0,
    hold: tuple[float, float] = (0.0, 0.0),
) -> tuple[Arr, Arr]:
    """Left and right channels. Times are film.html's T: fail 0, group 3.0, locate 6.0,
    prove 8.4, fix 10.8, challenge 13.8, post 16.4, result 18.8, each played `slow` times slower."""
    n = int(seconds * SR)
    left, right = np.zeros(n), np.zeros(n)
    rng = np.random.default_rng(10)

    def film(at: float) -> float:  # film seconds for film.html's time, with the hold
        return at * slow + (hold[1] if hold[1] and at >= hold[0] else 0.0)

    def add(sig: Arr, at: float, gain: float, pan: float = 0.0) -> None:
        i = int(film(at) * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        left[i:j] += sig[: j - i] * gain * (1 - pan) ** 0.5
        right[i:j] += sig[: j - i] * gain * (1 + pan) ** 0.5

    # The pad: A minor while the story is told, a brighter D major under the result.
    add(pad(film(19.4), [110.0, 164.81, 220.0, 261.63], 1.0), 0.0, 0.10)
    add(pad(seconds - film(18.8), [73.42, 146.83, 220.0, 329.63, 369.99], 1.2), 18.8, 0.11)

    # 1. Each failure, as its row turns red (0.75 + 0.17 i s).
    for i in range(fails):
        at = 0.75 + 0.17 * i
        add(tick(rng), at, 0.5, -0.4 + 0.8 * i / max(fails - 1, 1))
        add(pluck(SCALE[0] / 4 * (1 + 0.06 * (i % 3)), 0.5, 8, 0.1), at, 0.10)

    # 2. The dots fly into tickets, the tickets land, the biggest rises to the middle.
    add(sweep(300, 700, 1.1), 3.15, 0.07)
    for ti, size in enumerate(tickets):
        add(
            pluck(SCALE[ti] / 2, 0.7, 6, 0.3),
            4.0 + 0.06 * ti,
            0.08 + 0.02 * size,
            -0.6 + 1.2 * ti / max(len(tickets) - 1, 1),
        )
    add(sweep(160, 330, 0.8), 4.6, 0.06)
    add(pluck(SCALE[4], 1.0, 4, 0.4), 5.4, 0.12)

    # 3. The scan passes each file, then locks on the one at fault.
    for i in range(suspects):
        add(tick(rng), 6.5 + 0.9 * i / max(suspects - 1, 1), 0.3, 0.2)
    add(pluck(SCALE[6], 1.2, 3.5, 0.5), 7.5, 0.16)
    add(pluck(SCALE[8], 1.2, 3.5, 0.3), 7.56, 0.08, 0.3)

    # 4. The new test runs on the broken code and fails.
    add(sweep(200, 520, 0.7), 9.1, 0.06)
    add(thud(), 9.85, 0.5)
    add(pluck(SCALE[0] / 2, 0.8, 5, 0.1), 9.85, 0.12)

    # 5. The old line is struck, the new one types in, the test passes.
    add(sweep(700, 300, 0.4), 11.6, 0.05)
    for k in range(6):
        add(tick(rng, 0.03), 12.05 + 0.1 * k, 0.25, -0.3 + 0.12 * k)
    add(marimba(SCALE[5]), 12.8, 0.18, -0.2)
    add(marimba(SCALE[7]), 12.95, 0.18, 0.2)

    # 6. The other company's model checks it, and accepts it.
    add(sweep(400, 900, 1.1), 14.5, 0.05, 0.3)
    for f, pan in ((587.33, -0.3), (739.99, 0.0), (880.0, 0.3)):
        add(marimba(f), 15.72, 0.12, pan)

    # 7. The comment: a note per line, then per chip.
    add(pluck(SCALE[3], 0.8, 5, 0.3), 16.5, 0.10)
    for i in range(3):
        add(marimba(SCALE[4 + i]), 16.95 + 0.22 * i, 0.10, -0.3 + 0.3 * i)
    for i in range(3):
        add(marimba(SCALE[6 + i]), 17.7 + 0.25 * i, 0.12, -0.35 + 0.35 * i)

    # The result: the swell lands on the headline (film.html scales it in from 19.2 s).
    add(riser(1.1), 19.25 - 1.1, 0.05)
    add(impact(), 19.25, 0.22)
    for f, pan in ((587.33, -0.4), (739.99, 0.0), (880.0, 0.4)):
        add(bell(f, 3.2, 1.2), 19.25, 0.045, pan)
    for i, (f, pan) in enumerate(((880.0, -0.35), (1046.5, 0.0), (1174.66, 0.35))):
        add(marimba(f), 20.1 + 0.3 * i, 0.15, pan)
    # The last bell lands with the footer, "Every number..." (film.html fades it in from 21.85 s).
    add(bell(293.66, 4.0, 1.4, 2.0), 21.9, 0.16)
    add(bell(1174.66, 3.0, 1.0), 21.95, 0.04, 0.2)

    # A little room: three soft echoes, a fade at the end, then normalise.
    for d, gain in ((0.083, 0.22), (0.131, 0.15), (0.197, 0.1)):
        k = int(d * SR)
        left[k:] += gain * right[:-k]
        right[k:] += gain * left[:-k]
    tail = np.minimum(1.0, (seconds - _t(n)) / 0.6)
    left, right = left * tail, right * tail
    peak = max(np.abs(left).max(), np.abs(right).max())
    scale = 10 ** (-1 / 20) / peak
    return left * scale, right * scale


def write_wav(path: Path, left: Arr, right: Arr) -> None:
    pcm = (np.stack([left, right], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
