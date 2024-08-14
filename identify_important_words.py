#!/usr/bin/env python3

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

def load_unigram_frequencies(csv_file):
    """
    Load the unigram frequencies from the provided CSV file.
    
    Args:
        csv_file (str): Path to the CSV file containing word frequencies.
        
    Returns:
        dict: A dictionary mapping words to their frequencies.
    """
    frequencies = {}
    with open(csv_file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            word = row['word'].strip().lower()
            count = int(row['count'])
            frequencies[word] = count
    return frequencies

def process_ssml_queries(ssml_file, unigram_frequencies):
    """
    Process the SSML queries to identify important words.
    
    Args:
        ssml_file (str): Path to the SSML JSON file.
        unigram_frequencies (dict): Dictionary of word frequencies.
        
    Returns:
        Counter: A Counter object with words ranked by their importance.
    """
    with open(ssml_file, 'r', encoding='utf-8') as f:
        ssml_data = json.load(f)

    word_counter = Counter()

    # Iterate over the SSML queries
    for track in ssml_data['tracklist']:
        for query in track['ssml_queries']:
            # Remove SSML tags and split the text into words
            words = query.replace('<', ' <').replace('>', '> ').split()
            cleaned_words = [word.lower().strip('<>/') for word in words if word.isalpha()]
            word_counter.update(cleaned_words)

    # Compare the SSML word frequency with the general English frequency
    word_importance = Counter()
    for word, count in word_counter.items():
        general_freq = unigram_frequencies.get(word, 1)  # Default to 1 if the word is not found
        importance_score = count / general_freq
        word_importance[word] = importance_score

    return word_importance.most_common()

def main():
    parser = argparse.ArgumentParser(description="Identify important words in SSML queries based on relative frequency.")
    parser.add_argument('ssml_file', type=str, help="Path to the SSML JSON file.")
    parser.add_argument('--unigram_freq', type=str, default='./unigram_freq.csv', 
                        help="Path to the unigram frequency CSV file. Default is './unigram_freq.csv'.")
    parser.add_argument('--output', type=str, help="Optional output file to save the ranked words as JSON.")

    args = parser.parse_args()

    # Load unigram frequencies
    unigram_frequencies = load_unigram_frequencies(args.unigram_freq)

    # Process SSML queries
    important_words = process_ssml_queries(args.ssml_file, unigram_frequencies)

    # Print or save the results
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as outfile:
            json.dump(important_words, outfile, indent=4)
        print(f"Important words saved to {args.output}")
    else:
        for word, score in important_words:
            print(f"{word}: {score:.6f}")

if __name__ == "__main__":
    main()
