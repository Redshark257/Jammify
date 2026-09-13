import re
import json
import html as html_lib
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests
import numpy as np
import librosa


# ============================================================
# CONFIGURATION
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Candidate lengths for one Jammify pattern.
#
# Example:
#   beats = 4
#   pattern = [True, False, False, False]
#
# means one four-beat chord pattern.
#
# The analyzer will choose between these lengths based
# primarily on the audio and chord changes.
LIKELY_BEAT_LENGTHS = [1, 2, 4, 8]

# How much of a chord segment to ignore around transitions.
# This prevents attacks/crossfades from dominating the
# harmonic analysis.
INNER_MARGIN = 0.15

# Number of beats over which we search for a chord change.
CHANGE_THRESHOLD = 0.18

# Maximum number of beats a single chord event can occupy.
MAX_CHORD_BEATS = 8

# Default Jammify rhythm.
#
# This means:
#
#   ON OFF OFF OFF
#
# for a four-beat chord.
#
# For other beat lengths the pattern is generated
# automatically.
DEFAULT_ON_BEAT = 0


# ============================================================
# NOTE / CHORD UTILITIES
# ============================================================

NOTE_TO_PC = {
    "C": 0,
    "B#": 0,

    "C#": 1,
    "Db": 1,

    "D": 2,

    "D#": 3,
    "Eb": 3,

    "E": 4,
    "Fb": 4,

    "F": 5,
    "E#": 5,

    "F#": 6,
    "Gb": 6,

    "G": 7,

    "G#": 8,
    "Ab": 8,

    "A": 9,

    "A#": 10,
    "Bb": 10,

    "B": 11,
    "Cb": 11,
}


def extract_root(chord_name):
    """
    Extract root note from:

        Am
        F#m7
        Bbmaj7
        C/G
        Dsus4

    Returns:
        "A"
        "F#"
        "Bb"
        etc.
    """

    if not chord_name:
        return None

    match = re.match(
        r"^([A-Ga-g](?:#|b)?)",
        chord_name.strip()
    )

    if not match:
        return None

    root = match.group(1)

    return root[0].upper() + root[1:]


def root_pitch_class(chord_name):
    root = extract_root(chord_name)

    if root is None:
        return None

    return NOTE_TO_PC.get(root)


def midi_to_note(midi):
    names = [
        "C",
        "C#",
        "D",
        "D#",
        "E",
        "F",
        "F#",
        "G",
        "G#",
        "A",
        "A#",
        "B"
    ]

    midi = int(round(midi))

    octave = midi // 12 - 1

    return f"{names[midi % 12]}{octave}"


# ============================================================
# ULTIMATE GUITAR IMPORT
# ============================================================

def fetch_page(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            "URL must start with http:// or https://"
        )

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT
        },
        timeout=20
    )

    response.raise_for_status()

    return response.text


def get_page_title(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    if soup.title:
        return soup.title.get_text(
            strip=True
        )

    return "Imported Song"


def extract_wiki_content(html):
    """
    Extract Ultimate Guitar's wiki_tab content.

    This deliberately keeps the original parser approach,
    but the result is now used mainly to determine chord
    ORDER, not beat duration.
    """

    decoded = html_lib.unescape(html)

    match = re.search(
        r'"wiki_tab"\s*:\s*\{\s*"content"\s*:\s*"',
        decoded
    )

    if not match:
        raise ValueError(
            "Could not find Ultimate Guitar song content."
        )

    start = match.end()

    content_chars = []

    escaped = False

    for char in decoded[start:]:

        if escaped:
            content_chars.append(char)
            escaped = False
            continue

        if char == "\\":
            escaped = True
            content_chars.append(char)
            continue

        if char == '"':
            break

        content_chars.append(char)

    raw_content = "".join(content_chars)

    try:
        raw_content = bytes(
            raw_content,
            "utf-8"
        ).decode(
            "unicode_escape"
        )
    except UnicodeDecodeError:
        pass

    return raw_content


def extract_chords(content):
    """
    Extract the ordered chord sequence.

    IMPORTANT:

    We intentionally DO NOT use character spacing as beat
    information anymore.

    Ultimate Guitar formatting is not reliable enough for
    musical timing.
    """

    lines = content.splitlines()

    result = []

    for line in lines:

        if not line.strip():
            continue

        matches = list(
            re.finditer(
                r"\[ch\](.*?)\[/ch\]",
                line,
                flags=re.IGNORECASE | re.DOTALL
            )
        )

        for match in matches:

            chord = match.group(1)

            chord = html_lib.unescape(
                chord
            )

            chord = chord.strip()

            chord = re.sub(
                r"\s+",
                "",
                chord
            )

            if not chord:
                continue

            # Remove obviously invalid entries.
            if extract_root(chord) is None:
                continue

            result.append({
                "name": chord
            })

    return result


# ============================================================
# AUDIO
# ============================================================

def load_audio(audio_file):

    print(
        f"Loading audio: {audio_file}"
    )

    y, sr = librosa.load(
        audio_file,
        sr=22050,
        mono=True
    )

    y = y - np.mean(y)

    peak = np.max(
        np.abs(y)
    )

    if peak > 0:
        y = y / peak

    return y, sr


def calculate_chroma(y, sr):

    print("Calculating chroma...")

    chroma = librosa.feature.chroma_cqt(
        y=y,
        sr=sr,
        hop_length=512,
        bins_per_octave=36,
        n_octaves=7
    )

    chroma = librosa.util.normalize(
        chroma,
        axis=0
    )

    return chroma


def calculate_rms(y):

    return librosa.feature.rms(
        y=y,
        frame_length=2048,
        hop_length=512
    )[0]


# ============================================================
# TEMPO / BEAT GRID
# ============================================================

def estimate_beats(y, sr):
    """
    Estimate tempo AND actual beat positions.

    This is substantially more useful than only estimating BPM.

    Returns:

        bpm
        beat_times
    """

    print("Estimating BPM and beat positions...")

    onset_env = librosa.onset.onset_strength(
        y=y,
        sr=sr,
        hop_length=512
    )

    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=512,
        trim=False
    )

    tempo = float(
        np.asarray(tempo).flatten()[0]
    )

    # Handle common octave errors.
    if tempo < 55:
        tempo *= 2

    elif tempo > 180:
        tempo /= 2

    beat_times = librosa.frames_to_time(
        beat_frames,
        sr=sr,
        hop_length=512
    )

    beat_times = np.asarray(
        beat_times,
        dtype=float
    )

    # Remove invalid positions.
    beat_times = beat_times[
        beat_times >= 0
    ]

    if len(beat_times) < 2:

        # Fallback: create a regular beat grid.
        seconds_per_beat = 60.0 / tempo

        duration = len(y) / sr

        beat_times = np.arange(
            0,
            duration,
            seconds_per_beat
        )

    print(
        f"Estimated BPM: {tempo:.2f}"
    )

    print(
        f"Detected {len(beat_times)} beats."
    )

    return tempo, beat_times


def create_regular_beat_grid(
    duration,
    bpm
):
    """
    Fallback beat grid when beat tracking is poor.
    """

    seconds_per_beat = 60.0 / bpm

    return np.arange(
        0,
        duration,
        seconds_per_beat
    )


# ============================================================
# CHROMA / HARMONIC ANALYSIS
# ============================================================

def time_to_chroma_frame(
    time,
    sr,
    hop_length=512
):
    return int(
        round(
            time * sr / hop_length
        )
    )


def average_chroma(
    chroma,
    start_time,
    end_time,
    sr,
    hop_length=512
):
    """
    Return average chroma between two audio times.
    """

    start_frame = max(
        0,
        time_to_chroma_frame(
            start_time,
            sr,
            hop_length
        )
    )

    end_frame = min(
        chroma.shape[1],
        time_to_chroma_frame(
            end_time,
            sr,
            hop_length
        )
    )

    if end_frame <= start_frame:
        return np.zeros(12)

    segment = chroma[
        :,
        start_frame:end_frame
    ]

    if segment.shape[1] == 0:
        return np.zeros(12)

    result = np.mean(
        segment,
        axis=1
    )

    norm = np.linalg.norm(result)

    if norm > 0:
        result = result / norm

    return result


def chord_chroma_template(chord_name):
    """
    Very simple major/minor chord template.

    This is not intended to fully identify chords.
    The sheet already supplies the chord name.

    Its purpose is to determine how well the recorded
    audio matches the expected chord.
    """

    root = root_pitch_class(
        chord_name
    )

    if root is None:
        return np.zeros(12)

    template = np.zeros(12)

    # Root.
    template[root] = 1.0

    name = chord_name.lower()

    # Minor third.
    if (
        "m" in name
        and "maj" not in name
    ):
        template[
            (root + 3) % 12
        ] = 0.75

    else:
        # Major third.
        template[
            (root + 4) % 12
        ] = 0.75

    # Fifth.
    template[
        (root + 7) % 12
    ] = 0.60

    norm = np.linalg.norm(
        template
    )

    if norm > 0:
        template /= norm

    return template


def chord_similarity(
    observed_chroma,
    chord_name
):
    """
    Compare observed chroma to expected chord.
    """

    template = chord_chroma_template(
        chord_name
    )

    observed_norm = np.linalg.norm(
        observed_chroma
    )

    template_norm = np.linalg.norm(
        template
    )

    if (
        observed_norm == 0
        or template_norm == 0
    ):
        return 0.0

    return float(
        np.dot(
            observed_chroma,
            template
        )
        /
        (
            observed_norm
            * template_norm
        )
    )


# ============================================================
# CHORD EVENT TIMING
# ============================================================

def chord_segment_score(
    chroma,
    chord_name,
    start_time,
    end_time,
    sr
):
    """
    Calculate how well a chord fits a particular audio interval.

    We sample the inner portion of the interval to avoid
    attacks and chord transitions.
    """

    duration = end_time - start_time

    if duration <= 0:
        return -1.0

    inner_start = (
        start_time
        + duration * INNER_MARGIN
    )

    inner_end = (
        end_time
        - duration * INNER_MARGIN
    )

    if inner_end <= inner_start:
        inner_start = start_time
        inner_end = end_time

    observed = average_chroma(
        chroma,
        inner_start,
        inner_end,
        sr
    )

    return chord_similarity(
        observed,
        chord_name
    )


def score_chord_assignment(
    chroma,
    chord_names,
    start_beat,
    end_beat,
    beat_times,
    sr
):
    """
    Score assigning the supplied number of beats to the
    current chord.

    We look at how well the audio during that period matches
    the chord.
    """

    if start_beat >= len(beat_times):
        return -999.0

    end_time_index = min(
        end_beat,
        len(beat_times) - 1
    )

    start_time = beat_times[
        start_beat
    ]

    end_time = beat_times[
        end_time_index
    ]

    if end_time <= start_time:
        return -999.0

    score = chord_segment_score(
        chroma,
        chord_names,
        start_time,
        end_time,
        sr
    )

    return score


# ============================================================
# CHORD SEQUENCE ALIGNMENT
# ============================================================

def estimate_chord_duration_beats(
    chord_name,
    next_chord_name,
    current_beat,
    beat_times,
    chroma,
    sr
):
    """
    Determine how many beats the current chord should occupy.

    We test:

        1 beat
        2 beats
        4 beats
        8 beats

    and choose the duration that best fits the harmonic
    evidence.

    The next chord is also considered: if the audio begins
    matching the next chord, we stop the current chord.
    """

    remaining_beats = (
        len(beat_times)
        - 1
        - current_beat
    )

    if remaining_beats <= 0:
        return 1

    candidates = [
        b
        for b in LIKELY_BEAT_LENGTHS
        if b <= remaining_beats
    ]

    if not candidates:
        candidates = [
            min(
                remaining_beats,
                MAX_CHORD_BEATS
            )
        ]

    best_duration = candidates[0]
    best_score = -999.0

    for duration in candidates:

        end_beat = (
            current_beat
            + duration
        )

        if end_beat >= len(beat_times):
            continue

        start_time = beat_times[
            current_beat
        ]

        end_time = beat_times[
            end_beat
        ]

        score = chord_segment_score(
            chroma,
            chord_name,
            start_time,
            end_time,
            sr
        )

        # ----------------------------------------------------
        # Check whether the beginning of the next chord is
        # actually present.
        # ----------------------------------------------------

        if next_chord_name is not None:

            next_start = end_time

            next_end_index = min(
                end_beat + 1,
                len(beat_times) - 1
            )

            next_end = beat_times[
                next_end_index
            ]

            next_score = chord_segment_score(
                chroma,
                next_chord_name,
                next_start,
                next_end,
                sr
            )

            # If the next chord strongly fits immediately after
            # this duration, that's evidence that our boundary
            # is sensible.
            score += (
                max(
                    0.0,
                    next_score
                )
                * 0.35
            )

        # ----------------------------------------------------
        # Slight preference for conventional musical lengths.
        #
        # This prevents the algorithm from choosing 8 beats
        # merely because averaging over a longer section happens
        # to produce a similar chroma.
        # ----------------------------------------------------

        duration_bonus = {
            1: 0.00,
            2: 0.02,
            4: 0.05,
            8: 0.00
        }.get(
            duration,
            0.0
        )

        score += duration_bonus

        if score > best_score:

            best_score = score
            best_duration = duration

    return best_duration


def align_chords_to_beats(
    chord_sheet,
    beat_times,
    chroma,
    sr
):
    """
    Map the chord sequence onto the audio beat grid.

    IMPORTANT:

    The chord sheet determines ORDER.

    The audio determines TIMING.

    This is the core difference from the original script.
    """

    chord_names = [
        item["name"]
        for item in chord_sheet
    ]

    if not chord_names:
        return []

    result = []

    current_beat = 0

    chord_index = 0

    while (
        chord_index < len(chord_names)
        and current_beat < len(beat_times) - 1
    ):

        chord_name = chord_names[
            chord_index
        ]

        next_chord = None

        if (
            chord_index + 1
            < len(chord_names)
        ):
            next_chord = chord_names[
                chord_index + 1
            ]

        duration = estimate_chord_duration_beats(
            chord_name,
            next_chord,
            current_beat,
            beat_times,
            chroma,
            sr
        )

        end_beat = min(
            current_beat + duration,
            len(beat_times) - 1
        )

        start_time = beat_times[
            current_beat
        ]

        end_time = beat_times[
            end_beat
        ]

        result.append({
            "name": chord_name,
            "start_beat": int(
                current_beat
            ),
            "end_beat": int(
                end_beat
            ),
            "beats": int(
                end_beat - current_beat
            ),
            "start": float(
                start_time
            ),
            "end": float(
                end_time
            )
        })

        current_beat = end_beat

        chord_index += 1

    return result


# ============================================================
# MERGE CONSECUTIVE SAME CHORD EVENTS
# ============================================================

def merge_consecutive_chords(
    events
):
    """
    Merge adjacent identical chord events.

    Example:

        C 4 beats
        C 4 beats

    becomes:

        C 4 beats, repeat 2

    This is exactly the Jammify meaning of repeat.

    It does NOT mean:

        C 1 beat, repeat 8

    """

    if not events:
        return []

    result = []

    for event in events:

        if not result:

            result.append({
                **event,
                "repeat": 1
            })

            continue

        previous = result[-1]

        same_chord = (
            previous["name"].lower()
            == event["name"].lower()
        )

        # We only merge if the events are genuinely adjacent
        # in the beat grid.
        adjacent = (
            previous["end_beat"]
            == event["start_beat"]
        )

        if same_chord and adjacent:

            previous["repeat"] += 1

            previous["end_beat"] = (
                event["end_beat"]
            )

            previous["end"] = (
                event["end"]
            )

            previous["total_beats"] = (
                previous["beats"]
                * previous["repeat"]
            )

        else:

            result.append({
                **event,
                "repeat": 1
            })

    return result


# ============================================================
# JUMMIFY PATTERN
# ============================================================

def create_pattern(beats):
    """
    Create the default Jammify rhythm.

    Example:

        beats = 4

    becomes:

        [True, False, False, False]

    Repeat does NOT change this pattern.
    """

    beats = max(
        1,
        int(beats)
    )

    pattern = [
        False
        for _ in range(beats)
    ]

    pattern[
        min(
            DEFAULT_ON_BEAT,
            beats - 1
        )
    ] = True

    return pattern


# ============================================================
# ROOT OCTAVE DETECTION
# ============================================================

def frequency_for_midi(midi):
    return 440.0 * (
        2.0 ** ((midi - 69) / 12.0)
    )


def bass_spectrum(
    y_segment,
    sr
):
    """
    Calculate a spectrum with emphasis on low frequencies.

    Guitar chord roots are generally better estimated from
    the lower register than by simply looking for the strongest
    occurrence of the pitch anywhere in the spectrum.
    """

    if len(y_segment) < 4096:
        return None, None

    n_fft = 16384
    hop_length = 512

    spectrum = np.abs(
        librosa.stft(
            y_segment,
            n_fft=n_fft,
            hop_length=hop_length
        )
    )

    frequencies = librosa.fft_frequencies(
        sr=sr,
        n_fft=n_fft
    )

    mean_spectrum = np.mean(
        spectrum,
        axis=1
    )

    max_energy = np.max(
        mean_spectrum
    )

    if max_energy <= 0:
        return None, None

    mean_spectrum /= max_energy

    return (
        frequencies,
        mean_spectrum
    )


def score_root_octave(
    y_segment,
    sr,
    root_pc
):
    """
    Determine the most likely octave of the chord root.

    This version gives significantly more importance to:

        - actual low-frequency fundamental
        - harmonic consistency
        - low-register evidence

    and less importance to a high-frequency harmonic merely
    appearing strongly.
    """

    frequencies, spectrum = bass_spectrum(
        y_segment,
        sr
    )

    if frequencies is None:
        return 4, 0.0

    candidates = []

    # Guitar chord root range.
    #
    # Octave 2:
    #   C2-B2
    #
    # through octave 5.
    for octave in range(2, 6):

        midi = (
            (octave + 1) * 12
            + root_pc
        )

        root_frequency = frequency_for_midi(
            midi
        )

        if root_frequency >= sr / 2:
            continue

        # ----------------------------------------------------
        # Root frequency window.
        # ----------------------------------------------------

        tolerance = max(
            3.0,
            root_frequency * 0.025
        )

        indices = np.where(
            np.abs(
                frequencies
                - root_frequency
            )
            <= tolerance
        )[0]

        if len(indices) == 0:
            continue

        fundamental = float(
            np.max(
                spectrum[indices]
            )
        )

        fundamental_mean = float(
            np.mean(
                spectrum[indices]
            )
        )

        # ----------------------------------------------------
        # Harmonic support.
        # ----------------------------------------------------

        harmonic_score = 0.0

        weights = {
            2: 0.25,
            3: 0.15,
            4: 0.08,
            5: 0.05
        }

        for harmonic, weight in weights.items():

            frequency = (
                root_frequency
                * harmonic
            )

            if frequency >= sr / 2:
                continue

            tolerance = max(
                4.0,
                frequency * 0.02
            )

            h_indices = np.where(
                np.abs(
                    frequencies
                    - frequency
                )
                <= tolerance
            )[0]

            if len(h_indices) == 0:
                continue

            harmonic_energy = float(
                np.max(
                    spectrum[h_indices]
                )
            )

            harmonic_score += (
                harmonic_energy
                * weight
            )

        # ----------------------------------------------------
        # Strong preference for actual low roots.
        #
        # A high octave should need considerably stronger
        # evidence before beating a low octave.
        # ----------------------------------------------------

        if octave == 2:
            low_bonus = 1.30

        elif octave == 3:
            low_bonus = 1.20

        elif octave == 4:
            low_bonus = 1.00

        else:
            low_bonus = 0.80

        score = (
            fundamental * 0.60
            +
            fundamental_mean * 0.15
            +
            harmonic_score * 0.25
        )

        score *= low_bonus

        candidates.append({
            "octave": octave,
            "fundamental": fundamental,
            "fundamental_mean": fundamental_mean,
            "harmonic_score": harmonic_score,
            "score": score
        })

    if not candidates:
        return 4, 0.0

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    best = candidates[0]

    # --------------------------------------------------------
    # Confidence.
    # --------------------------------------------------------

    if len(candidates) > 1:

        second = candidates[1]

        confidence = (
            best["score"]
            /
            max(
                second["score"],
                1e-9
            )
        )

    else:
        confidence = 1.0

    # --------------------------------------------------------
    # Prefer a lower octave when it has substantial fundamental
    # evidence.
    # --------------------------------------------------------

    for candidate in sorted(
        candidates,
        key=lambda x: x["octave"]
    ):

        if candidate["octave"] >= best["octave"]:
            continue

        if (
            candidate["fundamental"]
            >= best["fundamental"] * 0.65
        ):

            best = candidate
            break

    return (
        int(best["octave"]),
        float(confidence)
    )


def detect_chord_octave(
    y,
    sr,
    chord,
    start,
    end
):
    """
    Determine chord root octave from the middle of the chord.
    """

    duration = end - start

    if duration <= 0:
        return {
            "octave": 4,
            "confidence": 0.0
        }

    inner_start = (
        start
        + duration * 0.25
    )

    inner_end = (
        end
        - duration * 0.25
    )

    if inner_end <= inner_start:
        inner_start = start
        inner_end = end

    start_sample = max(
        0,
        int(inner_start * sr)
    )

    end_sample = min(
        len(y),
        int(inner_end * sr)
    )

    segment = y[
        start_sample:end_sample
    ]

    root_pc = root_pitch_class(
        chord
    )

    if root_pc is None:
        return {
            "octave": 4,
            "confidence": 0.0
        }

    octave, confidence = score_root_octave(
        segment,
        sr,
        root_pc
    )

    return {
        "octave": int(octave),
        "confidence": float(
            confidence
        )
    }


# ============================================================
# OCTAVE SMOOTHING
# ============================================================

def smooth_octaves(events):
    """
    Prevent isolated octave jumps.

    Example:

        C3
        G3
        Am5
        F3

    If Am5 is a low-confidence outlier, this function can
    replace it with the surrounding register.

    The original detector treated every chord completely
    independently, which makes isolated octave errors common.
    """

    if len(events) < 3:
        return events

    result = [
        dict(event)
        for event in events
    ]

    for i in range(1, len(result) - 1):

        previous = result[i - 1]
        current = result[i]
        following = result[i + 1]

        prev_octave = previous[
            "octave"
        ]

        current_octave = current[
            "octave"
        ]

        next_octave = following[
            "octave"
        ]

        confidence = current.get(
            "octave_confidence",
            0.0
        )

        # If both neighbors agree and this chord is
        # significantly different with weak confidence,
        # treat it as an outlier.
        if (
            prev_octave
            == next_octave
            and current_octave
            != prev_octave
            and confidence < 1.30
        ):

            current[
                "octave"
            ] = prev_octave

    return result


# ============================================================
# FINAL ANALYSIS
# ============================================================

def analyze_song(
    chord_sheet,
    audio_file,
    bpm=None
):

    audio_file = Path(
        audio_file
    )

    if not audio_file.exists():
        raise FileNotFoundError(
            audio_file
        )

    # --------------------------------------------------------
    # Load audio
    # --------------------------------------------------------

    y, sr = load_audio(
        audio_file
    )

    audio_duration = (
        len(y) / sr
    )

    # --------------------------------------------------------
    # Tempo + beat grid
    # --------------------------------------------------------

    if bpm is None:

        bpm, beat_times = estimate_beats(
            y,
            sr
        )

    else:

        bpm = float(
            bpm
        )

        beat_times = create_regular_beat_grid(
            audio_duration,
            bpm
        )

    if len(beat_times) < 2:

        raise ValueError(
            "Could not determine a usable beat grid."
        )

    # --------------------------------------------------------
    # Chroma
    # --------------------------------------------------------

    chroma = calculate_chroma(
        y,
        sr
    )

    # --------------------------------------------------------
    # Align chord sequence to actual audio beats.
    # --------------------------------------------------------

    print()
    print(
        "Aligning chords to audio..."
    )

    aligned = align_chords_to_beats(
        chord_sheet,
        beat_times,
        chroma,
        sr
    )

    if not aligned:

        raise ValueError(
            "Could not align chord sheet to audio."
        )

    # --------------------------------------------------------
    # Remove impossible final zero-duration event.
    # --------------------------------------------------------

    aligned = [
        event
        for event in aligned
        if event["beats"] > 0
    ]

    # --------------------------------------------------------
    # Octave detection.
    # --------------------------------------------------------

    print()
    print(
        "Detecting chord octaves..."
    )

    for index, event in enumerate(
        aligned
    ):

        print(
            f"Octave "
            f"{index + 1}/"
            f"{len(aligned)}: "
            f"{event['name']}"
        )

        octave_data = detect_chord_octave(
            y,
            sr,
            event["name"],
            event["start"],
            event["end"]
        )

        event[
            "octave"
        ] = int(
            octave_data["octave"]
        )

        event[
            "octave_confidence"
        ] = float(
            round(
                octave_data[
                    "confidence"
                ],
                3
            )
        )

    # --------------------------------------------------------
    # Smooth isolated octave errors.
    # --------------------------------------------------------

    aligned = smooth_octaves(
        aligned
    )

    # --------------------------------------------------------
    # Merge consecutive occurrences of the SAME chord.
    #
    # This is where Jammify repeat is created.
    #
    # C 4 beats
    # C 4 beats
    #
    # becomes:
    #
    # C
    # beats = 4
    # repeat = 2
    #
    # NOT:
    #
    # beats = 8
    #
    # because the pattern remains four beats long.
    # --------------------------------------------------------

    merged = merge_consecutive_chords(
        aligned
    )

    # --------------------------------------------------------
    # Build Jammify output.
    # --------------------------------------------------------

    jammify_chords = []

    for event in merged:

        beats = int(
            event["beats"]
        )

        repeat = int(
            event.get(
                "repeat",
                1
            )
        )

        total_beats = (
            beats
            * repeat
        )

        jammify_chords.append({

            "type": "chord",

            "name": str(
                event["name"]
            ),

            "octave": int(
                event.get(
                    "octave",
                    4
                )
            ),

            "inversion": 0,

            "beats": beats,

            "repeat": repeat,

            "instrument": "grand_piano",

            "wait": 0,

            "speed": 1,

            "pattern": create_pattern(
                beats
            ),

            "total_beats": total_beats
        })

    # --------------------------------------------------------
    # Diagnostic timeline.
    # --------------------------------------------------------

    diagnostic_timeline = []

    for event in merged:

        diagnostic_timeline.append({

            "name": event["name"],

            "beats": int(
                event["beats"]
            ),

            "repeat": int(
                event.get(
                    "repeat",
                    1
                )
            ),

            "total_beats": int(
                event["beats"]
                *
                event.get(
                    "repeat",
                    1
                )
            ),

            "start": float(
                round(
                    event["start"],
                    3
                )
            ),

            "end": float(
                round(
                    event["end"],
                    3
                )
            ),

            "start_beat": int(
                event["start_beat"]
            ),

            "end_beat": int(
                event["end_beat"]
            ),

            "octave": int(
                event.get(
                    "octave",
                    4
                )
            ),

            "octave_confidence": float(
                event.get(
                    "octave_confidence",
                    0.0
                )
            )
        })

    return {

        "bpm": float(
            bpm
        ),

        "chords": jammify_chords,

        "timeline": diagnostic_timeline,

        "audio_duration": float(
            round(
                audio_duration,
                3
            )
        ),

        "detected_beats": int(
            len(beat_times)
        )
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) != 3:

        print(
            "Usage:"
        )

        print(
            "  python song_analyzer.py "
            "<chord_sheet_url> <audio_file>"
        )

        print()

        print(
            "Example:"
        )

        print(
            "  python song_analyzer.py "
            "https://tabs.ultimate-guitar.com/tab/... "
            "/path/to/guitar.wav"
        )

        sys.exit(1)

    URL = sys.argv[1]

    AUDIO_FILE = sys.argv[2]

    BPM = None

    # --------------------------------------------------------
    # Download chord sheet.
    # --------------------------------------------------------

    print(
        "Downloading chord sheet..."
    )

    html = fetch_page(
        URL
    )

    title = get_page_title(
        html
    )

    content = extract_wiki_content(
        html
    )

    chord_sheet = extract_chords(
        content
    )

    if not chord_sheet:

        raise ValueError(
            "No chords found."
        )

    print(
        f"Found {len(chord_sheet)} "
        f"chord entries."
    )

    print()

    print(
        "Chord sequence:"
    )

    print(
        " -> ".join(
            item["name"]
            for item in chord_sheet
        )
    )

    # --------------------------------------------------------
    # Analyze.
    # --------------------------------------------------------

    result = analyze_song(
        chord_sheet,
        AUDIO_FILE,
        bpm=BPM
    )

    result["title"] = title

    # --------------------------------------------------------
    # Save.
    # --------------------------------------------------------

    with open(
        "analyzed_song.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # Print final result.
    # --------------------------------------------------------

    print()

    print(
        "================================"
    )

    print(
        "Analysis complete!"
    )

    print(
        "================================"
    )

    print()

    print(
        json.dumps(
            result["chords"],
            indent=4,
            ensure_ascii=False
        )
    )

    print()

    print(
        "Diagnostic timeline:"
    )

    print(
        json.dumps(
            result["timeline"],
            indent=4,
            ensure_ascii=False
        )
    )
