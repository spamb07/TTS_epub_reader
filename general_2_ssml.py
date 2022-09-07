#!/usr/bin/env python3
import argparse
import json
import copy
import pprint

## Based on https://www.tutorialspoint.com/html/html_tags_ref.htm
internal_tag_set = {
	"small":{"combine_flag": True},
	"b": {"ssml_tag":"emphasis", "level":"strong","combine_flag": True},
	"big":{"combine_flag": True},
	"em":{"ssml_tag":"emphasis", "level":"moderate","combine_flag": True},
	"i":{"ssml_tag":"emphasis", "level":"moderate","combine_flag": True}
}

reserved_characters = { # Using Amazon's documentation for now: https://docs.aws.amazon.com/polly/latest/dg/escapees.html
	"\"": "&quot;",
	"&": "&amp;",
	"'": "&apos;",
	"<": "&lt;",
	">": "&gt;",
	"\u2019": "&apos;",
}

splitting_substrings = { # Used for meeting character limit requirements
	". "	:".",
	"! "	:"!",
	"? "	:"?",
	".\" "	:".\"",
	"!\" "	:"!\"",
	"?\" "	:"?\"",
	", "	:",",
	" "		:"",
	"-"		:""
}

def replaceAll(string, mapping = reserved_characters):
	for before,after in mapping.items():
		string.replace(before,after)
	return string

def rawTagAisParentofB(tagA, tagB):
	if tagA is None or tagB is None:
		return False

	tagAChildParentList = tagA["parent_tag_list"]
	tagAChildParentList.append(tagA["tag"])

	tagBChildParentList = tagB["parent_tag_list"]

	# print("{} ==\n{}?".format(tagAChildParentList,tagBChildParentList))

	if len(tagBChildParentList) == 0:
		return False

	if len(tagAChildParentList) != len(tagBChildParentList):
		return False

	for parent_list_index in range(len(tagBChildParentList)):
		pTagA = tagAChildParentList[parent_list_index]
		pTagB = tagBChildParentList[parent_list_index]

		if pTagA != pTagB:
			return False

	return True

def main(args):
	tracklist = args.general_json["tracklist"]
	simplified_tracklist = []
	for track in tracklist:
		metadata = track["entry"]
		tag_list = track["spine_readable_tags"]
		
		ssml_tag_list = []
		combine_to_previous = False
		for tag_index in range(len(tag_list)):
			tag = tag_list[tag_index]
			if "content" in tag:
				content_text = replaceAll(tag["content"].encode("ascii",errors='ignore').decode("ascii",errors='ignore'))
				if tag["tag"].split(".")[0] in internal_tag_set and\
					"ssml_tag" in internal_tag_set[tag["tag"].split(".")[0]]:
					content_text = {
						"tag": internal_tag_set[tag["tag"].split(".")[0]]["ssml_tag"],
						"content": content_text
					}
					for attribute, value in internal_tag_set[tag["tag"].split(".")[0]].items():
						if attribute != "ssml_tag" and "flag" not in attribute:
							content_text[attribute] = value

				if tag["tag"].split(".")[0] not in internal_tag_set and not combine_to_previous:
					ssml_tag_list.append({
						"tag": "p",
						"content": [ content_text ]
					})
				else:
					previous_ssml_tag = ssml_tag_list[-1]
					previous_tag = None
					next_tag = None
					if tag_index > 0:
						previous_tag = tag_list[tag_index-1]
					if tag_index < len(tag_list)-1:
						next_tag = tag_list[tag_index+1]


					if previous_tag != None and \
						(tag["tag"].split(".")[0] in internal_tag_set and \
							"combine" in tag["tag"].split(".")[0] and tag["tag"].split(".")[0]["combine"]) and\
						rawTagAisParentofB(previous_tag,tag) or \
						combine_to_previous:

						previous_ssml_tag["content"].append(content_text)
						combine_to_previous = False
					else:
						ssml_tag_list.append({
							"tag": "p",
							"content": [ content_text ]
						})

					if next_tag != None and rawTagAisParentofB(next_tag,tag):
						combine_to_previous = True
		
		simplified_tracklist.append({
			"metadata": metadata,
			"ssml_list":ssml_tag_list
			})

	# pprint.PrettyPrinter().pprint(simplified_tracklist)

	for track in simplified_tracklist:
		new_entries = []
		for top_level_entry in track["ssml_list"]:
			accumulated_char_len = 0
			for content_item in top_level_entry["content"]:
				if isinstance(content_item, dict):
					accumulated_char_len += len(content_item["content"])
				else:
					accumulated_char_len += len(content_item)

			if accumulated_char_len >= args.query_char_limit:
				for content_item in top_level_entry["content"]:
					if isinstance(content_item, dict):
						local_accumulated_char_length = 0
						for local_content_item in content_item["content"]:
							local_accumulated_char_length += len(local_content_item)
						content_item_length = local_accumulated_char_length
					else:
						content_item_length = len(content_item)

					if content_item_length < args.query_char_limit:
						new_split_entry = {
							"content": [ content_item ]
						}
						for key, value in top_level_entry.items():
							if key != "content":
								new_split_entry[key] = value

						new_split_entry["char_length"] = content_item_length

						new_entries.append(new_split_entry)
					else:
						dictContents = None
						if isinstance(content_item,dict):
							dictContents = {}
							for key, value in content_item.items():
								if key != "content":
									dictContents[key] = value
							toSplit_content = [ content_item["content"] ]
						else:
							toSplit_content = [ content_item ]

						for splitting_substring, left_substring_result in splitting_substrings.items():
							new_toSplit_content = []
							is_split_enough = True
							for preSplitString in toSplit_content:
								if len(preSplitString) >= args.query_char_limit:
									split_string_list = preSplitString.split(splitting_substring)
									## Add dangling character back
									for split_string_index in range(len(split_string_list)-1):
										split_string_list[split_string_index] += left_substring_result
									## Check all Substrings
									for split_string_index in range(len(split_string_list)):
										if len(split_string_list[split_string_index]) >= args.query_char_limit:
											is_split_enough = False
										new_toSplit_content.append(split_string_list[split_string_index])
								else:
									new_toSplit_content.append(preSplitString)
							toSplit_content = new_toSplit_content
							if is_split_enough:
								break

						if not is_split_enough:
							raise NotImplementedError("Splitting the following paragraph didn't allow for meeting the character limit: {}\n{}".format(args.query_char_limit,content_item))

						if dictContents is not None:
							for split_content_string in toSplit_content:
								new_split_internal_entry = {
									"content": [ split_content_string ]
								}
								for key, value in content_item.items():
									if key != "content":
										new_split_internal_entry[key] = value

								new_split_internal_entry["char_length"] = len(split_content_string)

								new_split_entry = {
									"content": [ new_split_internal_entry ]
								}
								for key, value in top_level_entry.items():
									if key != "content":
										new_split_entry[key] = value

								new_split_entry["char_length"] = new_split_internal_entry["char_length"]

								new_entries.append(new_split_entry)

						else:
							for split_content_string in toSplit_content:
								new_split_entry = {
									"content": [ split_content_string ]
								}
								for key, value in top_level_entry.items():
									if key != "content":
										new_split_entry[key] = value

								new_split_entry["char_length"] = len(split_content_string)

								new_entries.append(new_split_entry)

			else:
				top_level_entry["char_length"] = accumulated_char_len
				new_entries.append(top_level_entry)

		track["ssml_list"] = new_entries

	# pprint.PrettyPrinter().pprint(simplified_tracklist)

	non_atribute_keys = {"content","tag","char_length","ssml_length","ssml"}
	mark_format_string = ""
	if not args.no_mark:
		mark_format_string = "<mark name=\"{tag}{tag_count}\"/>"
	query_format_string = "<speak><prosody rate=\"{prosody_rate}\">{{text}}</prosody></speak>".format(prosody_rate="medium")
	query_length = len("<speak><prosody rate=\"{prosody_rate}\">{{text}}</prosody></speak>")

	tag_count = 0
	for track in simplified_tracklist:
		metadata = track["metadata"]
		if args.recursive_track_labels and "parent_labels" in metadata:
			trackname = copy.deepcopy(metadata["parent_labels"])
			trackname.append(metadata["label"])
			trackname = ": ".join(trackname)
		else:
			trackname = metadata["label"]

		metadata["trackname"] = trackname

		for ssml_dict_item in track["ssml_list"]:
			current_ssml = ""
			for content_item in ssml_dict_item["content"]:
				if isinstance(content_item,dict):
					atributes_list = []
					for key,value in content_item.items():
						if key not in non_atribute_keys:
							atributes_list.append("{key}='{value}'".format(key=key,value=value))
					
					atributes = ""
					if len(atributes_list) > 0:
						atributes = " "+" ".join(atributes_list)

					current_ssml += "<{tag}{atributes}>{text}</{tag}>".format(tag=content_item["tag"],atributes=atributes,text=content_item["content"])
				else:
					current_ssml += content_item

			atributes_list = []
			for key,value in ssml_dict_item.items():
				if key not in non_atribute_keys:
					atributes_list.append("{key}='{value}'".format(key=key,value=value))
			
			atributes = ""
			if len(atributes_list) > 0:
				atributes = " "+" ".join(atributes_list)

			total_ssml = "<{tag}{atributes}>{text}</{tag}>{mark}".format(tag=ssml_dict_item["tag"],atributes=atributes,text=current_ssml,mark=mark_format_string.format(tag=ssml_dict_item["tag"],tag_count=tag_count))

			tag_count += 1

			ssml_dict_item["ssml"] = total_ssml
			ssml_dict_item["ssml_length"] = len(total_ssml)
			
			if (ssml_dict_item["ssml_length"] + query_length) > args.query_full_limit:
				suggestion_string = "Decrease the \"query_char_limit\" (currently set to {query_char_limit}).\n  OR Increase the \"query_full_limit\" based on your TTS provider (currently set to {query_full_limit})\n  OR, as a last resort, correct the epub to have smaller chapters.".format(\
					query_char_limit=args.query_char_limit,
					query_full_limit=args.query_full_limit
				)
				if not args.no_mark:
					suggestion_string = "Turning on 'no_mark' to reduce the size of a single query." + "\n  OR "  + suggestion_string
				error_string="The following query is too large based on the max query limit:\n\"\"\"\n{problem_ssml}\n\"\"\"\n   With a total length of (including opening tags not shown): {query_length}\nSuggestions:\n{suggestion_string}".format(\
					problem_ssml=ssml_dict_item["ssml"],
					query_length=ssml_dict_item["ssml_length"] + query_length,
					suggestion_string=suggestion_string)
				raise NotImplementedError(error_string)

	# pprint.PrettyPrinter().pprint(simplified_tracklist)

	final_query_list = []
	display_query_list = []
	
	for track in simplified_tracklist:
		trackname = track["metadata"]["trackname"]

		ssml_query_list = []
		current_ssml_length = query_length
		current_ssml = ""
		for ssml_dict_item in track["ssml_list"]:
			current_ssml_portion = ssml_dict_item["ssml"]
			current_ssml_portion_length = len(current_ssml_portion)

			if current_ssml_length + current_ssml_portion_length < args.query_full_limit:
				current_ssml += current_ssml_portion
				current_ssml_length = query_length + len(current_ssml)
			else:
				ssml_query_list.append(query_format_string.format(text=current_ssml))
				current_ssml = current_ssml_portion
				current_ssml_length = query_length + len(current_ssml)

		ssml_query_list.append(query_format_string.format(text=current_ssml))
		
		final_query_list.append({
			"name": trackname,
			"ssml_queries": ssml_query_list,
			"num_queries": len(ssml_query_list)
		})

		display_query_list.append({
			"name": trackname,
			"num_queries": len(ssml_query_list)
		})

	final_dictionary = {
		"tracklist": final_query_list,
	}

	with open(args.output, "w") as outfile:
		json.dump(final_dictionary, outfile, indent=4, sort_keys=True)
	print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
	print("Generated Queries\n  The following or the identified 'trackames' and the number of queries needed:")
	pprint.PrettyPrinter().pprint(display_query_list)

def json_type(string):
	with open(string) as json_file:
		data = json.load(json_file)
	return data

def valid_output_file(string):
	## TODO, actually check if this is a valid location...
	return string

if __name__ == "__main__":
	default_output = "generalized_epub.ssml_queries.json"
	default_query_char_limit = int(2000 * .95) # + Factor of safety
	default_query_full_limit = int(3000 * .95) # + Factor of safety
	parser = argparse.ArgumentParser()
	parser.add_argument("general_json", type=json_type, help="The location for the generalized json description of an epub.")
	parser.add_argument("-o", "--output", type=valid_output_file, default=default_output, help="The output location for the ssml (as json) of the epub. Default is '{}'".format(default_output))
	parser.add_argument("-c","--query_char_limit", type=int, default=default_query_char_limit, help="Any Query limit on the number of read charachers. Default {}".format(default_query_char_limit))
	parser.add_argument("-f","--query_full_limit", type=int, default=default_query_full_limit, help="Any Query limit on the number of charachers in the full query. Default {}".format(default_query_full_limit))
	parser.add_argument("-r","--recursive_track_labels", action='store_true', help="For TOC with recursive entries, use the parent lables as well, delimited by ': ' between. This is off by default.")
	parser.add_argument("-m","--no_mark", action='store_true', help="Removes the marks at the end of paragraphs used for generating lyric and other timing based metadata files.")
	args = parser.parse_args()

	main(args)