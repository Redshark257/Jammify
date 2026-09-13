# song_analyzer.py
import re
import json
import html as html_lib
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup


import requests
import numpy as np
import librosa

import sys

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


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
    Extract the root note from:

        Am
        F#m7
        Bbmaj7
        C/G
        Dsus4

    Returns:
        note string
    """

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

    raw_content = bytes(
        raw_content,
        "utf-8"
    ).decode(
        "unicode_escape"
    )

    return raw_content


def extract_chords_with_beats(content):

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

        if not matches:
            continue

        chord_data = []

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

            chord_data.append({
                "name": chord,
                "position": match.start()
            })

        if not chord_data:
            continue

        for index, chord in enumerate(chord_data):

            if index < len(chord_data) - 1:

                chord["distance"] = (
                    chord_data[index + 1]["position"]
                    - chord["position"]
                )

            else:

                if len(chord_data) > 1:

                    distances = [
                        chord_data[i + 1]["position"]
                        - chord_data[i]["position"]
                        for i in range(len(chord_data) - 1)
                    ]

                    chord["distance"] = (
                        sum(distances)
                        / len(distances)
                    )

                else:

                    chord["distance"] = 1

        distances = [
            chord["distance"]
            for chord in chord_data
            if chord["distance"] > 0
        ]

        if not distances:
            continue

        base_distance = max(
            min(distances),
            1
        )

        for chord in chord_data:

            ratio = (
                chord["distance"]
                / base_distance
            )

            beats = max(
                1,
                round(ratio)
            )

            beats = min(
                16,
                beats
            )

            result.append({
                "name": chord["name"],
                "beats": beats
            })

    return result


# ============================================================
# AUDIO ANALYSIS
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

    # Remove DC offset.
    y = y - np.mean(y)

    # Normalize.
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

    # Normalize every frame.
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
# CHORD TIMING
# ============================================================

def create_chord_timeline(
    chords,
    bpm
):
    """
    Convert beats from the chord sheet
    into approximate audio times.
    """

    seconds_per_beat = 60.0 / bpm

    timeline = []

    current_time = 0.0

    for chord in chords:

        duration = (
            chord["beats"]
            * seconds_per_beat
        )

        timeline.append({
            "name": chord["name"],
            "beats": chord["beats"],
            "start": current_time,
            "end": current_time + duration
        })

        current_time += duration

    return timeline


# ============================================================
# AUDIO OFFSET / TEMPO IMPROVEMENT
# ============================================================

def estimate_bpm(y, sr):

    print("Estimating BPM...")

    tempo, _ = librosa.beat.beat_track(
        y=y,
        sr=sr
    )

    tempo = float(
        np.asarray(tempo).flatten()[0]
    )

    # Keep it within sensible musical bounds.
    if tempo < 40:
        tempo *= 2

    if tempo > 240:
        tempo /= 2

    return tempo


# ============================================================
# ROOT OCTAVE DETECTION
# ============================================================

def frequency_for_midi(midi):
    return 440.0 * (
        2.0 ** ((midi - 69) / 12.0)
    )


def score_root_octave(
    y_segment,
    sr,
    root_pc
):
    """
    Estimate the octave/register of the chord root.

    Uses:
        1. Low-frequency spectral energy
        2. Fundamental strength
        3. Harmonic support
        4. Subharmonic/octave ambiguity handling

    Returns:
        octave,
        confidence
    """

    if len(y_segment) < 4096:
        return 4, 0.0

    # --------------------------------------------------------
    # STFT
    # --------------------------------------------------------

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

    # Average over time.
    mean_spectrum = np.mean(
        spectrum,
        axis=1
    )

    # Normalize.
    max_energy = np.max(
        mean_spectrum
    )

    if max_energy <= 0:
        return 4, 0.0

    mean_spectrum /= max_energy

    # --------------------------------------------------------
    # Guitar-oriented octave range.
    #
    # E2 = 82.4 Hz
    # E5 = 659 Hz
    #
    # We can still test through octave 6.
    # --------------------------------------------------------

    candidates = []

    for octave in range(2, 7):

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
        # Fundamental
        # ----------------------------------------------------

        tolerance = max(
            4.0,
            root_frequency * 0.035
        )

        indices = np.where(
            np.abs(
                frequencies - root_frequency
            ) <= tolerance
        )[0]

        if len(indices) == 0:
            continue

        fundamental = np.max(
            mean_spectrum[indices]
        )

        # ----------------------------------------------------
        # Energy around the root.
        #
        # Average as well as max. This helps avoid a single
        # FFT bin producing a false positive.
        # ----------------------------------------------------

        root_mean = np.mean(
            mean_spectrum[indices]
        )

        # ----------------------------------------------------
        # Harmonic support
        # ----------------------------------------------------

        harmonic_score = 0.0

        harmonic_weights = {
            2: 0.30,
            3: 0.20,
            4: 0.12,
            5: 0.08
        }

        for harmonic, weight in harmonic_weights.items():

            frequency = (
                root_frequency * harmonic
            )

            if frequency >= sr / 2:
                continue

            tolerance = max(
                5.0,
                frequency * 0.025
            )

            h_indices = np.where(
                np.abs(
                    frequencies - frequency
                ) <= tolerance
            )[0]

            if len(h_indices) == 0:
                continue

            harmonic_energy = np.max(
                mean_spectrum[h_indices]
            )

            harmonic_score += (
                harmonic_energy * weight
            )

        # ----------------------------------------------------
        # Low-frequency preference
        #
        # For guitar, a genuine low root is much more
        # meaningful than a high octave that only appears
        # because of harmonics.
        # ----------------------------------------------------

        if octave <= 3:
            low_bonus = 1.15
        elif octave == 4:
            low_bonus = 1.0
        else:
            low_bonus = 0.90

        # ----------------------------------------------------
        # Final score
        # ----------------------------------------------------

        score = (
            fundamental * 0.60
            +
            root_mean * 0.20
            +
            harmonic_score * 0.20
        )

        score *= low_bonus

        candidates.append({
            "octave": octave,
            "frequency": root_frequency,
            "fundamental": float(fundamental),
            "root_mean": float(root_mean),
            "harmonic_score": float(harmonic_score),
            "score": float(score)
        })

    if not candidates:
        return 4, 0.0

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    best = candidates[0]

    # --------------------------------------------------------
    # Confidence
    # --------------------------------------------------------

    if len(candidates) >= 2:

        second = candidates[1]

        confidence = (
            best["score"]
            / max(
                second["score"],
                1e-9
            )
        )

    else:
        confidence = 1.0

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # If two octaves are almost equally strong, choose the
    # LOWER one only if it has real fundamental evidence.
    # --------------------------------------------------------

    if len(candidates) >= 2:

        for candidate in sorted(
            candidates,
            key=lambda x: x["octave"]
        ):

            if candidate["octave"] >= best["octave"]:
                continue

            # Lower octave is sufficiently supported.
            if (
                candidate["fundamental"]
                >= best["fundamental"] * 0.75
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
    Detect the most likely register/octave of a chord.

    Uses the middle portion of the chord to avoid
    attacks and transitions.
    """

    duration = end - start

    # --------------------------------------------------------
    # Ignore attacks/transitions.
    # --------------------------------------------------------

    inner_start = (
        start + duration * 0.20
    )

    inner_end = (
        end - duration * 0.20
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

    # --------------------------------------------------------
    # Determine root pitch class.
    # --------------------------------------------------------

    root_pc = root_pitch_class(
        chord
    )

    if root_pc is None:
        return {
            "octave": 4,
            "confidence": 0.0,
            "detected": False
        }

    # --------------------------------------------------------
    # Detect octave.
    # --------------------------------------------------------

    octave, confidence = score_root_octave(
        segment,
        sr,
        root_pc
    )

    return {
        "octave": int(octave),
        "confidence": float(confidence),
        "detected": True
    }



# ============================================================
# REPEAT DETECTION
# ============================================================

def calculate_repeats(chords):
    """
    Collapse consecutive identical chords only when
    both chord name AND octave are the same.
    """

    result = []

    for chord in chords:

        if result:

            previous = result[-1]

            same_name = (
                previous["name"].lower()
                == chord["name"].lower()
            )

            same_octave = (
                previous.get("octave", 4)
                == chord.get("octave", 4)
            )

            if same_name and same_octave:

                previous["repeat"] += 1

                previous["total_beats"] += (
                    chord["beats"]
                )

                continue

        result.append({
            "name": chord["name"],
            "beats": chord["beats"],
            "octave": chord.get("octave", 4),
            "octave_confidence": chord.get(
                "octave_confidence",
                0.0
            ),
            "repeat": 1,
            "total_beats": chord["beats"]
        })

    return result



# =====================================================================
#                      ANALYZE COMPLETE SONG
# =====================================================================

# ============================================================
# ANALYZE COMPLETE SONG
# ============================================================

# ============================================================
# ANALYZE COMPLETE SONG
# ============================================================

def analyze_song(
    chord_sheet,
    audio_file,
    bpm=None
):

    audio_file = Path(audio_file)

    if not audio_file.exists():
        raise FileNotFoundError(audio_file)

    # --------------------------------------------------------
    # Load audio
    # --------------------------------------------------------

    y, sr = load_audio(audio_file)

    # --------------------------------------------------------
    # BPM
    # --------------------------------------------------------

    if bpm is None:
        bpm = estimate_bpm(y, sr)

    # Make sure BPM is a normal Python float
    bpm = float(bpm)

    print(f"Detected BPM: {bpm:.2f}")

    # --------------------------------------------------------
    # Create chord timeline
    # --------------------------------------------------------

    timeline = create_chord_timeline(
        chord_sheet,
        bpm
    )

    if not timeline:
        raise ValueError(
            "No chord timeline could be created."
        )

    # --------------------------------------------------------
    # Scale timeline to audio duration
    # --------------------------------------------------------

    audio_duration = float(len(y) / sr)

    sheet_duration = float(
        timeline[-1]["end"]
    )

    if (
        sheet_duration > 0
        and audio_duration > 0
    ):

        scale = (
            audio_duration
            / sheet_duration
        )

        if 0.75 < scale < 1.25:

            for item in timeline:

                item["start"] = float(
                    item["start"] * scale
                )

                item["end"] = float(
                    item["end"] * scale
                )

    # --------------------------------------------------------
    # Detect octave for every chord
    # --------------------------------------------------------

    analyzed = []

    for index, item in enumerate(timeline):

        print(
            f"Analyzing "
            f"{index + 1}/"
            f"{len(timeline)}: "
            f"{item['name']}"
        )

        octave_data = detect_chord_octave(
            y,
            sr,
            item["name"],
            item["start"],
            item["end"]
        )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Convert NumPy values to normal Python values here.
        # ----------------------------------------------------

        detected_octave = int(
            octave_data.get(
                "octave",
                4
            )
        )

        confidence = float(
            octave_data.get(
                "confidence",
                0
            )
        )

        analyzed.append({

            "name": str(
                item["name"]
            ),

            "beats": int(
                item.get(
                    "beats",
                    1
                )
            ),

            "start": float(
                round(
                    item["start"],
                    3
                )
            ),

            "end": float(
                round(
                    item["end"],
                    3
                )
            ),

            "octave": detected_octave,

            "octave_confidence": float(
                round(
                    confidence,
                    3
                )
            )

        })

    # --------------------------------------------------------
    # Calculate repeats
    # --------------------------------------------------------

    repeated = calculate_repeats(
        analyzed
    )

    # --------------------------------------------------------
    # Convert to Jammify format
    # --------------------------------------------------------

    jammify_chords = []

    for item in repeated:

        octave = int(
            item.get(
                "octave",
                4
            )
        )

        beats = int(
            item.get(
                "beats",
                1
            )
        )

        repeat = int(
            item.get(
                "repeat",
                1
            )
        )

        total_beats = int(
            item.get(
                "total_beats",
                beats * repeat
            )
        )

        jammify_chords.append({

            "type": "chord",

            "name": str(
                item["name"]
            ),

            "octave": octave,

            "inversion": 0,

            "beats": beats,

            "repeat": repeat,

            "instrument": "grand_piano",

            "wait": 0,

            "speed": 1,

            "pattern": [
                True
            ],

            "total_beats": total_beats

        })

    # --------------------------------------------------------
    # Return
    # --------------------------------------------------------

    return {

        "bpm": float(bpm),

        "chords": jammify_chords,

        "timeline": analyzed

    }




# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

# ============================================================
# MAIN
# ============================================================

    if len(sys.argv) != 3:
        print("Usage:")
        print(
            "  python song_analyser.py "
            "<chord_sheet_url> <audio_file>"
        )
        print()
        print("Example:")
        print(
            "  python song_analyser.py "
            "https://tabs.ultimate-guitar.com/tab/... "
            "/path/to/guitar.wav"
        )
        sys.exit(1)

    # --------------------------------------------
    # Read command-line arguments
    # --------------------------------------------

    URL = sys.argv[1]
    AUDIO_FILE = sys.argv[2]

    BPM = None

    # --------------------------------------------
    # Get chord sheet
    # --------------------------------------------

    print("Downloading chord sheet...")

    html = fetch_page(URL)

    title = get_page_title(html)

    content = extract_wiki_content(html)

    chord_sheet = extract_chords_with_beats(content)

    if not chord_sheet:
        raise ValueError(
            "No chords found."
        )

    print(
        f"Found {len(chord_sheet)} "
        f"chord entries."
    )

    # --------------------------------------------
    # Analyze audio
    # --------------------------------------------

    result = analyze_song(
        chord_sheet,
        AUDIO_FILE,
        bpm=BPM
    )

    result["title"] = title

    # --------------------------------------------
    # Save JSON
    # --------------------------------------------

    with open(
        "analyzed_song.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=2,
            ensure_ascii=False,
            default=lambda o: o.item() if hasattr(o, "item") else str(o)
        )

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

    print(
        json.dumps(
            result["chords"],
            indent=4
        )
    )
