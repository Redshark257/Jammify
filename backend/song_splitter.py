import subprocess
import sys
from pathlib import Path


def separate_audio(input_file, output_dir="output"):
    input_file = Path(input_file)

    if not input_file.exists():
        raise FileNotFoundError(f"File not found: {input_file}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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

    subprocess.run(command, check=True)

    stem_dir = output_dir / "htdemucs_6s" / input_file.stem

    print("\nSeparation complete!")
    print(f"Output directory: {stem_dir}\n")

    stems = [
        "vocals",
        "drums",
        "bass",
        "guitar",
        "piano",
        "other",
    ]

    for stem in stems:
        path = stem_dir / f"{stem}.wav"

        if path.exists():
            print(f"✓ {stem:8} -> {path}")
        else:
            print(f"✗ {stem:8} -> NOT FOUND")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:")
        print("  python separate.py song.mp3")
        sys.exit(1)

    separate_audio(sys.argv[1])
