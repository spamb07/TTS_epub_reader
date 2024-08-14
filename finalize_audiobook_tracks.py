#!/usr/bin/env python3
import argparse
import json

def load_json(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def save_json(data, file_path):
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4, sort_keys=True, ensure_ascii=False)

def is_unreadable_track(track):
    # Check if ssml_queries is empty or contains one item that is just xml tags
    if not track["ssml_queries"]:
        return True
    if len(track["ssml_queries"]) == 1 and not track["ssml_queries"][0].strip():
        return True
    return False

def contains_unreadable_words(name):
    # Check if track name contains any of the commonly unread words
    unread_words = ["contents", "copyright", "insert", "title", "cover", "newsletter", "illustrations", "j-novel"]
    for word in unread_words:
        if word in name.lower():
            return True
    return False

def finalize_tracks(metadata, ssml_queries):
    track_count = 1  # Start track count at 1
    finalized_tracks = []

    for track in ssml_queries["tracklist"]:
        track_name = track["name"]
        # Check if track is unreadable by the two methods
        if is_unreadable_track(track):
            continue
        if contains_unreadable_words(track_name) and len(track["ssml_queries"]) < 3:
            continue

        # Add metadata for each track
        track_metadata = metadata.copy()
        track_metadata["track"] = track_count  # Track number starts from 1 now
        track_metadata["title"] = track_name
        track_metadata["genre"] = "audiobook"

        track["metadata"] = track_metadata
        finalized_tracks.append(track)
        track_count += 1

    return {"tracklist": finalized_tracks}

def main(args):
    metadata = load_json(args.metadata_file)
    ssml_queries = load_json(args.ssml_queries_file)

    finalized_data = finalize_tracks(metadata, ssml_queries)
    
    save_json(finalized_data, args.output_file)
    print(f"Finalized audiobook tracks saved to {args.output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finalize audiobook tracks and metadata")
    parser.add_argument("metadata_file", type=str, help="Path to the metadata.json file")
    parser.add_argument("ssml_queries_file", type=str, help="Path to the ssml_queries.json file")
    parser.add_argument("-o", "--output_file", type=str, default="finalized_ssml_queries.json", help="Output file for finalized ssml_queries.json")

    args = parser.parse_args()
    main(args)
