# main.py
from chord_player import play_chord, stop_chords

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import threading
from pydantic import BaseModel
from metronome import set_tempo, BPM, BEATS_PER_BAR


from song_chord_importer import import_chords_from_url



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

app = FastAPI()

'''
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
'''

# render online
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
def root():
    return {"message": "Jammify API is running"}


@app.get("/play")
def play(chord: str, mode: str = "normal"):

    if mode == "strumming":
        wait = 0.05
    else:
        wait = 0.0

    '''
    threading.Thread(
        target=play_chord,
        args=(
            chord,
            4,   # octave
            1,   # beats
            0.8, # volume,
            "acoustic_grand_piano",
            wait
        )
    ).start()
    '''
    

    return {
        "message": "playing",
        "chord": chord,
        "mode": mode
    }

@app.get("/stop")
def stop():
    stop_chords()

    return {
        "message": "stopped"
    }


@app.get("/tempo")
def get_tempo():

    return {
        "bpm": BPM,
        "beats_per_bar": BEATS_PER_BAR
    }


@app.post("/tempo")
def update_tempo(settings: TempoSettings):

    set_tempo(
        settings.bpm,
        settings.beats_per_bar
    )

    return {
        "bpm": settings.bpm,
        "beats_per_bar": settings.beats_per_bar
    }


#@app.get("/play_step")
@app.post("/play_step")
def play_step(chords: list[Chord]):

    print("RECEIVED:", chords)

    return {
        "message": "received",
        "chords": chords
    }


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
            detail=str(e)
        )


'''
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
                chord.wait
            )
        )

        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return {
        "message": "finished"
    }
'''