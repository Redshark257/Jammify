import subprocess
import sys
import tempfile
from pathlib import Path


STEMS = [
    "vocals",
    "drums",
    "bass",
    "guitar",
    "piano",
    "other",
]


def separate_audio(input_file):
    input_file = Path(input_file)

    if not input_file.exists():
        raise FileNotFoundError(
            f"File not found: {input_file}"
        )

    # Create a temporary directory.
    # It will be automatically deleted when the caller exits
    # the context manager.
    temp_dir = tempfile.TemporaryDirectory()
    output_dir = Path(temp_dir.name)

    command = [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        "htdemucs_6s",
        "-o",
        str(output_dir),
        str(input_file),
    ]

    print(f"Separating: {input_file}")
    print("Model: htdemucs_6s")
    print()

    subprocess.run(
        command,
        check=True
    )

    stem_dir = (
        output_dir
        / "htdemucs_6s"
        / input_file.stem
    )

    if not stem_dir.exists():
        temp_dir.cleanup()
        raise FileNotFoundError(
            f"Demucs output directory not found: {stem_dir}"
        )

    stems = {}

    for stem in STEMS:
        path = stem_dir / f"{stem}.wav"

        if path.exists():
            stems[stem] = str(path)

            print(
                f"✓ {stem:8} -> {path}"
            )
        else:
            print(
                f"✗ {stem:8} -> NOT FOUND"
            )

    if "guitar" not in stems:
        temp_dir.cleanup()
        raise FileNotFoundError(
            "Demucs did not produce guitar.wav"
        )

    print("\nSeparation complete!")

    return {
        "temp_dir": temp_dir,
        "directory": str(stem_dir),
        "stems": stems,
    }


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:")
        print("  python splitter.py song.wav")
        sys.exit(1)

    result = separate_audio(sys.argv[1])

    try:
        print(
            f"\nOutput directory: {result['directory']}"
        )

        for stem, path in result["stems"].items():
            print(f"{stem}: {path}")

        # Do whatever processing you need with the WAV files here.
        # They remain available during this block.

    finally:
        # Delete all separated WAV files and the temporary directory.
        result["temp_dir"].cleanup()
        print("\nTemporary stem files deleted.")