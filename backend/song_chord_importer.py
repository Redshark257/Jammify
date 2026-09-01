# song_chord_importer.py
import re
import html as html_lib

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def fetch_page(url: str) -> str:
    """
    Download the webpage HTML.
    """

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


def get_page_title(html: str) -> str:
    """
    Get the page title.
    """

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    if soup.title:

        return soup.title.get_text(
            strip=True
        )

    return "Imported Song"


def extract_wiki_content(html: str) -> str:
    """
    Extract Ultimate Guitar's wiki_tab.content.

    Ultimate Guitar stores the actual chord sheet
    inside HTML-encoded application data.
    """

    # Ultimate Guitar uses &quot; around JSON keys/values.
    decoded = html_lib.unescape(html)

    # Find the wiki_tab content.
    match = re.search(
        r'"wiki_tab"\s*:\s*\{\s*"content"\s*:\s*"',
        decoded
    )

    if not match:
        raise ValueError(
            "Could not find Ultimate Guitar song content."
        )

    start = match.end()

    # The content is JSON-escaped.
    #
    # We need to find the closing quote while
    # respecting escaped quotes.
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

    # Decode JSON-style escaped characters.
    raw_content = bytes(
        raw_content,
        "utf-8"
    ).decode(
        "unicode_escape"
    )

    return raw_content


def extract_chords_from_content(content: str):
    """
    Extract Ultimate Guitar [ch]...[/ch] chord tags.

    Example:

        [ch]Am[/ch]
        [ch]E+[/ch]
        [ch]Fmaj7[/ch]

    becomes:

        ["Am", "E+", "Fmaj7"]
    """

    chords = re.findall(
        r"\[ch\](.*?)\[/ch\]",
        content,
        flags=re.IGNORECASE | re.DOTALL
    )

    result = []

    for chord in chords:

        chord = chord.strip()

        if not chord:
            continue

        # Normalize whitespace.
        chord = re.sub(
            r"\s+",
            "",
            chord
        )

        result.append(chord)

    return result


def extract_chords_with_beats(content: str):
    """
    Extract Ultimate Guitar chord tags and estimate
    the number of beats for each chord based on
    horizontal spacing between chord tags.
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

        if not matches:
            continue

        chord_data = []

        # ---------------------------------------------
        # Extract chord names and their positions
        # ---------------------------------------------

        for match in matches:

            chord = match.group(1)

            chord = html_lib.unescape(chord)

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

        # ---------------------------------------------
        # Calculate spacing between chords
        # ---------------------------------------------

        for index, chord in enumerate(chord_data):

            if index < len(chord_data) - 1:

                next_chord = chord_data[index + 1]

                chord["distance"] = (
                    next_chord["position"]
                    - chord["position"]
                )

            else:

                # Last chord on the line.
                #
                # Use the average spacing of the
                # previous chords as its duration.

                if len(chord_data) > 1:

                    distances = [
                        chord_data[i + 1]["position"]
                        - chord_data[i]["position"]
                        for i in range(
                            len(chord_data) - 1
                        )
                    ]

                    chord["distance"] = (
                        sum(distances)
                        / len(distances)
                    )

                else:

                    # Only one chord on this line.
                    chord["distance"] = 1

        # ---------------------------------------------
        # Determine the smallest spacing.
        #
        # The smallest spacing is treated as
        # approximately one beat.
        # ---------------------------------------------

        distances = [
            chord["distance"]
            for chord in chord_data
            if chord["distance"] > 0
        ]

        if not distances:
            continue

        base_distance = min(distances)

        # Prevent division by zero.
        base_distance = max(
            base_distance,
            1
        )

        # ---------------------------------------------
        # Convert spacing to beats.
        # ---------------------------------------------

        for chord in chord_data:

            ratio = (
                chord["distance"]
                / base_distance
            )

            beats = max(
                1,
                round(ratio)
            )

            # Your UI currently supports
            # up to 16 beats.
            beats = min(
                16,
                beats
            )

            result.append({
                "name": chord["name"],
                "beats": beats
            })

    return result


def import_chords_from_url(url: str):

    html = fetch_page(url)

    title = get_page_title(html)

    content = extract_wiki_content(html)

    chords = extract_chords_with_beats(
        content
    )

    if not chords:
        raise ValueError(
            "No chords were found in the song."
        )

    return {
        "title": title,
        "chords": chords
    }




def main():

    song_url = (
        "https://tabs.ultimate-guitar.com/"
        "tab/led-zeppelin/"
        "stairway-to-heaven-chords-1088573"
    )

    song_url = "https://tabs.ultimate-guitar.com/tab/elton-john/tiny-dancer-chords-328198"

    result = import_chords_from_url(
        song_url
    )

    print(result)


if __name__ == "__main__":
    main()
