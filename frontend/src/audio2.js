// Audio.js

import * as Tone from "tone";


// ============================================================
// STATE
// ============================================================

let activeVoices = [];
let trackGains = {};
let trackSamplers = {};
let initialized = false;


// ============================================================
// INSTRUMENT CONFIGURATION
// ============================================================
//
// These are the folders you copied into:
//
// public/samples/
//

// The filenames below correspond to the tonejs-instruments
// sample sets.
//
// Tone.Sampler will automatically pitch-shift between these
// sampled notes, so we don't need every single note.
//

const instrumentConfigs = {


    piano: {

        folder: "piano",

        urls: {
            C1: "C1.mp3",
            C2: "C2.mp3",
            C3: "C3.mp3",
            C4: "C4.mp3",
        },
    },

    bass: {
        folder: "bass-electric",

        urls: {
            E1: "E1.mp3",
            E2: "E2.mp3",
            E3: "E3.mp3",
            E4: "E4.mp3",
        },
    },


    acoustic_guitar: {
        folder: "guitar-acoustic",

        urls: {
            C3: "C3.mp3",
            C4: "C4.mp3",
            C5: "C5.mp3",
        },
    },


    electric_guitar: {
        folder: "guitar-electric",

        urls: {
            A2: "A2.mp3",
            A3: "A3.mp3",
            A4: "A4.mp3",
            A5: "A5.mp3",
        },
    },


    nylon_guitar: {
        folder: "guitar-nylon",

        urls: {
            A2: "A2.mp3",
            A3: "A3.mp3",
            A4: "A4.mp3",
            A5: "A5.mp3",
        },
    },


    organ: {
        folder: "organ",

        urls: {
            C2: "C2.mp3",
            C3: "C3.mp3",
            C4: "C4.mp3",
            C5: "C5.mp3",
        },
    },

};


// ============================================================
// INSTRUMENT ALIASES
// ============================================================
//
// This lets your existing application continue using names
// such as:
//
// acoustic_guitar
// rock_guitar
// finger_bass
// church_organ
//
// while internally using the new sample folders.
//

const instrumentAliases = {

    grand_piano: "piano",
    acoustic_guitar: "acoustic_guitar",
};


// ============================================================
// GET INSTRUMENT CONFIG
// ============================================================

function getInstrumentConfig(instrument) {

    const normalizedInstrument =
        instrumentAliases[instrument] ||
        instrument;

    const config =
        instrumentConfigs[normalizedInstrument];

    if (!config) {

        throw new Error(
            `Unknown instrument: ${instrument}`
        );

    }

    return config;
}


// ============================================================
// CREATE SAMPLER
// ============================================================

function createSampler(instrument) {

    const config =
        getInstrumentConfig(instrument);


    /*
     * public/ is the web root in Vite.
     *
     * Therefore:
     *
     * public/samples/organ/C4.mp3
     *
     * becomes:
     *
     * /samples/organ/C4.mp3
     */

    const sampler =
        new Tone.Sampler({

            urls: config.urls,

            baseUrl:
                `/samples/${config.folder}/`,

            release: 0.1,

        });


    return sampler;
}


// ============================================================
// LOAD INSTRUMENT FOR TRACK
// ============================================================
//
// Every track gets its own sampler.
//
// Example:
//
// Track 1 → piano/organ/etc.
// Track 2 → guitar
// Track 3 → guitar
//
// Even if Track 2 and Track 3 use the same instrument,
// they have independent samplers.
//

async function loadInstrumentForTrack(
    trackId,
    instrument
) {

    const existing =
        trackSamplers[trackId];


    /*
     * Reuse the sampler if the track is
     * already using the same instrument.
     */

    if (
        existing &&
        existing.instrument === instrument
    ) {

        return existing.sampler;

    }


    /*
     * Dispose old sampler if the track
     * is changing instruments.
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
     * Create the new sampler.
     */

    const sampler =
        createSampler(instrument);


    /*
     * Store it immediately.
     *
     * This prevents multiple calls from
     * creating duplicate samplers.
     */

    trackSamplers[trackId] = {

        sampler,

        instrument,

    };


    /*
     * Wait until Tone has finished loading
     * all samples for this sampler.
     */

    await Tone.loaded();


    return sampler;
}


// ============================================================
// UNLOCK WEB AUDIO
// ============================================================

export async function unlockAudio() {

    await Tone.start();

    if (!initialized) {

        initialized = true;

    }

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


// ============================================================
// PLAY CHORD
// ============================================================

export async function playChord(

    notes,

    durationBeats,

    bpm,

    volume = 0.8,

    instrument = "organ",

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


    /*
     * Load sampler for this track.
     */

    const sampler =
        await loadInstrumentForTrack(
            trackId,
            instrument
        );


    /*
     * Get this track's gain.
     */

    const gain =
        getTrackGain(
            trackId,
            volume
        );


    /*
     * Connect sampler to this
     * track's gain.
     *
     * We mark the sampler so it
     * isn't connected multiple times.
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
     * Calculate duration.
     *
     * BPM 120:
     *
     * 1 beat = 0.5 seconds
     * 2 beats = 1 second
     * 4 beats = 2 seconds
     */

    const duration =
        (
            60 /
            Number(bpm)
        ) *
        Number(durationBeats);


    /*
     * Convert MIDI numbers into
     * note names.
     *
     * Example:
     *
     * 60 → C4
     * 64 → E4
     * 67 → G4
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
    // Only play the lowest note.
    //

    if (
        normalizedSpeed === 0
    ) {

        sampler.triggerAttackRelease(

            noteNames[0],

            duration

        );

    }


    // ========================================================
    // SPEED 1
    // ========================================================
    //
    // Play the entire chord simultaneously.
    //

    else if (
        normalizedSpeed >= 1
    ) {

        sampler.triggerAttackRelease(

            noteNames,

            duration

        );

    }


    // ========================================================
    // BETWEEN 0 AND 1
    // ========================================================
    //
    // Arpeggio.
    //

    else {

        /*
         * Convert speed to notes per beat.
         *
         * 0.25 → 1 note / beat
         * 0.50 → 2 notes / beat
         * 0.75 → 3 notes / beat
         */

        const notesPerBeat =
            Math.max(
                1,
                Math.round(
                    normalizedSpeed * 4
                )
            );


        /*
         * Duration of one beat.
         */

        const beatDuration =
            60 /
            Number(bpm);


        /*
         * Time between arpeggio notes.
         */

        const noteInterval =
            beatDuration /
            notesPerBeat;


        /*
         * Use one shared Tone timestamp.
         */

        const startTime =
            Tone.now();


        /*
         * Schedule every note.
         */

        noteNames.forEach(
            (
                note,
                index
            ) => {

                /*
                 * Start offset.
                 */

                const offset =
                    index *
                    noteInterval;


                /*
                 * Don't start a note after
                 * the chord has finished.
                 */

                if (
                    offset >= duration
                ) {

                    return;

                }


                /*
                 * Sustain the note until
                 * the end of the chord.
                 */

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
     * Keep track of this sampler so
     * it can be stopped later.
     */

    activeVoices.push({

        trackId,

        sampler,

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