#!/usr/bin/env bash

# Inputs
INPUT_EPUB=`realpath "${1}"`
base_input=`basename "${INPUT_EPUB}" '.epub'`

OUTPUT_DIRECTORY=${2:-"${base_input}"}

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
METADATA_MAPPING_FILE=${3:-"${SCRIPTPATH}/metadata_maping.json"}

mkdir -p "${OUTPUT_DIRECTORY}"

# Python Apps
run_epub_interpreter="${SCRIPTPATH}/epub_interpreter.py"
run_general_2_ssml="${SCRIPTPATH}/general_2_ssml.py"
run_generate_id3_metatags="${SCRIPTPATH}/generate_id3_metatags.py"
run_read_ssml="${SCRIPTPATH}/readSSML.py"
run_finalize_audiobook_tracks="${SCRIPTPATH}/finalize_audiobook_tracks.py"

# Middle Files
general_epub_file="${OUTPUT_DIRECTORY}/generalized_epub.json"
ssml_queries_file="${OUTPUT_DIRECTORY}/ssml_queries.json"
interpreted_metdata_file="${OUTPUT_DIRECTORY}/metadata.json"
finalized_ssml_queries_file="${OUTPUT_DIRECTORY}/finalized_ssml_queries.json"

# Generate the "general" description of the epub
"${run_epub_interpreter}" --output "${general_epub_file}" "${INPUT_EPUB}"

# Generate SSML Queries List from "general" epub description
"${run_general_2_ssml}" --output "${ssml_queries_file}" "${general_epub_file}"

# Generate Metadata from "general" epub description
"${run_generate_id3_metatags}" --metadata_mapper "${METADATA_MAPPING_FILE}" --output "${interpreted_metdata_file}" "${general_epub_file}"

# Finalize audiobook tracks and metadata

"${run_finalize_audiobook_tracks}" -o "${finalized_ssml_queries_file}" "${interpreted_metdata_file}" "${ssml_queries_file}" 

# Run the SSML to Audio conversion
"${run_read_ssml}" --confirm_cost --voice_type "standard" "${finalized_ssml_queries_file}" "${OUTPUT_DIRECTORY}" 