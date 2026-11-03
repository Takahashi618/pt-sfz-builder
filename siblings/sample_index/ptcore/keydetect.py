from __future__ import annotations
import cmath
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
try:
    from .audiofile import read_audio_info, read_samples
    from .prep import pitch_shift_semitones
except ImportError:
    from audiofile import read_audio_info, read_samples
    from prep import pitch_shift_semitones
FRAME_SIZE = 2048
TARGET_RATE = 5512
MAX_FRAMES = 24
MIN_HZ = 130.0
MAX_HZ = 1000.0
SILENCE_RMS = 0.0001
HARMONIC_FIFTH = 0.33
HARMONIC_THIRD = 0.15
MAJOR_PROFILE = (5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0)
MINOR_PROFILE = (5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0)
PITCH_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
MARGIN_HIGH = 0.15
MARGIN_MEDIUM = 0.05

def fft(values: Sequence[complex]) -> List[complex]:
    n = len(values)
    if n & n - 1:
        raise ValueError('長さは 2 の冪である必要があります')
    a = list(values)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = (a[j], a[i])
    length = 2
    while length <= n:
        step = cmath.exp(-2j * math.pi / length)
        half = length // 2
        for start in range(0, n, length):
            w = 1 + 0j
            for k in range(start, start + half):
                u = a[k]
                v = a[k + half] * w
                a[k] = u + v
                a[k + half] = u - v
                w *= step
        length <<= 1
    return a
_HANN_CACHE: dict = {}

def _hann(n: int) -> List[float]:
    if n not in _HANN_CACHE:
        _HANN_CACHE[n] = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
    return _HANN_CACHE[n]

def frame_chroma(samples: Sequence[float], rate: int) -> Optional[List[float]]:
    n = FRAME_SIZE
    if not samples:
        return None
    rms = math.sqrt(sum((v * v for v in samples)) / len(samples))
    if rms < SILENCE_RMS:
        return None
    block = list(samples[:n])
    if len(block) < n:
        block += [0.0] * (n - len(block))
    window = _hann(n)
    spectrum = fft([complex(block[i] * window[i], 0.0) for i in range(n)])
    bin_hz = rate / n
    lo = max(1, int(MIN_HZ / bin_hz))
    hi = min(n // 2, int(MAX_HZ / bin_hz) + 1)
    magnitudes = [abs(spectrum[k]) for k in range(hi + 1)]
    chroma = [0.0] * 12
    for k in range(lo, hi):
        magnitude = magnitudes[k]
        if magnitude <= 0.0:
            continue
        if not (magnitude >= magnitudes[k - 1] and magnitude >= magnitudes[k + 1]):
            continue
        semitone = 12 * math.log2(k * bin_hz / 440.0) + 9
        chroma[int(round(semitone)) % 12] += magnitude
    total = sum(chroma)
    if total <= 0.0:
        return None
    chroma = [v / total for v in chroma]
    corrected = [max(0.0, chroma[p] - HARMONIC_FIFTH * chroma[(p - 7) % 12] - HARMONIC_THIRD * chroma[(p - 4) % 12]) for p in range(12)]
    total = sum(corrected)
    return [v / total for v in corrected] if total > 0 else chroma

def _correlate(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    num = sum(((a - mx) * (b - my) for a, b in zip(x, y)))
    dx = math.sqrt(sum(((a - mx) ** 2 for a in x)))
    dy = math.sqrt(sum(((b - my) ** 2 for b in y)))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0

@dataclass
class KeyEstimate:
    key: Optional[str] = None
    pitch_class: Optional[int] = None
    quality: Optional[str] = None
    score: float = 0.0
    margin: float = 0.0
    frames: int = 0
    chroma: List[float] = field(default_factory=list)

    @property
    def key_label(self) -> str:
        if not self.key:
            return '不明'
        if self.quality == 'minor':
            return f'{self.key}マイナー'
        return f'{self.key}メジャー'

    @property
    def confidence(self) -> str:
        if self.key is None:
            return 'none'
        if self.margin >= MARGIN_HIGH:
            return 'high'
        if self.margin >= MARGIN_MEDIUM:
            return 'medium'
        return 'low'

    def summary(self) -> str:
        if self.key is None:
            return 'キーを推定できなかった'
        return f'{self.key_label}（相関 {self.score:.2f}、2 位との差 {self.margin:.2f}、確信度 {self.confidence}）'

def estimate_from_chroma(chroma: Sequence[float], frames: int=0) -> KeyEstimate:
    scores = []
    for pitch_class in range(12):
        rotated = [chroma[(pitch_class + i) % 12] for i in range(12)]
        scores.append((_correlate(rotated, MAJOR_PROFILE), pitch_class, 'major'))
        scores.append((_correlate(rotated, MINOR_PROFILE), pitch_class, 'minor'))
    scores.sort(reverse=True)
    best, second = (scores[0], scores[1])
    return KeyEstimate(key=PITCH_NAMES[best[1]], pitch_class=best[1], quality=best[2], score=best[0], margin=best[0] - second[0], frames=frames, chroma=list(chroma))

def detect_key(path: str, max_frames: int=MAX_FRAMES) -> KeyEstimate:
    info = read_audio_info(path)
    if info is None or not info.sample_rate or info.frames <= 0:
        return KeyEstimate()
    decimate = max(1, round(info.sample_rate / TARGET_RATE))
    window_seconds = FRAME_SIZE * decimate / info.sample_rate
    span = info.duration - window_seconds
    if span <= 0:
        starts = [0.0]
    else:
        count = max(1, min(max_frames, int(info.duration / window_seconds)))
        step = span / count if count > 1 else 0.0
        starts = [i * step for i in range(count)]
    total = [0.0] * 12
    used = 0
    for start in starts:
        samples, rate = read_samples(path, start=start, frames=FRAME_SIZE * decimate, decimate=decimate)
        if not samples:
            continue
        chroma = frame_chroma(samples, rate)
        if chroma is None:
            continue
        total = [a + b for a, b in zip(total, chroma)]
        used += 1
    if not used:
        return KeyEstimate()
    return estimate_from_chroma([v / used for v in total], frames=used)

def transposition_agrees(estimate: KeyEstimate, key: Optional[str], quality: Optional[str]=None) -> Optional[bool]:
    if estimate.key is None or not key:
        return None
    return pitch_shift_semitones(estimate.key, key, estimate.quality, quality) == 0

def review_key(path: str, key: Optional[str], quality: Optional[str]=None) -> tuple:
    estimate = detect_key(path)
    agrees = transposition_agrees(estimate, key, quality)
    if agrees is False and estimate.confidence == 'high':
        return (estimate, f'音から推定したキーは{estimate.key_label}で、ファイル名の{key}と食い違う（確信度 {estimate.confidence}）。移調の前に確かめること')
    return (estimate, None)
