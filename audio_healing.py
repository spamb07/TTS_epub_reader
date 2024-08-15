#!/usr/bin/env python3

import argparse
import json
import re
import os
import tempfile
from pydub import AudioSegment
import boto3
import eyed3

# AWS Polly voices data with associated costs per type
polly_voices = {
    "en-US": [
        {"name": "Danielle", "gender": "Female", "types": {"standard": 4.00}},
        {"name": "Gregory", "gender": "Male", "types": {"standard": 4.00}},
        {"name": "Ivy", "gender": "Female (child)", "types": {"neural": 16.00}},
        {"name": "Joanna", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Kendra", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Kimberly", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Salli", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Joey", "gender": "Male", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Justin", "gender": "Male (child)", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Kevin", "gender": "Male (child)", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Matthew", "gender": "Male", "types": {"standard": 4.00, "long-form": 100.00}},
        {"name": "Ruth", "gender": "Female", "types": {"generative": 30.00, "long-form": 100.00, "neural": 16.00}},
        {"name": "Stephen", "gender": "Male", "types": {"long-form": 100.00}},
    ],
    "en-GB": [
        {"name": "Amy", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00, "generative": 30.00}},
        {"name": "Emma", "gender": "Female", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Brian", "gender": "Male", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Arthur", "gender": "Male", "types": {"standard": 4.00, "neural": 16.00}},
        {"name": "Geraint", "gender": "Male", "types": {"standard": 4.00}},
    ],
    "en-AU": [
        {"name": "Nicole", "gender": "Female", "types": {"standard": 4.00}},
        {"name": "Olivia", "gender": "Female", "types": {"neural": 16.00}},
        {"name": "Russell", "gender": "Male", "types": {"standard": 4.00}},
    ],
    "en-IN": [
        {"name": "Aditi", "gender": "Female", "types": {"standard": 4.00}},
        {"name": "Raveena", "gender": "Female", "types": {"standard": 4.00}},
        {"name": "Kajal", "gender": "Female", "types": {"neural": 16.00}},
    ],
    "en-IE": [
        {"name": "Niamh", "gender": "Female", "types": {"neural": 16.00, "standard": 4.00}},
    ],
    "en-NZ": [
        {"name": "Aria", "gender": "Female", "types": {"neural": 16.00}},
    ],
    "en-ZA": [
        {"name": "Ayanda", "gender": "Female", "types": {"neural": 16.00, "standard": 4.00}},
    ],
    "en-GB-WLS": [
        {"name": "Geraint", "gender": "Male", "types": {"standard": 4.00}},
    ],
}

def calculate_cost(ssml_queries, selected_voice, verbose=False):
    voice_language = selected_voice["language"]
    voice_name = selected_voice["name"]
    voice_type = selected_voice["type"]

    # Find the cost per million characters based on the voice and type
    cost_per_million = None
    for voice in polly_voices.get(voice_language, []):
        if voice["name"] == voice_name and voice_type in voice["types"]:
            cost_per_million = voice["types"][voice_type]
            break

    if cost_per_million is None:
        raise ValueError(f"Cost not found for voice {voice_name} with type {voice_type}")

    # Calculate the total cost based on the number of characters in the SSML
    total_characters = 0
    for time_key, content in ssml_queries.items():
        total_characters += len(content["ssml"])

    if verbose:
        print(f"Total characters across all SSML queries: {total_characters}")

    total_cost = (total_characters / 1_000_000) * cost_per_million

    return total_cost


def load_audio_segment(file_path):
    return AudioSegment.from_mp3(file_path)


def save_audio_segment(audio_segment, file_path):
    audio_segment.export(file_path, format="mp3")


def parse_lrc_file(lrc_file):
    lyrics = {}
    with open(lrc_file, 'r') as file:
        lines = file.readlines()
        for line in lines:
            match = re.match(r"\[(\d+):(\d+)\.(\d+)\](.*)", line)
            if match:
                time_key = timestamp_to_milliseconds(match.group(0))
                lyrics[time_key] = {"original": match.group(4).strip()}
    return lyrics


def find_lines_with_word(lyrics, target_word):
    result = {}
    for time_key, content in lyrics.items():
        if target_word.lower() in content["original"].lower():
            result[time_key] = content
    return result


def calculate_ssml_replacement(lyrics, all_lyrics, replacement_text, target_word):
    sorted_time_keys = sorted(all_lyrics.keys())

    for i, time_key in enumerate(sorted_time_keys):
        content = lyrics.get(time_key)
        if content:
            # Replace only the target word within the line (case insensitive)
            original_line = content["original"]
            new_line = re.sub(re.escape(target_word), replacement_text, original_line, flags=re.IGNORECASE)
            content["new"] = new_line
            content["ssml"] = f"<speak>{new_line}</speak>"

            if i + 1 < len(sorted_time_keys):
                content["end_time"] = sorted_time_keys[i + 1]
            else:
                content["end_time"] = None

    return lyrics


def calculate_splice_times(audio_segment, lyrics):
    for time_key, content in lyrics.items():
        start_splice, start_half_length = find_silence_splice_point(audio_segment, time_key, "start")
        end_splice, end_half_length = find_silence_splice_point(audio_segment, content.get("end_time", None), "end")

        content["start_splice"] = start_splice
        content["start_splice_half_length"] = start_half_length
        content["end_splice"] = end_splice
        content["end_splice_half_length"] = end_half_length

    return lyrics


def find_silence_splice_point(audio_segment, start_time, mode="start"):
    if mode == "start":
        return find_start_splice_point(audio_segment, start_time)
    elif mode == "end":
        return find_end_splice_point(audio_segment, start_time)


def find_start_splice_point(audio_segment, start_time):
    silence_threshold = -60  # dBFS value below which we consider it as silence
    after_start_splice = start_time

    # Forward scan for the last millisecond of silence
    while after_start_splice < len(audio_segment) and audio_segment[after_start_splice:after_start_splice + 1].dBFS < silence_threshold:
        after_start_splice += 1

    # Backward scan for the first millisecond of silence
    before_start_splice = after_start_splice
    while before_start_splice > 0 and audio_segment[before_start_splice - 1:before_start_splice].dBFS >= silence_threshold:
        before_start_splice -= 1

    # Calculate start_splice as the average of before and after splices
    start_splice = (before_start_splice + after_start_splice) // 2
    start_half_length = (after_start_splice - before_start_splice) // 2

    return start_splice, start_half_length


def find_end_splice_point(audio_segment, end_time):
    if end_time is None:
        return None, None

    silence_threshold = -60  # dBFS value below which we consider it as silence
    after_end_splice = end_time

    # Backward scan for the last millisecond of silence
    while after_end_splice > 0 and audio_segment[after_end_splice - 1:after_end_splice].dBFS < silence_threshold:
        after_end_splice -= 1

    # Forward scan for the first millisecond of silence
    before_end_splice = after_end_splice
    while before_end_splice < len(audio_segment) and audio_segment[before_end_splice:before_end_splice + 1].dBFS >= silence_threshold:
        before_end_splice += 1

    # Calculate end_splice as the average of before and after splices
    end_splice = (before_end_splice + after_end_splice) // 2
    end_half_length = (before_end_splice - after_end_splice) // 2

    return end_splice, end_half_length


def generate_readings_with_polly(lyrics, voice_id, engine):
    polly = boto3.client('polly')
    for time_key, content in lyrics.items():
        response = polly.synthesize_speech(
            Text=content["ssml"],
            TextType="ssml",
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine=engine
        )
        audio_stream = response['AudioStream'].read()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_stream)
        temp_file.close()

        # Load the generated audio segment
        ready_to_splice = AudioSegment.from_mp3(temp_file.name)
        os.remove(temp_file.name)

        # Calculate local start and end splice times based on silence
        ready_to_splice = calculate_local_splice_times(ready_to_splice, content)

        content["ready_to_splice"] = ready_to_splice

    return lyrics


def calculate_local_splice_times(ready_to_splice, content):
    """
    Calculates the local start and end splice times for the Polly-generated audio.

    Args:
        ready_to_splice (AudioSegment): The Polly-generated audio segment to be spliced.
        content (dict): A dictionary containing information about the start and end splice times.

    Returns:
        AudioSegment: The adjusted audio segment with the calculated splice times.
    """

    # Step 4b: Calculate the local start splice time
    silence_threshold = -60  # dBFS value below which we consider it as silence
    start_splice_half_length = content["start_splice_half_length"]

    # Find the last millisecond of silence from the beginning of the Polly read line
    local_start_splice_time = 0
    while local_start_splice_time < len(ready_to_splice) and ready_to_splice[local_start_splice_time:local_start_splice_time + 1].dBFS < silence_threshold:
        local_start_splice_time += 1
    local_start_splice_time -= 1

    # Adjust the local start splice time by subtracting the start_splice_half_length
    adjusted_start_splice_time = local_start_splice_time - start_splice_half_length
    if adjusted_start_splice_time < 0:
        # Pad with silence if the adjusted start splice time is negative
        silence_padding = AudioSegment.silent(duration=abs(adjusted_start_splice_time))
        ready_to_splice = silence_padding + ready_to_splice
    else:
        # Otherwise, cut off that much silence from the beginning
        ready_to_splice = ready_to_splice[adjusted_start_splice_time:]

    # Step 4c: Calculate the local end splice time
    end_splice_half_length = content.get("end_splice_half_length")

    if end_splice_half_length is not None:
        # Find the last silent millisecond walking backwards from the end of the Polly reading
        local_end_splice_time = len(ready_to_splice)
        while local_end_splice_time > 0 and ready_to_splice[local_end_splice_time - 1:local_end_splice_time].dBFS < silence_threshold:
            local_end_splice_time -= 1
        local_end_splice_time += 1

        # Adjust the local end splice time by adding the end_splice_half_length
        adjusted_end_splice_time = local_end_splice_time + end_splice_half_length
        if adjusted_end_splice_time > len(ready_to_splice):
            # Pad additional silence if the adjusted end splice time exceeds the length of the reading
            silence_padding = AudioSegment.silent(duration=adjusted_end_splice_time - len(ready_to_splice))
            ready_to_splice = ready_to_splice + silence_padding
        else:
            # Otherwise, remove the silence after that point
            ready_to_splice = ready_to_splice[:adjusted_end_splice_time]

    # Step 4d: Return the adjusted "ready_to_splice" audio segment
    return ready_to_splice


def splice_audio_segments(audio_segment, lyrics):
    current_output = audio_segment
    delta_time = 0

    for time_key, content in lyrics.items():
        start_splice = content["start_splice"] + delta_time
        end_splice = content.get("end_splice", None)

        if end_splice is None:
            # If end_slice is None, this means we're dealing with the last segment, so just use till the end of the audio
            current_output = current_output[:start_splice] + content["ready_to_splice"]
            end_time = len(current_output)
        else:
            end_splice += delta_time
            before_splice = current_output[:start_splice]
            after_splice = current_output[end_splice:]

            # Combine the segments
            current_output = before_splice + content["ready_to_splice"] + after_splice

            # Calculate the new end_time after the splice, adding the end_splice_half_length
            end_time = start_splice + len(content["ready_to_splice"]) + content.get("end_splice_half_length", 0)

            # Update delta_time for the next iteration
            delta_time += len(content["ready_to_splice"]) - (end_splice - start_splice)

        # Update the start time and end time of the new lyric
        content["new_lyric_start"] = start_splice
        content["end_time"] = end_time

    return current_output, lyrics


def update_lyrics_file(original_lyrics, lyrics, output_lrc_file):
    with open(output_lrc_file, 'w') as file:
        time_shift = 0
        sorted_time_keys = sorted(original_lyrics.keys())

        for i, time_key in enumerate(sorted_time_keys):
            if time_key in lyrics:
                # Calculate the new start time and new end time
                new_start_time = lyrics[time_key]["new_lyric_start"]
                end_time = lyrics[time_key].get("end_time", None)

                if i + 1 < len(sorted_time_keys):
                    original_end_time = sorted_time_keys[i + 1]
                else:
                    original_end_time = None

                if end_time is not None and original_end_time is not None:
                    # Calculate time shift only if original_end_time is defined
                    time_shift = (end_time - original_end_time)

                # Write the updated line
                line = f"[{new_start_time // 60000}:{(new_start_time % 60000) // 1000}.{(new_start_time % 1000) // 10}]{lyrics[time_key]['new']}\n"
            else:
                # Adjust the time_key by the current time_shift
                adjusted_time_key = time_key + time_shift

                # Write the original line with the adjusted time
                line = f"[{adjusted_time_key // 60000}:{(adjusted_time_key % 60000) // 1000}.{(adjusted_time_key % 1000) // 10}]{original_lyrics[time_key]['original']}\n"

            file.write(line)


def validate_timestamp_format(timestamp):
    match = re.match(r"^\[?\d{1,2}:\d{2}\.\d{2}\]?$", timestamp)
    return match is not None


def timestamp_to_milliseconds(timestamp):
    match = re.match(r"\[?(\d+):(\d+)\.(\d+)\]?", timestamp)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2)) + int(match.group(3)) / 100.0
        return int((minutes * 60 + seconds) * 1000)
    return None


def main(args):
    audio_segment = load_audio_segment(args.mp3_file)
    lyrics = parse_lrc_file(args.lrc_file)

    if args.word:
        lyrics_to_replace = find_lines_with_word(lyrics, args.target)
    else:
        if not validate_timestamp_format(args.target):
            parser.error("The target must be a valid timestamp when the --word flag is not used.")
        timestamp = timestamp_to_milliseconds(args.target)
        lyrics_to_replace = {timestamp: lyrics[timestamp]}

    lyrics_to_replace = calculate_ssml_replacement(lyrics_to_replace, lyrics, args.replacement, args.target)

    # Calculate cost if requested
    selected_voice = {
        "language": args.voice_language,
        "name": args.voice_name,
        "type": args.voice_type
    }
    estimated_cost = calculate_cost(lyrics_to_replace, selected_voice, verbose=args.confirm_cost)

    if args.confirm_cost:
        print(f"Estimated cost for Polly synthesis: ${estimated_cost:.2f}")
        confirm = input("Do you want to proceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Operation cancelled.")
            return

    lyrics_to_replace = calculate_splice_times(audio_segment, lyrics_to_replace)
    lyrics_to_replace = generate_readings_with_polly(lyrics_to_replace, args.voice_name, args.voice_type)
    new_audio_segment, updated_lyrics = splice_audio_segments(audio_segment, lyrics_to_replace)

    output_mp3_file = f"new_{os.path.basename(args.mp3_file)}"
    save_audio_segment(new_audio_segment, output_mp3_file)

    output_lrc_file = f"new_{os.path.basename(args.lrc_file)}"
    update_lyrics_file(lyrics, updated_lyrics, output_lrc_file)

    print(f"Updated audio saved to: {output_mp3_file}")
    print(f"Updated lyrics saved to: {output_lrc_file}")


if __name__ == "__main__":
    available_languages = list(polly_voices.keys())

    parser = argparse.ArgumentParser(description="Heal incorrectly pronounced lines in an MP3 using Polly and LRC.")
    parser.add_argument("mp3_file", help="Original MP3 file to process.")
    parser.add_argument("lrc_file", help="Original LRC file with lyrics.")
    parser.add_argument("target", help="The line or word to replace.")
    parser.add_argument("replacement", help="The replacement string.")
    parser.add_argument("--word", action="store_true", help="Flag to indicate word replacement instead of the whole line.")
    parser.add_argument("--voice_language", type=str, choices=available_languages, default="en-GB", help="Voice language (e.g., en-GB, en-US)")
    parser.add_argument("--voice_name", type=str, default="Amy", help="Voice name (e.g., Amy, Joanna)")
    parser.add_argument("--voice_type", type=str, choices=["standard", "neural", "long-form", "generative"], default="neural", help="Voice type (e.g., standard, neural, long-form, generative)")
    parser.add_argument("--confirm_cost", action="store_true", help="Confirm the cost before proceeding")

    args = parser.parse_args()
    main(args)
