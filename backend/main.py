# main.py

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
)

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

import shutil
import tempfile
from pathlib import Path

from chord_player import play_chord, stop_chords
from metronome import set_tempo, BPM, BEATS_PER_BAR

from song_chord_importer import import_chords_from_url
from splitter import separate_audio

from song_analyzer import (
    fetch_page,
    get_page_title,
    extract_wiki_content,
    extract_chords_with_beats,
    analyze_song,
)


# ============================================================
# APP
# ============================================================

app = FastAPI()


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODELS
# ============================================================

class TempoSettings(BaseModel):
    bpm: int
    beats_per_bar: int


class Chord(BaseModel):
    name: str
    octave: int
    beats: float
    instrument: str
    volume: float
    wait: float


class ImportChordsRequest(BaseModel):
    url: str


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "Jammify API is running"
    }


# ============================================================
# PLAY
# ============================================================

@app.get("/play")
def play(chord: str, mode: str = "normal"):

    if mode == "strumming":
        wait = 0.05
    else:
        wait = 0.0

    # Audio playback currently disabled.
    #
    # threading.Thread(
    #     target=play_chord,
    #     args=(
    #         chord,
    #         4,
    #         1,
    #         0.8,
    #         "acoustic_grand_piano",
    #         wait,
    #     ),
    # ).start()

    return {
        "message": "playing",
        "chord": chord,
        "mode": mode,
    }


# ============================================================
# STOP
# ============================================================

@app.get("/stop")
def stop():

    stop_chords()

    return {
        "message": "stopped"
    }


# ============================================================
# TEMPO
# ============================================================

@app.get("/tempo")
def get_tempo():

    return {
        "bpm": BPM,
        "beats_per_bar": BEATS_PER_BAR,
    }


@app.post("/tempo")
def update_tempo(settings: TempoSettings):

    set_tempo(
        settings.bpm,
        settings.beats_per_bar,
    )

    return {
        "bpm": settings.bpm,
        "beats_per_bar": settings.beats_per_bar,
    }


# ============================================================
# PLAY STEP
# ============================================================

@app.post("/play_step")
def play_step(chords: list[Chord]):

    print("RECEIVED:", chords)

    return {
        "message": "received",
        "chords": chords,
    }


# ============================================================
# IMPORT SONG
# ============================================================

@app.post("/import-song")
def import_chords(request: ImportChordsRequest):

    try:

        result = import_chords_from_url(
            request.url
        )

        return result

    except Exception as e:

        print(
            "IMPORT ERROR:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# ANALYZE SONG
# ============================================================

@app.post("/analyze-song")
async def analyze_uploaded_song(
    tabs_url: str = Form(...),
    audio_file: UploadFile = File(...),
):

    temp_root = None

    try:

        # ----------------------------------------------------
        # Validate Ultimate Guitar URL
        # ----------------------------------------------------

        if not tabs_url.strip():

            raise HTTPException(
                status_code=400,
                detail="Ultimate Guitar URL is required.",
            )

        # ----------------------------------------------------
        # Validate uploaded file
        # ----------------------------------------------------

        if not audio_file.filename:

            raise HTTPException(
                status_code=400,
                detail="Audio file is required.",
            )

        extension = Path(
            audio_file.filename
        ).suffix.lower()

        if extension != ".wav":

            raise HTTPException(
                status_code=400,
                detail="Please upload a WAV file.",
            )

        # ----------------------------------------------------
        # Create temporary working directory
        # ----------------------------------------------------

        temp_root = Path(
            tempfile.mkdtemp(
                prefix="jammify_"
            )
        )

        input_file = (
            temp_root
            / "input.wav"
        )

        split_dir = (
            temp_root
            / "stems"
        )

        # ----------------------------------------------------
        # Save uploaded WAV
        # ----------------------------------------------------

        print(
            f"Saving uploaded audio: "
            f"{audio_file.filename}"
        )

        with open(
            input_file,
            "wb",
        ) as buffer:

            shutil.copyfileobj(
                audio_file.file,
                buffer,
            )

        # ----------------------------------------------------
        # STEP 1: AUDIO SEPARATION
        # ----------------------------------------------------

        print()
        print("==============================")
        print("STEP 1: AUDIO SEPARATION")
        print("==============================")

        separation = separate_audio(
            input_file,
            split_dir,
        )

        stems = separation["stems"]

        guitar_file = stems.get(
            "guitar"
        )

        if not guitar_file:

            raise RuntimeError(
                "Guitar stem was not produced."
            )

        print(
            f"Guitar stem: {guitar_file}"
        )

        # ----------------------------------------------------
        # STEP 2: CHORD SHEET
        # ----------------------------------------------------

        print()
        print("==============================")
        print("STEP 2: CHORD SHEET")
        print("==============================")

        html = fetch_page(
            tabs_url
        )

        title = get_page_title(
            html
        )

        content = extract_wiki_content(
            html
        )

        chord_sheet = (
            extract_chords_with_beats(
                content
            )
        )

        if not chord_sheet:

            raise ValueError(
                "No chords found in the supplied "
                "Ultimate Guitar page."
            )

        print(
            f"Found {len(chord_sheet)} "
            f"chord entries."
        )

        # ----------------------------------------------------
        # STEP 3: GUITAR ANALYSIS
        # ----------------------------------------------------

        print()
        print("==============================")
        print("STEP 3: GUITAR ANALYSIS")
        print("==============================")

        result = analyze_song(
            chord_sheet,
            guitar_file,
        )

        result["title"] = title

        # ----------------------------------------------------
        # Return result to React
        # ----------------------------------------------------

        return {
            "success": True,

            "title": title,

            "bpm": result["bpm"],

            "chords": result["chords"],

            "timeline": result["timeline"],

            "stems": {
                stem: Path(path).name
                for stem, path in stems.items()
            },
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            "ANALYZE SONG ERROR:",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

    finally:

        # ----------------------------------------------------
        # DELETE ALL TEMPORARY FILES
        # ----------------------------------------------------

        if temp_root and temp_root.exists():

            print()
            print("==============================")
            print("CLEANING UP TEMPORARY FILES")
            print("==============================")

            shutil.rmtree(
                temp_root,
                ignore_errors=True,
            )

            print(
                f"Deleted temporary directory: "
                f"{temp_root}"
            )


# ============================================================
# OPTIONAL PLAYBACK IMPLEMENTATION
# ============================================================

'''
@app.post("/play_step")
def play_step(chords: list[Chord]):

    print("RECEIVED:", chords)

    threads = []

    for chord in chords:

        t = threading.Thread(
            target=play_chord,
            args=(
                chord.name,
                chord.octave,
                chord.beats,
                chord.volume,
                chord.instrument,
                chord.wait,
            ),
        )

        t.start()

        threads.append(t)

    for t in threads:
        t.join()

    return {
        "message": "finished"
    }
'''
