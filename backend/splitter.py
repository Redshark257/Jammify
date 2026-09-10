import subprocess
import sys
from pathlib import Path


STEMS = [
    "vocals",
    "drums",
    "bass",
    "guitar",
    "piano",
    "other",
]


def separate_audio(input_file, output_dir):
    input_file = Path(input_file)
    output_dir = Path(output_dir)

    if not input_file.exists():
        raise FileNotFoundError(
            f"File not found: {input_file}"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

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
        raise FileNotFoundError(
            "Demucs did not produce guitar.wav"
        )

    print("\nSeparation complete!")

    return {
        "directory": str(stem_dir),
        "stems": stems,
    }
