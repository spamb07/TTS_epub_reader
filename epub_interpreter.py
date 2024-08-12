#!/usr/bin/env python3

import argparse
import os
import zipfile
import xml.sax
import pprint
import copy
import re
import json

# The existing classes and functions remain unchanged

# SAX handler for parsing the container.xml file in an EPUB archive
class ContainerHandler(xml.sax.ContentHandler):
	def __init__(self):
		self.rootfiles = []

	def startElement(self, tag, attributes):
		# Collects rootfiles from the container.xml file
		if tag == "rootfile":
			current_rootfile = {}
			for attribute_name, attribute_value in attributes.items():
				current_rootfile[attribute_name] = attribute_value
			self.rootfiles.append(current_rootfile)

# SAX handler for parsing the package.opf file in an EPUB archive
class OpenPackageFormatHandler(xml.sax.ContentHandler):
	def __init__(self):
		# Initialize state variables to track different sections of the OPF file
		self.state = ""
		self.metadata = {}
		self.manifest = {}
		self.spine = []
		self.guide = {}
		self.current_tag_tag = None
		self.current_tag_dict = None
		self.state_set_as_dict = {
			"metadata": self.metadata,
			"manifest": self.manifest,
			"spine": self.spine,
			"guide": self.guide,
			"spine_toc_id": ""
		}

	def updateHREF(self, parentDirPath):
		# Update href paths to include the directory path
		for key_id, manifest_value in self.manifest.items():
			for key, value in manifest_value.items():
				if key == "href":
					self.manifest[key_id]["href"] = os.path.join(parentDirPath, self.manifest[key_id]["href"])

	# Helper function to append values to a dictionary key, allowing for multiple values
	def __dict_append_to_key(dictionary, key, value):
		if key not in dictionary:
			dictionary[key] = value
		else:
			if isinstance(dictionary[key], list):
				dictionary[key].append(value)
			else:
				old_value = dictionary[key]
				dictionary[key] = [old_value, value]

	def startElement(self, tag, attributes):
		# Determine the current state (e.g., metadata, manifest, spine, guide) based on the tag
		if tag in self.state_set_as_dict.keys():
			self.state = tag

		# Process the metadata section
		if self.state == "metadata":
			if tag == "metadata":
				# Capture namespaces within metadata
				if "name_spaces" not in self.metadata:
					self.metadata["name_spaces"] = {}
				for key, value in attributes.items():
					if "xmlns:" in key:
						self.metadata["name_spaces"][key.replace("xmlns:", "")] = value

			if tag != "metadata" and self.current_tag_tag is None:
				# Start capturing metadata tags and attributes
				self.current_tag_tag = tag
				self.current_tag_dict = {}
				for key, value in attributes.items():
					self.current_tag_dict[key] = value

		# Process the manifest section
		if self.state == "manifest" and tag == "item":
			current_manifest_item = {}
			for key, value in attributes.items():
				if key != "id":
					current_manifest_item[key] = value
			if "id" in attributes.keys():
				self.manifest[attributes.getValue("id")] = current_manifest_item

		# Process the spine section
		if self.state == "spine":
			if tag == "spine":
				if "toc" in attributes.keys():
					self.state_set_as_dict["spine_toc_id"] = attributes.getValue("toc")
			if tag == "itemref":
				if "idref" in attributes.keys():
					self.spine.append(attributes.getValue("idref"))

		# Process the guide section
		if self.state == "guide":
			if tag == "reference":
				current_guide_item = {}
				for key, value in attributes.items():
					if key != "type":
						current_guide_item[key] = value
				if "type" in attributes.keys():
					OpenPackageFormatHandler.__dict_append_to_key(self.guide, attributes.getValue("type"), current_guide_item)

	def characters(self, content):
		# Capture the text content for metadata tags
		if self.state == "metadata" and self.current_tag_tag is not None:
			self.current_tag_dict["text"] = content

	def endElement(self, tag):
		# Finalize the metadata tag processing and append it to the metadata dictionary
		if self.state == "metadata" and self.current_tag_tag is not None:
			if tag == self.current_tag_tag:
				OpenPackageFormatHandler.__dict_append_to_key(self.metadata, self.current_tag_tag, self.current_tag_dict)
				self.current_tag_tag = None
				self.current_tag_dict = None

# SAX handler for parsing the Table of Contents (TOC) in an EPUB archive
class TableOfContentsHandler(xml.sax.ContentHandler):
	def __init__(self):
		self.navPointStack = []
		self.navPointList = []
		self.is_navMap_state = False
		self.awaiting_label_text_tag = False
		self.awaiting_label_text = False

	def updateSRC(self, parentDirPath):
		# Update the src paths in the TOC to include the directory path
		TableOfContentsHandler.__recursiveUpdateSRC(self.navPointList, parentDirPath)

	def __recursiveUpdateSRC(navPointList, parentDirPath):
		# Recursively update the src paths for nested navigation points
		for navPointDict in navPointList:
			if "src" in navPointDict:
				navPointDict["src"] = os.path.join(parentDirPath, navPointDict["src"])
			if "navPointList" in navPointDict and isinstance(navPointDict["navPointList"], list):
				TableOfContentsHandler.__recursiveUpdateSRC(navPointDict["navPointList"], parentDirPath)

	def startElement(self, tag, attributes):
		# Handle the start of elements related to TOC navigation
		if tag == "navMap":
			self.is_navMap_state = True

		if self.is_navMap_state and tag == "navPoint":
			# Capture navigation point attributes
			current_navPoint_item = {}
			for key, value in attributes.items():
				current_navPoint_item[key] = value
			self.navPointStack.append(current_navPoint_item)

		if self.is_navMap_state and tag == "navLabel":
			self.awaiting_label_text_tag = True

		if self.is_navMap_state and self.awaiting_label_text_tag and tag == "text":
			self.awaiting_label_text = True

		if self.is_navMap_state and tag == "content":
			if "src" in attributes.keys():
				self.navPointStack[-1]["src"] = attributes.getValue("src")

	def characters(self, content):
		# Capture the text content for navigation labels
		if self.awaiting_label_text:
			self.navPointStack[-1]["label"] = content

	def endElement(self, tag):
		# Handle the end of elements related to TOC navigation
		if self.is_navMap_state and tag == "navMap":
			self.is_navMap_state = False

		if self.is_navMap_state and tag == "navLabel":
			self.awaiting_label_text_tag = False

		if self.is_navMap_state and tag == "text":
			self.awaiting_label_text = False

		if self.is_navMap_state and tag == "navPoint":
			# Finalize the current navigation point and add it to the list
			current_navPoint = self.navPointStack.pop()
			if len(self.navPointStack) == 0:
				self.navPointList.append(current_navPoint)
			else:
				if "navPointList" not in self.navPointStack[-1]:
					self.navPointStack[-1]["navPointList"] = []
				self.navPointStack[-1]["navPointList"].append(current_navPoint)

# SAX handler for parsing the body of XHTML files in an EPUB archive
class BodyXHTMLHandler(xml.sax.ContentHandler):
	def __init__(self):
		self.isBody = False
		self.bodyContentStack = []
		self.bodyContentList = []
		self.element_number = 0

	def __get_current_stack_info(self):
		# Helper function to gather stack information and tag hierarchy
		tag_list = []
		stack_info = {}
		for stack_item in reversed(self.bodyContentStack):
			tag_list.append(stack_item["tag"])
			for key, value in stack_item.items():
				if key != "tag" and key != "had_content" and key != "id" and key not in stack_info:
					stack_info[key] = value
		tag_list = list(reversed(tag_list))
		tag_list.pop()  # Remove the current tag
		stack_info["parent_tag_list"] = tag_list
		return stack_info

	def clean_empty_content(self, current_list=None):
		# Recursively clean up any empty content in the body content list
		if current_list is None:
			current_list = self.bodyContentList

		to_delete_indices = []
		for content_index in range(len(current_list)):
			content_item = current_list[content_index]

			# Identify empty content based on lack of ID and whitespace-only content
			if "id" not in content_item and \
				"content" in content_item and \
				(("had_content" in content_item and not content_item["had_content"]) or ("had_content" not in content_item)):
				if content_item["content"] == '\n':
					to_delete_indices.append(content_index)
				else:
					empty_regex = r"^\s+$"
					empty_match = re.match(empty_regex, content_item["content"])
					if empty_match is not None:
						to_delete_indices.append(content_index)
			elif "content_list" in content_item and len(content_item["content_list"]) > 0:
				self.clean_empty_content(current_list=content_item["content_list"])

		for delete_index in reversed(to_delete_indices):
			current_list.pop(delete_index)

	def startElement(self, tag, attributes):
		# Handle the start of body elements and attributes
		if tag == "body":
			self.isBody = True
			current_body_item = {}
			current_body_item["tag"] = "{}.{}".format(tag, self.element_number)
			self.element_number += 1
			current_body_item["had_content"] = True
			for key, value in attributes.items():
				current_body_item[key] = value
			self.bodyContentList.append(current_body_item)
		if self.isBody and tag != "body":
			current_body_item = {}
			current_body_item["tag"] = "{}.{}".format(tag, self.element_number)
			self.element_number += 1
			current_body_item["had_content"] = False
			for key, value in attributes.items():
				current_body_item[key] = value
			self.bodyContentStack.append(current_body_item)

	def characters(self, content):
		# Capture the content within body elements
		if self.isBody:
			if len(self.bodyContentStack) == 0:
				self.bodyContentList.append({
					"tag": "{}.{}".format("body", self.element_number),
					"content": content
				})
				self.element_number += 1
			else:
				current_state = self.__get_current_stack_info()
				current_state["content"] = content
				if len(self.bodyContentStack) > 0 and "tag" in self.bodyContentStack[-1]:
					current_state["tag"] = self.bodyContentStack[-1]["tag"]
				for parent in reversed(self.bodyContentStack):
					if "id" in parent:
						if "id" in current_state and not isinstance(current_state["id"], list):
							current_state["id"] = [current_state["id"]]

						if "id" not in current_state:
							current_state["id"] = parent["id"]
						elif isinstance(current_state["id"], list):
							current_state["id"].append(parent["id"])

						parent.pop("id")
				current_state["content"] = content

				for parent in self.bodyContentStack:
					parent["had_content"] = True

				self.bodyContentList.append(current_state)

	def endElement(self, tag):
		# Handle the end of body elements and finalize the content list
		if tag == "body":
			self.isBody = False
		elif self.isBody:
			if not self.bodyContentStack[-1]["had_content"] or "id" in self.bodyContentStack[-1]:
				combined_info = self.__get_current_stack_info()
				combined_info["tag"] = self.bodyContentStack[-1]["tag"]
				if len(self.bodyContentStack) > 0 and "id" in self.bodyContentStack[-1]:
					combined_info["id"] = self.bodyContentStack[-1]["id"]

				self.bodyContentList.append(combined_info)
				for parent in self.bodyContentStack:
					parent["had_content"] = True
			self.bodyContentStack.pop()

# Function to recursively flatten the content list, handling nested content
def __recursive_content_flatten(content_list):
	total_content_list = []
	for content_item in content_list:
		if content_item is not None:
			if "content_list" in content_item and len(content_item["content_list"]) > 0:
				children_content_list = __recursive_content_flatten(content_item["content_list"])
				local_content_elem = copy.deepcopy(content_item)
				if "content_list" in local_content_elem:
					local_content_elem.pop("content_list", None)
				current_content_list = [local_content_elem]
				current_content_list.extend(children_content_list)
			else:
				local_content_elem = copy.deepcopy(content_item)
				if "content_list" in local_content_elem:
					local_content_elem.pop("content_list", None)
				current_content_list = [local_content_elem]
			total_content_list.extend(current_content_list)

	return total_content_list

# Validate that the EPUB file exists, is a file, and is a valid ZIP (EPUB) file
def epub_type(EPUB_Location):
	# Check file exists, is a file, and is a zip
	if not os.path.exists(EPUB_Location):
		raise argparse.ArgumentTypeError(f"EPUB Location '{EPUB_Location}' does not exist.")
	elif not os.path.isfile(EPUB_Location):
		raise argparse.ArgumentTypeError(f"EPUB Location '{EPUB_Location}' is not a file, but exists.")
	elif not zipfile.is_zipfile(EPUB_Location):
		raise argparse.ArgumentTypeError(f"EPUB Location '{EPUB_Location}' cannot be opened by zipfile (EPUBS should be a zip).")
	else:
		pass

	epub_zip_file = zipfile.ZipFile(EPUB_Location)

	# Check Mimetype
	pathObj = zipfile.Path(epub_zip_file, at="mimetype")
	if not pathObj.exists():
		raise argparse.ArgumentTypeError(f"'{EPUB_Location}' is missing a mimetype.")

	mimetype_file_contents = epub_zip_file.read("mimetype")

	if b'application' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'application'")
	if b'epub' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'epub'")
	if b'zip' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'zip'")

	pathObj = zipfile.Path(epub_zip_file, at="META-INF/container.xml")
	if not pathObj.exists():
		raise argparse.ArgumentTypeError(f"'{EPUB_Location}' is missing a 'META-INF/container.xml'")

	return zipfile.ZipFile(EPUB_Location)

# Recursively process the navigation points in the TOC to flatten them into a list
def recursiveNavPointList_2_split_list(navPointList, parent_label_list=None):
	split_list = []
	for navPoint in navPointList:
		if parent_label_list is not None:
			navPoint["parent_labels"] = parent_label_list

		if "src" in navPoint:
			src_list = navPoint["src"].split("#", 1)
			if len(src_list) == 1:
				navPoint["src_path"] = src_list[0]
			else:
				navPoint["src_path"] = src_list[0]
				navPoint["src_id"] = src_list[1]

		if "navPointList" in navPoint:
			if parent_label_list is None:
				current_parent_list = [navPoint["label"]]
			else:
				current_parent_list = copy.deepcopy(parent_label_list)
				current_parent_list.append(navPoint["label"])
			nested_split_list = recursiveNavPointList_2_split_list(navPoint.pop("navPointList"), parent_label_list=current_parent_list)

			split_list.append(navPoint)
			split_list.extend(nested_split_list)
		else:
			split_list.append(navPoint)

	return split_list

# Generate a structured book format by combining TOC and spine data
import pprint

def generate_book(toc_list, spine_list, debug=False):
    """
    Generates a list representing the book structure by associating TOC (Table of Contents)
    entries with corresponding spine content.

    Args:
        toc_list (list): List of TOC entries containing chapter labels, paths, and IDs.
        spine_list (list): List of spine entries containing paths, IDs, and readable tags.
        debug (bool): Flag to control debug-level printing. Default is False.

    Returns:
        list: A structured list representing the book, with TOC entries associated with corresponding spine content.
    """

    if debug:
        print("Starting the generation of the book structure...")
        print("TOC List:")
        pprint.pprint(toc_list)
        print("Spine List:")
        pprint.pprint(spine_list)

    current_path = None  # Tracks the current path being processed
    complete_book_list = []  # The final list to represent the structured book
    avaliable_toc_list = copy.deepcopy(toc_list)  # A copy of the TOC list to track unassociated entries

    # This is the default TOC entry if none are matched; it groups items before the first TOC entry
    current_toc_entry = {
        "label": "Pre Table of Contents"
    }
    current_spine_list = []  # Tracks spine items associated with the current TOC entry

    for readable_tag in spine_list:
        if "path" in readable_tag:
            current_path = readable_tag["path"]  # Update the current path if specified in the spine entry

        if debug:
            print(f"Processing Spine Item:")
            pprint.pprint(readable_tag)
            print(f"Current Path: {current_path}")

        found_toc = False  # Flag to determine if a matching TOC entry was found

        # Check if the current spine item matches any TOC entry
        for toc_entry in avaliable_toc_list:
            if "src_path" in toc_entry and current_path == toc_entry["src_path"]:
                if ("src_id" not in toc_entry) or \
                    ("id" in readable_tag and readable_tag["id"] == toc_entry["src_id"]) or \
                    ("id" in readable_tag and isinstance(readable_tag["id"], list) and toc_entry["src_id"] in readable_tag["id"]):

                    # If a match is found, associate the current spine list with the current TOC entry
                    complete_book_list.append({
                        "entry": current_toc_entry,
                        "spine_readable_tags": current_spine_list
                    })

                    # Update to the new TOC entry and reset the current spine list
                    current_toc_entry = toc_entry
                    current_spine_list = [readable_tag]

                    # Remove the matched TOC entry from the available list
                    avaliable_toc_list.remove(toc_entry)

                    if debug:
                        print("Matched TOC Entry:")
                        pprint.pprint(toc_entry)
                        print("Associated Spine List:")
                        pprint.pprint(current_spine_list)

                    found_toc = True
                    break

        if not found_toc:
            # If no matching TOC entry is found, continue adding spine items to the current list
            current_spine_list.append(readable_tag)
            if debug:
                print("No TOC match found. Continuing with current spine list:")
                pprint.pprint(current_spine_list)

    # After looping through all spine items, add the final accumulated items to the book list
    complete_book_list.append({
        "entry": current_toc_entry,
        "spine_readable_tags": current_spine_list
    })

    if debug:
        print("Completed the generation of the book structure.")
        print("Final Book List:")
        pprint.pprint(complete_book_list)

    return complete_book_list


# Extract and save images from the EPUB archive
def dump_images(opf_dict, epub_zip, output_dir):
	image_files = {}
	found_cover = None
	
	for key, values_dict in opf_dict["manifest"].items():
		if "media-type" in values_dict and "image" in values_dict["media-type"]:
			image_path = values_dict["href"]
			image_filename = os.path.basename(image_path)
			output_image_path = os.path.join(output_dir, image_filename)

			# Extract and save the image file
			with open(output_image_path, 'wb') as image_file:
				image_file.write(epub_zip.read(image_path))
			
			# Store the key and the path for later identification of the cover
			image_files[key] = output_image_path

			# Check if this image is explicitly marked as the cover
			if "properties" in values_dict and values_dict["properties"] == "cover-image":
				found_cover = key
	
	return image_files, found_cover

# Identify the cover image from the extracted images and save it separately
def identify_and_save_cover_image(opf_dict, image_files, output_dir, cover_key=None):
	# If cover_key is provided, use it to identify the cover image
	if cover_key is not None and cover_key in image_files:
		cover_image_path = image_files[cover_key]
		cover_extension = os.path.splitext(cover_image_path)[1]
		cover_output_path = os.path.join(output_dir, f"cover{cover_extension}")

		# Copy the image file as cover
		with open(cover_output_path, 'wb') as cover_file:
			with open(cover_image_path, 'rb') as original_image:
				cover_file.write(original_image.read())

		print(f"Cover image identified and saved as: {cover_output_path}")
		return cover_output_path

	# Otherwise, look in OPF_dict for the cover-image reference in metadata
	if "metadata" in opf_dict and "meta" in opf_dict["metadata"]:
		meta_metadata_opf = opf_dict["metadata"]["meta"]

		for meta_item in meta_metadata_opf:
			if isinstance(meta_item, dict) and meta_item.get("content") == "cover-image":
				cover_key = meta_item.get("name")

				if cover_key in image_files:
					cover_image_path = image_files[cover_key]
					cover_extension = os.path.splitext(cover_image_path)[1]
					cover_output_path = os.path.join(output_dir, f"cover{cover_extension}")

					# Copy the image file as cover
					with open(cover_output_path, 'wb') as cover_file:
						with open(cover_image_path, 'rb') as original_image:
							cover_file.write(original_image.read())

					print(f"Cover image identified and saved as: {cover_output_path}")
					return cover_output_path

	print("No cover image identified.")
	return None

# Main function that orchestrates the entire EPUB processing
def main(args):
	epub_zip = args.epub_location

	# Extract the container.xml contents
	container_file_contents = epub_zip.read("META-INF/container.xml")

	content_handler = ContainerHandler()
	xml.sax.parseString(container_file_contents, content_handler)

	# Parse the OPF file(s) specified in container.xml
	OPF_dict = {}
	Last_TOC_Location = ""
	for rootfile in content_handler.rootfiles:
		if "full-path" in rootfile:
			print("Reading rootfile: {}".format(rootfile["full-path"]))
			opf_file_contents = epub_zip.read(rootfile["full-path"])
			rootfile_loc = os.path.dirname(rootfile["full-path"])
			OPF_Handler = OpenPackageFormatHandler()
			xml.sax.parseString(opf_file_contents, OPF_Handler)
			OPF_Handler.updateHREF(rootfile_loc)

			if OPF_Handler.state_set_as_dict["spine_toc_id"] != "":
				Last_TOC_Location = rootfile_loc

			for key, value in OPF_Handler.state_set_as_dict.items():
				if len(value) != 0 or (isinstance(value, str) and value != ""):
					OPF_dict[key] = value

	# Dump images from the EPUB
	output_dir = os.path.dirname(args.output)
	image_files, found_cover = dump_images(OPF_dict, epub_zip, output_dir)

	# Identify and save the cover image
	identify_and_save_cover_image(OPF_dict, image_files, output_dir, cover_key=found_cover)

	# Identify and parse the Table of Contents (TOC) file
	if OPF_dict["spine_toc_id"] != "":
		toc_index = OPF_dict["spine_toc_id"]
		if toc_index in OPF_dict["manifest"]:
			toc_dict = OPF_dict["manifest"][toc_index]
			if "href" in toc_dict:
				toc_path = toc_dict["href"]
				print("TOC file: {}".format(toc_path))
				toc_file_contents = epub_zip.read(toc_path)
			else:
				print(f"ERROR: TOC file at path {toc_path} has no 'href' information")
				exit(1)
		else:
			print(f"ERROR: TOC key from spine '{toc_index}', is not found in manifest.")
			exit(2)
	else:
		print("ERROR: Never found a spine toc id in spine attributes.")
		exit(2)

	pprint.PrettyPrinter().pprint(OPF_dict)

	# Identify entry points to the spine
	TOC_Handler = TableOfContentsHandler()
	xml.sax.parseString(toc_file_contents, TOC_Handler)

	if Last_TOC_Location != "":
		print(Last_TOC_Location)
		TOC_Handler.updateSRC(Last_TOC_Location)

	# Convert TOC navigation points into a flat list
	TOC_Splitting_list = recursiveNavPointList_2_split_list(copy.deepcopy(TOC_Handler.navPointList))

	# Extract relevant "body" HTML content from the lists of contiguous spine entries (between TOC entry points)
	full_spine = []

	for spine_id in OPF_dict["spine"]:
		if spine_id in OPF_dict["manifest"]:
			local_manifest = OPF_dict["manifest"][spine_id]
			local_manifest["id"] = spine_id
			if "href" in local_manifest:
				spine_path = local_manifest["href"]
				spine_entry_file_contents = epub_zip.read(spine_path)
				Body_Handler = BodyXHTMLHandler()
				xml.sax.parseString(spine_entry_file_contents, Body_Handler)
				Body_Handler.clean_empty_content()
				body_list = Body_Handler.bodyContentList
				body_list[0]["path"] = spine_path
				full_spine.extend(body_list)

	epub_zip.close()

	# Generate a structured book format combining TOC and spine data
	general_book_tracklist = generate_book(TOC_Splitting_list, full_spine)
	general_book_dictionary = {
		"tracklist": general_book_tracklist,
		"metadata": OPF_dict["metadata"]
	}

	# pprint.pprint(general_book_dictionary)

	# Write the generalized EPUB description to a JSON file
	with open(args.output, "w") as outfile:
		json.dump(general_book_dictionary, outfile, indent=4, sort_keys=True)

# Function to validate and return the output file path
def valid_output_file(string):
	return string

# Entry point of the script
if __name__ == "__main__":
	default_output = "generalized_epub.json"
	parser = argparse.ArgumentParser()
	parser.add_argument("epub_location", type=epub_type, help="The location for the target epub")
	parser.add_argument("-o", "--output", type=valid_output_file, default=default_output, help="The output location for the general epub json description. Default is '{}'".format(default_output))
	args = parser.parse_args()

	main(args)
