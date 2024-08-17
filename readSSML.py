#!/usr/bin/env python3
import argparse
import json
import sys
import os
from contextlib import closing
from boto3 import Session
from botocore.exceptions import BotoCoreError, ClientError
import eyed3
from pydub import AudioSegment
from io import BytesIO

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
    for track in ssml_queries:
        for query in track["ssml_queries"]:
            char_count = len(query)
            total_characters += char_count
            if verbose:
                print(f"Track: {track['metadata']['title']} - Query length: {char_count} characters")

    if verbose:
        print(f"Total characters across all SSML queries: {total_characters}")

    total_cost = (total_characters / 1_000_000) * cost_per_million

    return total_cost

def add_id3_tags(output_filename, track_metadata):
    """
    Add ID3 tags to an MP3 file using the metadata provided.

    Args:
        output_filename (str): Path to the MP3 file.
        track_metadata (dict): Metadata information to apply as ID3 tags.
    """
    audiofile = eyed3.load(output_filename)

    if audiofile is None:
        print(f"Error: Failed to load MP3 file {output_filename}")
        return

    if not audiofile.tag:
        audiofile.initTag()

    # Map the metadata keys to the corresponding ID3 tag fields
    if "ARTIST" in track_metadata:
        audiofile.tag.artist = track_metadata["ARTIST"]

    if "ALBUM" in track_metadata:
        audiofile.tag.album = track_metadata["ALBUM"]

    if "ALBUMARTIST" in track_metadata:
        audiofile.tag.album_artist = track_metadata["ALBUMARTIST"]

    if "TITLE" in track_metadata:
        audiofile.tag.title = track_metadata["TITLE"]

    if "TRACK" in track_metadata:
        audiofile.tag.track_num = track_metadata["TRACK"]

    if "DATE" in track_metadata:
        date_value = track_metadata["DATE"]
        
        if date_value:
            # Set release date, original release date, recording date, and year
            audiofile.tag.release_date = date_value
            
            # Attempt to parse the year from the date
            year_value = None
            if len(date_value) >= 4:
                year_value = date_value[:4]
                
            if year_value:
                audiofile.tag.recording_date = year_value
                audiofile.tag.original_release_date = year_value
                audiofile.tag.tagging_date = year_value  # Often used for the year
                
                # Set the year (older ID3v2.3)
                audiofile.tag.year = year_value
        else:
            print(f"Warning: 'DATE' metadata is missing or invalid for {output_filename}. Skipping date tags.")

    if "PUBLISHER" in track_metadata:
        audiofile.tag.publisher = track_metadata["PUBLISHER"]

    # The genre can be set to Audiobook (ID3 genre 183) if not specified
    genre = str(audiofile.tag.genre).lower() if audiofile.tag.genre else "audiobook"
    if genre == "audiobook":
        audiofile.tag.genre = 183  # Set to Audiobook genre code

    # Save the changes to the file
    try:
        audiofile.tag.save()
        print(f"Successfully saved ID3 tags to {output_filename}")
    except Exception as e:
        print(f"Error saving ID3 tags to {output_filename}: {e}")




def calculate_audio_duration(audio_content):
    """
    Calculate the duration of an MP3 audio stream.

    Args:
        audio_content (bytes): The raw audio data.

    Returns:
        float: Duration of the audio in milliseconds.
    """
    audio = AudioSegment.from_mp3(BytesIO(audio_content))
    return len(audio)  # duration in milliseconds

def generate_lyrics(ssmlJSON, track_metadata):
    """
    Generate lyrics with accurate timestamps based on SSML speech marks and audio durations.

    Args:
        ssmlJSON (list): The SSML speech marks JSON response from Polly.
        track_metadata (dict): Metadata information for the track.

    Returns:
        tuple: Formatted lyrics in LRC format and plain text format.
    """
    lrc_lyrics = ""
    txt_lyrics = ""
    current_paragraph = []

    # Add metadata to the LRC lyrics
    lrc_lyrics += "[ar:{artist}]\n".format(artist=track_metadata.get("artist", "Unknown Artist"))
    lrc_lyrics += "[al:{album}]\n".format(album=track_metadata.get("album", "Unknown Album"))
    lrc_lyrics += "[ti:{title}]\n".format(title=track_metadata.get("title", "Unknown Title"))
    lrc_lyrics += "\n"  # Add a newline for readability

    currentTimeZero = 0

    for ssmlMark in ssmlJSON:
        if ssmlMark["type"] == "sentence":
            time = ssmlMark["time"] + currentTimeZero
            minutes = time // (60 * 1000)
            time -= minutes * (60 * 1000)
            seconds = time // 1000
            time -= seconds * 1000
            hundredths = time // 10

            value = ssmlMark["value"]
            lrc_lyrics += "[{mm:02d}:{ss:02d}.{xx:02d}]{value}\n".format(mm=minutes, ss=seconds, xx=hundredths, value=value)

            # Add the sentence to the current paragraph
            current_paragraph.append(value)

        elif ssmlMark["type"] == "ssml":
            # End the current paragraph
            if current_paragraph:
                txt_lyrics += " ".join(current_paragraph) + "\n"
                current_paragraph = []

        elif ssmlMark["type"] == "preceding_realtime":
            currentTimeZero += ssmlMark["time"]

    # If there's any remaining paragraph content, add it to txt_lyrics
    if current_paragraph:
        txt_lyrics += " ".join(current_paragraph) + "\n"

    return lrc_lyrics, txt_lyrics


def readEntryWithPolly(entry, outfilename, voiceID, engine, track_metadata):
    """
    Converts SSML to speech using Amazon Polly and writes the result to an MP3 file.

    Args:
        entry (dict): The entry containing SSML queries to be converted.
        outfilename (str): The output MP3 file path.
        voiceID (str): The ID of the Polly voice to use.
        engine (str): The Polly engine to use (standard, neural, long-form, generative).
        track_metadata (dict): Metadata information to apply as ID3 tags.

    Returns:
        dict: Dictionary containing the SSML speech marks JSON response from Polly, with additional timing information and lyrics.
    """
    session = Session()
    polly = session.client("polly")

    print(f"Generating MP3: {outfilename} with voiceID: {voiceID} using engine: {engine}")
    
    # Use 'ssml_queries' instead of 'ssml' as per the structure of 'entry'
    pieces = entry["ssml_queries"]
    chapterJSON = ""
    ssmlJSON = []
    section_durations = []

    with open(outfilename, "wb") as out:
        for i, piece in enumerate(pieces, start=1):
            print(f"Processing piece {i} of {len(pieces)}")

            try:
                responseAudio = polly.synthesize_speech(
                    Text=piece, TextType="ssml", OutputFormat="mp3", 
                    VoiceId=voiceID, Engine=engine
                )
                responseJSON = polly.synthesize_speech(
                    Text=piece, TextType="ssml", OutputFormat="json", 
                    SpeechMarkTypes=["ssml", "sentence"], VoiceId=voiceID, Engine=engine
                )
            except (BotoCoreError, ClientError) as error:
                print(f"Error: {error}")
                sys.exit(-1)

            # Extract duration of the audio
            if "AudioStream" in responseAudio:
                with closing(responseAudio["AudioStream"]) as stream:
                    audio_content = stream.read()
                    out.write(audio_content)

                    # Calculate duration (length in milliseconds) of the current audio piece
                    duration = calculate_audio_duration(audio_content)
                    section_durations.append(duration)
            else:
                print("Could not stream audio")
                sys.exit(-1)

            if "AudioStream" in responseJSON:
                with closing(responseJSON["AudioStream"]) as stream:
                    try:
                        json_content = stream.read().decode("utf-8")
                        chapterJSON = json_content  # Store a single line to avoid repetition
                    except IOError as error:
                        print(f"Error: {error}")
                        sys.exit(-1)

                # Convert the current JSON content to a list of dicts
                current_ssmlJSON = json.loads("[" + ','.join(chapterJSON[:-1].split('\n')) + "]")
                
                # Append the SSML JSON entries
                ssmlJSON.extend(current_ssmlJSON)
                
                # Append the corresponding preceding_realtime entry
                preceding_realtime_entry = {"time": duration, "type": "preceding_realtime"}
                ssmlJSON.append(preceding_realtime_entry)

    # Add ID3 tags to the MP3 file
    add_id3_tags(outfilename, track_metadata)

    # Generate lyrics
    lrc_lyrics, txt_lyrics = generate_lyrics(ssmlJSON, track_metadata)

    entry["returnSSML"] = ssmlJSON
    entry["lyrics"] = lrc_lyrics

    return {"ssmlJSON": ssmlJSON, "lrc_lyrics": lrc_lyrics, "txt_lyrics": txt_lyrics}

def process_ssml_queries(ssml_queries, selected_voice, output_dir):
    engine = selected_voice["type"]
    voiceID = selected_voice["name"]

    for i, track in enumerate(ssml_queries):
        track_number = track["metadata"]["track"]
        track_title = track["metadata"]["title"]
        base_filename = f"{track_number} - {track_title}"

        output_filename = os.path.join(output_dir, f"{base_filename}.mp3")
        ssml_json_filename = os.path.join(output_dir, f"{base_filename}.json")
        lrc_filename = os.path.join(output_dir, f"{base_filename}.lrc")
        txt_filename = os.path.join(output_dir, f"{base_filename}.txt")

        track_metadata = track["metadata"]
        result = readEntryWithPolly(track, output_filename, voiceID, engine, track_metadata)
        ssml_json = result["ssmlJSON"]
        lrc_lyrics = result["lrc_lyrics"]
        txt_lyrics = result["txt_lyrics"]

        # Save SSML JSON
        with open(ssml_json_filename, "w") as json_file:
            json.dump(ssml_json, json_file, indent=4, ensure_ascii=False)

        # Save Lyrics as LRC
        with open(lrc_filename, "w") as lrc_file:
            lrc_file.write(lrc_lyrics)

        # Save Lyrics as TXT
        with open(txt_filename, "w") as txt_file:
            txt_file.write(txt_lyrics)

        # Add ID3 tags to the MP3 file
        add_id3_tags(output_filename, track_metadata)

        print(f"Generated MP3, JSON, LRC, and TXT files for track {track_number} - {track_title}.")

def create_preview_ssml_query(ssml_queries):
    """
    Find the longest SSML query to use for preview.
    
    Args:
        ssml_queries (list): List of SSML entries from the JSON file.

    Returns:
        dict: The SSML query entry that is the longest.
    """
    # Extract the longest SSML query entry
    longest_query_entry = max(
        (query for track in ssml_queries["tracklist"] for query in track["ssml_queries"]),
        key=lambda query: len(query)
    )

    # Replicate the original structure for the preview entry
    for track in ssml_queries["tracklist"]:
        if longest_query_entry in track["ssml_queries"]:
            preview_entry = {
                "metadata": track["metadata"],
                "ssml_queries": [longest_query_entry]
            }
            return preview_entry

    return None

def generate_preview(preview_entry, selected_voice, output_dir):
    """
    Generate an MP3 preview for the longest SSML query.

    Args:
        preview_entry (dict): The SSML query entry to preview.
        selected_voice (dict): Selected voice options including language, name, and type.
        output_dir (str): The directory to output the preview MP3 file.
    """
    preview_filename = f"{output_dir}/preview_{selected_voice['language']}_{selected_voice['name']}_{selected_voice['type']}.mp3"
    readEntryWithPolly(preview_entry, preview_filename, selected_voice['name'], selected_voice['type'], preview_entry["metadata"])
    print(f"Preview generated: {preview_filename}")

def main():
    available_languages = list(polly_voices.keys())

    parser = argparse.ArgumentParser(description="SSML to Speech Converter using AWS Polly")
    parser.add_argument('ssml_file', type=str, help="Path to the SSML JSON file")
    parser.add_argument('output_dir', type=str, help="Output directory for MP3 and JSON files")
    parser.add_argument('--voice_language', type=str, choices=available_languages, default="en-GB", help="Voice language (e.g., en-GB, en-US)")
    parser.add_argument('--voice_name', type=str, default="Amy", help="Voice name (e.g., Amy, Joanna)")
    parser.add_argument('--voice_type', type=str, choices=["standard", "neural", "long-form", "generative"], default="neural", help="Voice type (e.g., standard, neural, long-form, generative)")
    parser.add_argument('--confirm_cost', action='store_true', help="Confirm the cost before proceeding")
    parser.add_argument('--preview_voice', action='store_true', help="Generate a preview of the longest SSML query")

    args = parser.parse_args()

    selected_voice = {
        "language": args.voice_language,
        "name": args.voice_name,
        "type": args.voice_type
    }

    with open(args.ssml_file, 'r') as f:
        ssml_queries = json.load(f)["tracklist"]

    # Calculate cost
    total_cost = calculate_cost(ssml_queries, selected_voice)

    if args.preview_voice:
        preview_entry = create_preview_ssml_query(ssml_queries)
        preview_cost = calculate_cost([preview_entry["ssml_queries"][0]], selected_voice, verbose=args.confirm_cost)
        
        if args.confirm_cost:
            print(f"Estimated cost for the preview: ${preview_cost:.2f}")
            confirm = input("Do you want to proceed with the preview? (yes/no): ").strip().lower()
            if confirm != 'yes':
                print("Preview operation cancelled.")
                sys.exit(0)

        generate_preview(preview_entry, selected_voice, args.output_dir)
        sys.exit(0)

    if args.confirm_cost:
        print(f"Estimated total cost: ${total_cost:.2f}")
        confirm = input("Do you want to proceed? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Operation cancelled.")
            sys.exit(0)

    # Process SSML queries and generate MP3 and JSON files
    process_ssml_queries(ssml_queries, selected_voice, args.output_dir)

if __name__ == "__main__":
    main()
