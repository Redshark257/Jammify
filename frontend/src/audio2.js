// audio.js

import * as Tone from "tone";


// ============================================================
// STATE
// ============================================================

let activeVoices = [];
let trackGains = {};
let trackSamplers = {};

let initialized = false;
let preloadPromise = null;


// ============================================================
// INSTRUMENT CONFIGURATION
// ============================================================
//
// Current sample folders:
//
// public/samples/piano/
// public/samples/guitar-acoustic/
//

const instrumentConfigs = {

    grand_piano: {

        folder: "piano",

        urls: {
            C1: "C1.mp3",
            C2: "C2.mp3",
            C3: "C3.mp3",
            C4: "C4.mp3",
            C5: "C5.mp3"
        }

    },


    acoustic_guitar: {

        folder: "guitar-acoustic",

        urls: {
            C3: "C3.mp3",
            C4: "C4.mp3",
            C5: "C5.mp3"
        }

    }

};


// ============================================================
// INSTRUMENT ALIASES
// ============================================================
//
// Keeps compatibility with older data.
//

const instrumentAliases = {

    piano: "grand_piano"

};


// ============================================================
// NORMALIZE INSTRUMENT
// ============================================================

function normalizeInstrument(instrument) {

    const requested =
        instrument || "grand_piano";

    return (
        instrumentAliases[requested] ||
        requested
    );

}


// ============================================================
// GET INSTRUMENT CONFIG
// ============================================================

function getInstrumentConfig(instrument) {

    const normalized =
        normalizeInstrument(instrument);

    const config =
        instrumentConfigs[normalized];

    if (!config) {

        console.warn(
            `Unknown instrument "${instrument}". Using Grand Piano.`
        );

        return instrumentConfigs.grand_piano;

    }

    return config;

}


// ============================================================
// CREATE SAMPLER
// ============================================================

function createSampler(instrument) {

    const normalized =
        normalizeInstrument(instrument);

    const config =
        getInstrumentConfig(normalized);


    return new Tone.Sampler({

        urls: config.urls,

        baseUrl:
            `/samples/${config.folder}/`,

        release: 0.08,

        onerror: error => {

            console.error(
                `Error loading ${normalized} samples:`,
                error
            );

        }

    });

}


// ============================================================
// PRELOAD INSTRUMENTS
// ============================================================
//
// IMPORTANT:
//
// We load the samples once after the user clicks Play.
//
// This prevents playChord() from waiting for sample
// downloads between chords.
//

async function preloadInstruments() {

    if (preloadPromise) {

        return preloadPromise;

    }


    preloadPromise = (async () => {

        Object.keys(
            instrumentConfigs
        ).forEach(instrument => {

            const key =
                `__preload_${instrument}`;


            if (!trackSamplers[key]) {

                trackSamplers[key] = {

                    sampler:
                        createSampler(instrument),

                    instrument

                };

            }

        });


        await Tone.loaded();

    })();


    try {

        await preloadPromise;

    }
    catch (error) {

        preloadPromise = null;

        throw error;

    }

}


// ============================================================
// LOAD INSTRUMENT FOR TRACK
// ============================================================

async function loadInstrumentForTrack(
    trackId,
    instrument
) {

    const normalized =
        normalizeInstrument(instrument);


    const existing =
        trackSamplers[trackId];


    /*
     * Reuse existing sampler if the instrument
     * has not changed.
     */

    if (
        existing &&
        existing.instrument === normalized
    ) {

        return existing.sampler;

    }


    /*
     * Dispose old sampler if the track
     * changed instruments.
     */

    if (existing) {

        try {

            existing.sampler.dispose();

        }
        catch (error) {

            console.warn(
                "Unable to dispose old sampler:",
                error
            );

        }

    }


    /*
     * Create track sampler.
     */

    const sampler =
        createSampler(normalized);


    trackSamplers[trackId] = {

        sampler,

        instrument: normalized

    };


    /*
     * Normally this has already completed
     * during unlockAudio().
     *
     * This is only relevant if an instrument
     * is changed dynamically.
     */

    // await Tone.loaded();


    return sampler;

}


// ============================================================
// UNLOCK WEB AUDIO
// ============================================================

export async function unlockAudio() {

    /*
     * Must happen after a user interaction.
     */

    await Tone.start();


    if (!initialized) {

        initialized = true;

    }


    /*
     * Load piano and acoustic guitar
     * before playback begins.
     */

    await preloadInstruments();

}


// ============================================================
// MIDI → NOTE NAME
// ============================================================

function midiToNote(midi) {

    return Tone.Frequency(
        midi,
        "midi"
    ).toNote();

}


// ============================================================
// CREATE / GET TRACK GAIN
// ============================================================

function getTrackGain(
    trackId,
    volume
) {

    if (!trackGains[trackId]) {

        trackGains[trackId] =
            new Tone.Gain(
                Number(volume)
            ).toDestination();

    }

    return trackGains[trackId];

}


// ============================================================
// CHANGE TRACK VOLUME
// ============================================================

export function updateTrackVolume(
    trackId,
    volume
) {

    const gain =
        trackGains[trackId];


    if (!gain) {

        return;

    }


    gain.gain.rampTo(
        Number(volume),
        0.05
    );

}

export async function prepareTrackInstrument(trackId, instrument) {

    const normalized = normalizeInstrument(instrument);

    const existing = trackSamplers[trackId];

    if (
        existing &&
        existing.instrument === normalized
    ) {
        return;
    }

    const sampler = createSampler(normalized);

    trackSamplers[trackId] = {
        sampler,
        instrument: normalized
    };

    await Tone.loaded();
}



// ============================================================
// PLAY CHORD
// ============================================================

export async function playChord(

    notes,

    durationBeats,

    bpm,

    volume = 0.8,

    instrument = "grand_piano",

    trackId,

    speed = 1

) {

    /*
     * Nothing to play.
     */

    if (
        !notes ||
        notes.length === 0
    ) {

        return;

    }


    const normalizedInstrument =
        normalizeInstrument(instrument);


    /*
     * Get sampler for this track.
     */

    const sampler =
        await loadInstrumentForTrack(
            trackId,
            normalizedInstrument
        );


    /*
     * Get track gain.
     */

    const gain =
        getTrackGain(
            trackId,
            volume
        );


    /*
     * Connect sampler to the track gain
     * only once.
     */

    if (!sampler.__connectedToTrack) {

        sampler.connect(gain);

        sampler.__connectedToTrack = true;

    }


    /*
     * Update volume.
     */

    gain.gain.rampTo(
        Number(volume),
        0.02
    );


    /*
     * Calculate duration in seconds.
     */

    const duration =
        (
            60 /
            Number(bpm)
        ) *
        Number(durationBeats);


    /*
     * Convert MIDI notes to Tone note names.
     */

    const noteNames =
        notes.map(
            midiToNote
        );


    /*
     * Clamp speed between 0 and 1.
     */

    const normalizedSpeed =
        Math.min(
            1,
            Math.max(
                0,
                Number(speed ?? 1)
            )
        );


    // ========================================================
    // SPEED 0
    // ========================================================
    //
    // Play only the lowest note.
    //

    if (
        normalizedSpeed === 0
    ) {

        sampler.triggerAttackRelease(

            noteNames[0],

            duration,

            Tone.now()

        );

    }


    // ========================================================
    // SPEED 1
    // ========================================================
    //
    // Play the whole chord simultaneously.
    //

    else if (
        normalizedSpeed >= 1
    ) {

        sampler.triggerAttackRelease(

            noteNames,

            duration,

            Tone.now()

        );

    }


    // ========================================================
    // BETWEEN 0 AND 1
    // ========================================================
    //
    // Arpeggio.
    //

    else {

        const notesPerBeat =
            Math.max(
                1,
                Math.round(
                    normalizedSpeed * 4
                )
            );


        const beatDuration =
            60 /
            Number(bpm);


        const noteInterval =
            beatDuration /
            notesPerBeat;


        const startTime =
            Tone.now();


        noteNames.forEach(
            (
                note,
                index
            ) => {

                const offset =
                    index *
                    noteInterval;


                if (
                    offset >= duration
                ) {

                    return;

                }


                const noteDuration =
                    duration -
                    offset;


                sampler.triggerAttackRelease(

                    note,

                    noteDuration,

                    startTime + offset

                );

            }
        );

    }


    /*
     * Track active sampler.
     */

    activeVoices.push({

        trackId,

        sampler

    });

}


// ============================================================
// STOP NOTES FOR ONE TRACK
// ============================================================

export function stopTrackNotes(
    trackId
) {

    const trackVoices =
        activeVoices.filter(
            voice =>
                voice.trackId === trackId
        );


    trackVoices.forEach(
        voice => {

            try {

                voice.sampler.releaseAll();

            }
            catch (error) {

                console.warn(
                    "Unable to stop track:",
                    error
                );

            }

        }
    );


    activeVoices =
        activeVoices.filter(
            voice =>
                voice.trackId !== trackId
        );

}


// ============================================================
// STOP EVERYTHING
// ============================================================

export function stopAllNotes() {

    Object.values(
        trackSamplers
    ).forEach(
        ({ sampler }) => {

            try {

                sampler.releaseAll();

            }
            catch (error) {

                console.warn(
                    "Unable to stop sampler:",
                    error
                );

            }

        }
    );


    activeVoices = [];

}


// ============================================================
// REMOVE TRACK AUDIO
// ============================================================

export function removeTrackAudio(
    trackId
) {

    /*
     * Stop currently playing notes.
     */

    stopTrackNotes(trackId);


    /*
     * Dispose sampler.
     */

    const samplerData =
        trackSamplers[trackId];


    if (samplerData) {

        try {

            samplerData.sampler.dispose();

        }
        catch (error) {

            console.warn(
                "Unable to dispose sampler:",
                error
            );

        }


        delete trackSamplers[trackId];

    }


    /*
     * Dispose track gain.
     */

    const gain =
        trackGains[trackId];


    if (gain) {

        try {

            gain.dispose();

        }
        catch (error) {

            console.warn(
                "Unable to dispose gain:",
                error
            );

        }


        delete trackGains[trackId];

    }

}
