#!/usr/bin/env python3
import argparse
import json
import pprint
from pathlib import Path
import os.path
from datetime import datetime

def recursive_retrieve_exact_metadata_query(query_list, complex_datum):
	if len(query_list) == 0:
		return complex_datum, []

	elif isinstance(complex_datum,list): # Lists assumed to be "any" match within list
		list_index = query_list[0]
		if 0 <= list_index < len(complex_datum):
			list_item = complex_datum[list_index]
			if len(query_list) == 1:
				child_query_result, child_query_list = recursive_retrieve_exact_metadata_query([], list_item)
			else:
				child_query_result, child_query_list = recursive_retrieve_exact_metadata_query(query_list[1:], list_item)

			if child_query_list != None:
				return_query_list = [list_index]
				return_query_list.extend(child_query_list)
				return child_query_result, return_query_list

	elif isinstance(complex_datum,dict):
		if query_list[0] in complex_datum:
			dict_item = complex_datum[query_list[0]]
			if len(query_list) == 1:
				child_query_result, child_query_list = recursive_retrieve_exact_metadata_query([], dict_item)
			else:
				child_query_result, child_query_list = recursive_retrieve_exact_metadata_query(query_list[1:], dict_item)

			if child_query_list != None:
				return_query_list = [query_list[0]]
				return_query_list.extend(child_query_list)
				return child_query_result, return_query_list

	return None, None

def recursive_retrieve_general_metadata_query(query_list, complex_datum, to_match = None):
	if len(query_list) == 0:
		return complex_datum, []

	elif isinstance(complex_datum,list): # Lists assumed to be "any" match within list
		for list_index in range(len(complex_datum)):
			list_item = complex_datum[list_index]
			child_query_result, child_query_list = recursive_retrieve_general_metadata_query(query_list, list_item, to_match = to_match)

			if child_query_result != None and\
				(to_match is None or child_query_result == to_match):
				return_query_list = [list_index]
				return_query_list.extend(child_query_list)
				return child_query_result, return_query_list

	elif isinstance(complex_datum,dict):
		if query_list[0] in complex_datum:
			dict_item = complex_datum[query_list[0]]
			if len(query_list) == 1:
				child_query_result, child_query_list = recursive_retrieve_general_metadata_query([], dict_item, to_match = to_match)
			else:
				child_query_result, child_query_list = recursive_retrieve_general_metadata_query(query_list[1:], dict_item, to_match = to_match)

			if child_query_result != None:
				return_query_list = [query_list[0]]
				return_query_list.extend(child_query_list)
				return child_query_result, return_query_list

	return None, None

def main(args):
	general_json_metadata = args.general_json["metadata"]
	metadata_mapper = args.metadata_mapper

	name_space_intermappings = {}

	for book_namespace, book_namespace_url in general_json_metadata["name_spaces"].items():
		for mm_namespace, mm_namespace_url in metadata_mapper["name_spaces"].items():
			if book_namespace_url == mm_namespace_url:
				name_space_intermappings[mm_namespace] = book_namespace
				break

	id3_tag_output = {}

	for id3_tag_list_string, gen_metadata_query_list in metadata_mapper["id3_mappings"].items():
		id3_tag_list = id3_tag_list_string.split(",")
		for gen_metadata_query in gen_metadata_query_list:
			currently_valid = True

			exact_validation_path = None

			if "validate" in gen_metadata_query:
				for validation_path, validation_value in gen_metadata_query["validate"].items():
					validation_path = validation_path.split(".")
					validation_query_result, exact_validation_path = recursive_retrieve_general_metadata_query(validation_path, general_json_metadata, to_match=validation_value)

					if validation_query_result is None or validation_value != validation_query_result:
						currently_valid = False
						break

			if currently_valid and "data" in gen_metadata_query:
				data_path = list(gen_metadata_query["data"].keys())[0]
				data_processing = gen_metadata_query["data"][data_path]
				data_path = data_path.split(".")

				if exact_validation_path is not None:
					# print(exact_validation_path)
					for path_index in range(len(data_path)):
						path_item = data_path[path_index]
						if path_item == "pop":
							exact_validation_path.pop()
						else:
							break

					exact_validation_path.extend(data_path[path_index:])
					data_path = exact_validation_path

					data_query_result ,_ = recursive_retrieve_exact_metadata_query(data_path, general_json_metadata)

				else:
					data_query_result ,_ = recursive_retrieve_general_metadata_query(data_path, general_json_metadata)


				for id3_tag in id3_tag_list:
					if data_processing == "raw":
						id3_tag_output[id3_tag] = data_query_result
					elif data_processing == "read_datetime":
						date_time_obj = datetime.strptime(data_query_result.split("+")[0], '%Y-%m-%dT%H:%M:%S')
						id3_tag_output[id3_tag] = date_time_obj.strftime('%Y-%m-%dT%H:%M:%S')


	print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
	print("Identified Metadata\n  The following or the identified pieces of id3 metadata and the values found:")
	pprint.PrettyPrinter().pprint(id3_tag_output)
	
	with open(args.output, "w") as outfile:
		json.dump(id3_tag_output, outfile, indent=4, sort_keys=True)

def json_type(string):
	with open(string) as json_file:
		data = json.load(json_file)
	return data

def valid_output_file(string):
	## TODO, actually check if this is a valid location...
	return string

if __name__ == "__main__":
	default_output = "generalized_epub.id3_metadata.json"
	default_metadata_mapper_location = os.path.join(os.path.dirname(Path( __file__ ).absolute()),"metadata_maping.json")
	default_metadata_mapper_json = json_type(default_metadata_mapper_location)
	parser = argparse.ArgumentParser()
	parser.add_argument("general_json", type=json_type, help="The location for the generalized json description of an epub.")
	parser.add_argument("-m","--metadata_mapper", default=default_metadata_mapper_json , type=json_type, help="The input metadata mapper, Default is located at {}".format(default_metadata_mapper_location))
	parser.add_argument("-o", "--output", type=valid_output_file, default=default_output, help="The output location for the ssml (as json) of the epub. Default is '{}'".format(default_output))
	
	args = parser.parse_args()

	main(args)