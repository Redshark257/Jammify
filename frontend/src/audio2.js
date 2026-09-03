import * as Tone from "tone";


// ============================================================
// STATE
// ============================================================

let instrumentSamplers = {};
let trackGains = {};
let samplerConnections = {};

let masterGain = null;
let initialized = false;
let preloadPromise = null;


// ============================================================
// INSTRUMENT CONFIGURATION
// ============================================================

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

    },

    electric_guitar: {

        folder: "guitar-electric",

        urls: {
            C3: "C3.mp3",
            C4: "C4.mp3",
            C5: "C5.mp3"
        }

    },

    organ: {

        folder: "organ",

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


    console.log(
        `[audio] Creating sampler: ${normalized}`
    );


    const sampler =
        new Tone.Sampler({

            urls: config.urls,

            baseUrl:
                `/samples/${config.folder}/`,

            release: 0.08,

            onload: () => {

                console.log(
                    `[audio] Loaded instrument: ${normalized}`
                );

            },

            onerror: error => {

                console.error(
                    `[audio] Error loading ${normalized} samples:`,
                    error
                );

            }

        });


    return sampler;

}


// ============================================================
// GET / CREATE INSTRUMENT SAMPLER
// ============================================================

function getInstrumentSampler(instrument) {

    const normalized =
        normalizeInstrument(instrument);


    if (
        instrumentSamplers[normalized]
    ) {

        return instrumentSamplers[normalized];

    }


    const sampler =
        createSampler(normalized);


    instrumentSamplers[normalized] =
        sampler;


    return sampler;

}


// ============================================================
// PRELOAD INSTRUMENTS
// ============================================================
//
// IMPORTANT:
//
// This function runs only once.
//
// It creates one sampler for each configured instrument
// and waits for Tone.js to finish loading the samples.
//
// prepareTrackInstrument() DOES NOT call Tone.loaded().
// ============================================================

async function preloadInstruments() {

    if (preloadPromise) {

        return preloadPromise;

    }


    preloadPromise =
        (async () => {

            console.log(
                "[audio] Starting instrument preload..."
            );


            Object.keys(
                instrumentConfigs
            ).forEach(instrument => {

                getInstrumentSampler(
                    instrument
                );

            });


            /*
             * Wait for Tone.js samples to load.
             *
             * This is intentionally done ONCE,
             * rather than once per track/chord.
             */

            await Tone.loaded();


            console.log(
                "[audio] Instrument preload complete."
            );

        })();


    try {

        await preloadPromise;

    }
    catch (error) {

        console.error(
            "[audio] Instrument preload failed:",
            error
        );


        preloadPromise = null;

        throw error;

    }

}


// ============================================================
// UNLOCK WEB AUDIO
// ============================================================

export async function unlockAudio() {

    console.log(
        "[audio] Unlocking audio..."
    );


    /*
     * Must happen after a user interaction.
     */

    await Tone.start();

    if (!masterGain) {
        masterGain = new Tone.Gain(1).toDestination();
    }


    initialized = true;


    /*
     * Load instruments once.
     */

    await preloadInstruments();


    console.log(
        "[audio] Audio ready."
    );

}


// ============================================================
// PREPARE TRACK INSTRUMENT
// ============================================================
//
// This function is intentionally lightweight.
//
// The old implementation did:
//
//     createSampler()
//     await Tone.loaded()
//
// for every track.
//
// That could cause playback to appear frozen.
//
// Now all instruments are already loaded by unlockAudio().
// ============================================================

export async function prepareTrackInstrument(
    trackId,
    instrument
) {

    const normalized =
        normalizeInstrument(instrument);


    const sampler =
        getInstrumentSampler(
            normalized
        );


    return sampler;

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

    /*
     * Track ID should normally exist.
     */

    const key =
        String(trackId);


    if (
        !trackGains[key]
    ) {

        trackGains[key] =
            new Tone.Gain(
                Number(volume)
            ).connect(masterGain);;

    }


    return trackGains[key];

}


// ============================================================
// CHANGE TRACK VOLUME
// ============================================================

export function updateTrackVolume(
    trackId,
    volume
) {

    const gain =
        trackGains[
            String(trackId)
        ];


    if (!gain) {

        return;

    }


    gain.gain.rampTo(
        Number(volume),
        0.05
    );

}


export function updateMasterVolume(volume) {

    if (!masterGain) {
        return;
    }

    masterGain.gain.rampTo(
        Math.max(
            0,
            Math.min(
                1,
                Number(volume)
            )
        ),
        0.05
    );

}


// ============================================================
// CONNECT SAMPLER TO TRACK GAIN
// ============================================================

function connectSamplerToTrack(
    sampler,
    trackId,
    gain
) {

    const normalizedTrackId =
        String(trackId);


    /*
     * Each sampler can be connected to
     * multiple track gains.
     *
     * We therefore use:
     *
     *     instrument + track
     *
     * as the connection key.
     */

    const samplerKey =
        Object.keys(
            instrumentSamplers
        ).find(
            key =>
                instrumentSamplers[key] === sampler
        );


    const connectionKey =
        `${samplerKey}:${normalizedTrackId}`;


    if (
        samplerConnections[connectionKey]
    ) {

        return;

    }


    sampler.connect(gain);


    samplerConnections[connectionKey] =
        true;

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
        normalizeInstrument(
            instrument
        );


    /*
     * Get already-loaded sampler.
     */

    const sampler =
        getInstrumentSampler(
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
     * Connect this instrument to
     * this track exactly once.
     */

    connectSamplerToTrack(
        sampler,
        trackId,
        gain
    );


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
    // Play entire chord simultaneously.
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

}


// ============================================================
// STOP NOTES FOR ONE TRACK
// ============================================================

export function stopTrackNotes(
    trackId
) {

    const normalizedTrackId =
        String(trackId);


    /*
     * releaseAll() on a shared sampler would
     * stop notes belonging to OTHER tracks too.
     *
     * Therefore we cannot safely use it here
     * with shared samplers.
     *
     * We instead stop all currently playing
     * samplers.
     *
     * This is safe, but means stopping one track
     * can also stop another track's notes.
     *
     * For your current Play/Pause/Stop behavior,
     * stopAllNotes() is the important function.
     */

    Object.values(
        instrumentSamplers
    ).forEach(
        sampler => {

            try {

                sampler.releaseAll();

            }
            catch (error) {

                console.warn(
                    "[audio] Unable to stop track:",
                    normalizedTrackId,
                    error
                );

            }

        }
    );

}


// ============================================================
// STOP EVERYTHING
// ============================================================

export function stopAllNotes() {

    Object.values(
        instrumentSamplers
    ).forEach(
        sampler => {

            try {

                sampler.releaseAll();

            }
            catch (error) {

                console.warn(
                    "[audio] Unable to stop sampler:",
                    error
                );

            }

        }
    );

}


// ============================================================
// REMOVE TRACK AUDIO
// ============================================================

export function removeTrackAudio(
    trackId
) {

    const normalizedTrackId =
        String(trackId);


    /*
     * Stop notes.
     */

    stopTrackNotes(
        normalizedTrackId
    );


    /*
     * Dispose track gain.
     */

    const gain =
        trackGains[
            normalizedTrackId
        ];


    if (gain) {

        try {

            gain.dispose();

        }
        catch (error) {

            console.warn(
                "[audio] Unable to dispose gain:",
                error
            );

        }


        delete trackGains[
            normalizedTrackId
        ];

    }


    /*
     * Remove connection bookkeeping.
     */

    Object.keys(
        samplerConnections
    ).forEach(
        key => {

            if (
                key.endsWith(
                    `:${normalizedTrackId}`
                )
            ) {

                delete samplerConnections[key];

            }

        }
    );

}


// ============================================================
// OPTIONAL CLEANUP
// ============================================================

export function disposeAudio() {

    stopAllNotes();


    Object.values(
        instrumentSamplers
    ).forEach(
        sampler => {

            try {

                sampler.dispose();

            }
            catch (error) {

                console.warn(
                    "[audio] Unable to dispose sampler:",
                    error
                );

            }

        }
    );


    Object.values(
        trackGains
    ).forEach(
        gain => {

            try {

                gain.dispose();

            }
            catch (error) {

                console.warn(
                    "[audio] Unable to dispose gain:",
                    error
                );

            }

        }
    );

    if (masterGain) {

        try {
            masterGain.dispose();
        }
        catch (error) {
            console.warn(
                "[audio] Unable to dispose master gain:",
                error
            );
        }

    }

    masterGain = null;



    instrumentSamplers = {};
    trackGains = {};
    samplerConnections = {};

    preloadPromise = null;
    initialized = false;

}
