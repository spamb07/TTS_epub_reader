#!/usr/bin/env python3

import argparse
import os.path
import zipfile
import xml.sax
import pprint
import copy
import re
import json

class ContainerHandler( xml.sax.ContentHandler ):
	def __init__(self):
		self.rootfiles = []

	# Call when an element starts
	def startElement(self, tag, attributes):
		if tag == "rootfile":
			current_rootfile = {}
			for attribute_name, attribute_value in attributes.items():
				current_rootfile[attribute_name] = attribute_value
			self.rootfiles.append(current_rootfile)

	# # Call when an elements ends
	# def endElement(self, tag):
	# 	pass

	# # Call when a character is read
	# def characters(self, content):
	# 	pass

class OpenPackageFormatHandler( xml.sax.ContentHandler ):
	def __init__(self):
		self.state = ""
		self.metadata = {}
		self.manifest = {}
		self.spine = []
		self.guide = {}
		self.current_tag_tag = None
		self.current_tag_dict = None
		self.state_set_as_dict = {
			"metadata" : self.metadata,
			"manifest" : self.manifest,
			"spine" : self.spine,
			"guide" : self.guide,
			"spine_toc_id" : ""
		}

	def updateHREF(self, parentDirPath):
		for key_id, manifest_value in self.manifest.items():
			for key, value in manifest_value.items():
				if key == "href":
					self.manifest[key_id]["href"] = os.path.join(parentDirPath,self.manifest[key_id]["href"])	

	def __dict_append_to_key(dictionary, key, value):
		if key not in dictionary:
			dictionary[key] = value
		else:
			if isinstance(dictionary[key],list):
				dictionary[key].append(value)
			else:
				old_value = dictionary[key]
				dictionary[key] = [old_value, value]

	# Call when an element starts
	def startElement(self, tag, attributes):
		if tag in self.state_set_as_dict.keys():
			self.state = tag

		## Extract Metadata
		if self.state == "metadata":
			if tag == "metadata":
				if "name_spaces" not in self.metadata:
					self.metadata["name_spaces"] = {}
				for key, value in attributes.items():
					if "xmlns:" in key:
						self.metadata["name_spaces"][key.replace("xmlns:", "")] = value

			if tag != "metadata" and self.current_tag_tag is None:
				self.current_tag_tag = tag
				self.current_tag_dict = {}
				for key, value in attributes.items():
					self.current_tag_dict[key] = value

		## Extract Manifest 
		if self.state == "manifest" and tag == "item":
			current_manifest_item = {}
			for key, value in attributes.items():
				if key != "id":
					current_manifest_item[key] = value
			if "id" in attributes.keys():
				self.manifest[attributes.getValue("id")] = current_manifest_item

		## Extract Spine += TOC identification
		if self.state == "spine":
			if tag == "spine":
				if "toc" in attributes.keys():
					self.state_set_as_dict["spine_toc_id"] = attributes.getValue("toc")
			if tag == "itemref":
				if "idref" in attributes.keys():
					self.spine.append(attributes.getValue("idref"))

		## Extract Guide
		if self.state == "guide":
			if tag == "reference":
				current_guide_item = {}
				for key, value in attributes.items():
					if key != "type":
						current_guide_item[key] = value
				if "type" in attributes.keys():
					OpenPackageFormatHandler.__dict_append_to_key(self.guide, attributes.getValue("type"), current_guide_item)

	def characters(self, content):
		if self.state == "metadata" and self.current_tag_tag is not None:
			self.current_tag_dict["text"] = content

	def endElement(self, tag):
		if self.state == "metadata" and self.current_tag_tag is not None:
			if tag == self.current_tag_tag:
				OpenPackageFormatHandler.__dict_append_to_key(self.metadata, self.current_tag_tag, self.current_tag_dict)
				self.current_tag_tag = None
				self.current_tag_dict = None

class TableOfContentsHandler( xml.sax.ContentHandler ):
	def __init__(self):
		self.navPointStack = []
		self.navPointList = []

		self.is_navMap_state = False
		self.awaiting_label_text_tag = False
		self.awaiting_label_text = False

	def updateSRC(self, parentDirPath):
		TableOfContentsHandler.__recursiveUpdateSRC( self.navPointList, parentDirPath )

	def __recursiveUpdateSRC(navPointList, parentDirPath):
		for navPointDict in navPointList:
			if "src" in navPointDict:
				navPointDict["src"] = os.path.join(parentDirPath,navPointDict["src"])
			if "navPointList" in navPointDict and isinstance(navPointDict["navPointList"], list):
				TableOfContentsHandler.__recursiveUpdateSRC(navPointDict["navPointList"], parentDirPath)


	def startElement(self, tag, attributes):
		if tag == "navMap":
			self.is_navMap_state = True

		if self.is_navMap_state and tag == "navPoint":
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
		if self.awaiting_label_text:
			self.navPointStack[-1]["label"] = content

	def endElement(self, tag):
		if self.is_navMap_state and tag == "navMap":
			self.is_navMap_state = False

		if self.is_navMap_state and tag == "navLabel":
			self.awaiting_label_text_tag = False

		if self.is_navMap_state and tag == "text":
			self.awaiting_label_text = False

		if self.is_navMap_state and tag == "navPoint":

			current_navPoint = self.navPointStack.pop()
			if len(self.navPointStack) == 0:
				self.navPointList.append(current_navPoint)
			else:
				if "navPointList" not in self.navPointStack[-1]:
					self.navPointStack[-1]["navPointList"] = []
				self.navPointStack[-1]["navPointList"].append(current_navPoint)

class BodyXHTMLHandler( xml.sax.ContentHandler ):
	# divTagsDict = {
	# 	## Tags supported in HTML 4.01 and xhtml 1.0: https://www.tutorialspoint.com/html/html_tags_ref.htm
			
	# }

	def __init__(self):
		self.isBody = False
		self.bodyContentStack = []
		self.bodyContentList = []
		self.element_number = 0

	def __get_current_stack_info(self):
		tag_list = []
		stack_info = {}
		for stack_item in reversed(self.bodyContentStack):
			tag_list.append(stack_item["tag"])
			for key, value in stack_item.items():
				if key != "tag" and key != "had_content" and key != "id" and key not in stack_info:
					stack_info[key] = value
		tag_list = list(reversed(tag_list))
		tag_list.pop()
		stack_info["parent_tag_list"] = tag_list
		return stack_info

	def clean_empty_content(self, current_list = None):
		if current_list == None:
			current_list = self.bodyContentList

		to_delete_indecies = []
		for content_index in range(len(current_list)):
			content_item = current_list[content_index]
			
			# "tag" in content_item and content_item["tag"] == "raw_text" and \
			if "id" not in content_item and \
				"content" in content_item and \
				(("had_content" in content_item and not content_item["had_content"]) or ("had_content" not in content_item)):
				if content_item["content"] == '\n':
					to_delete_indecies.append(content_index)
				else:
					empty_regex = r"^\s+$"
					empty_match = re.match(empty_regex, content_item["content"])
					if empty_match != None:
						to_delete_indecies.append(content_index)
			elif "content_list" in content_item and len(content_item["content_list"]) > 0:
				self.clean_empty_content(current_list = content_item["content_list"])

		for delete_index in reversed(to_delete_indecies):
			current_list.pop(delete_index)

	def startElement(self, tag, attributes):
		if tag == "body":
			self.isBody = True
			current_body_item = {}
			current_body_item["tag"] = "{}.{}".format(tag,self.element_number)
			self.element_number += 1
			current_body_item["had_content"] = True
			for key, value in attributes.items():
				current_body_item[key] = value
			self.bodyContentList.append(current_body_item)
		if self.isBody and tag != "body":
			current_body_item = {}
			current_body_item["tag"] = "{}.{}".format(tag,self.element_number)
			self.element_number += 1
			current_body_item["had_content"] = False
			for key, value in attributes.items():
				current_body_item[key] = value
			self.bodyContentStack.append(current_body_item)

	def characters(self, content):
		if self.isBody:
			if len(self.bodyContentStack) == 0:
				self.bodyContentList.append({
					"tag":"{}.{}".format("body",self.element_number), 
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
						if "id" in current_state and not isinstance(current_state["id"],list):
							current_state["id"] = [current_state["id"]]

						if "id" not in current_state:
							current_state["id"] = parent["id"]
						elif isinstance(current_state["id"],list):
							current_state["id"].append(parent["id"])
							
						parent.pop("id")
				current_state["content"] = content
				
				for parent in self.bodyContentStack:
					parent["had_content"] = True
				
				self.bodyContentList.append(current_state)

	def endElement(self, tag):
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
				current_content_list = [ local_content_elem ]
			total_content_list.extend(current_content_list)

	return total_content_list

def epub_type(EPUB_Locaiton):
	# Check file exists, is a file, and is a zip
	if not os.path.exists(EPUB_Locaiton):
		raise argparse.ArgumentTypeError("EPUB Location '{}' does not exist.".format(EPUB_Locaiton))
	elif not os.path.isfile(EPUB_Locaiton):
		raise argparse.ArgumentTypeError("EPUB Location '{}' is not a file, but exists.".format(EPUB_Locaiton))
	elif not zipfile.is_zipfile(EPUB_Locaiton):
		raise argparse.ArgumentTypeError("EPUB Location '{}' can not be opened by zipfile (EPUBS should be a zip).".format(EPUB_Locaiton))
	else:
		pass

	epub_zip_file = zipfile.ZipFile(EPUB_Locaiton)
	
	## Check Mimetype
	pathObj = zipfile.Path(epub_zip_file, at="mimetype")
	if not pathObj.exists():
		raise argparse.ArgumentTypeError("'{}' is missing a mimetype.".format(EPUB_Locaiton))

	mimetype_file_contents = epub_zip_file.read("mimetype")

	if b'application' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'application'")
	if b'epub' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'epub'")
	if b'zip' not in mimetype_file_contents:
		raise argparse.ArgumentTypeError("Epub mimetype doesn't contain 'zip'")

	pathObj = zipfile.Path(epub_zip_file, at="META-INF/container.xml")
	if not pathObj.exists():
		raise argparse.ArgumentTypeError("'{}' is missing a 'META-INF/container.xml'".format(EPUB_Locaiton))

	return zipfile.ZipFile(EPUB_Locaiton)

def recursiveNavPointList_2_split_list( navPointList , parent_label_list = None):
	split_list = []
	for navPoint in navPointList:
		if parent_label_list is not None:
			navPoint["parent_labels"] = parent_label_list

		if "src" in navPoint:
			src_list = navPoint["src"].split("#",1)
			if len(src_list) == 1:
				navPoint["src_path"] = src_list[0]
			else:
				navPoint["src_path"] = src_list[0]
				navPoint["src_id"] = src_list[1]

		if "navPointList" in navPoint:
			if parent_label_list == None:
				current_parent_list = [ navPoint["label"] ]
			else:
				current_parent_list = copy.deepcopy(parent_label_list)
				current_parent_list.append(navPoint["label"])
			nested_split_list = recursiveNavPointList_2_split_list( navPoint.pop("navPointList") , parent_label_list = current_parent_list)

			split_list.append(navPoint)
			split_list.extend(nested_split_list)
		else:
			split_list.append(navPoint)

	return split_list

def generate_book(toc_list, spine_list):
	current_path = None
	complete_book_list = []
	avaliable_toc_list = copy.deepcopy(toc_list)

	current_toc_entry = {
		"label":"Pre Table of Contents"
	}
	current_spine_list = []
	for readable_tag in spine_list:
		if "path" in readable_tag:
			current_path = readable_tag["path"]
			# print("Path: {}".format(current_path))

		if "path" in readable_tag or "id" in readable_tag:
			# print("\tTag:{}".format(readable_tag))

			found_toc = False
			for toc_entry in avaliable_toc_list:
				# print ("{} == {}? {}".format(current_path,toc_entry["src_path"],current_path == toc_entry["src_path"]))
				if "src_path" in toc_entry and current_path == toc_entry["src_path"]:
					if "src_id" not in toc_entry or \
						("id" in readable_tag and readable_tag["id"] == toc_entry["src_id"]) or \
						("id" in readable_tag and isinstance(readable_tag["id"], list) and toc_entry["src_id"] in readable_tag["id"]):
						# print("\t\tTOC:{}".format(toc_entry))
						complete_book_list.append({
							"entry": current_toc_entry,
							"spine_readable_tags":current_spine_list
						})

						current_toc_entry = toc_entry
						current_spine_list = [readable_tag]

						avaliable_toc_list.remove(toc_entry)

						found_toc = True
						break

		if not found_toc:
			current_spine_list.append(readable_tag)

	complete_book_list.append({
		"entry": current_toc_entry,
		"spine_readable_tags":current_spine_list
	})

	return complete_book_list


def main(args):
	epub_zip = args.epub_location

	container_file_contents = epub_zip.read("META-INF/container.xml")

	# container_parser = xml.sax.make_parser()

	content_handler = ContainerHandler()
	xml.sax.parseString(container_file_contents, content_handler)

	## Find OPF File
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
				## TODO: Identify how multiple rootfiles would affect the interpretation across the board...
				if len(value) != 0 or (isinstance(value,str) and value != ""):
					OPF_dict[key] = value

	# print(OPF_Handler.spine_toc_id)
	# pprint.PrettyPrinter().pprint(OPF_dict)

	## Find TOC
	if OPF_dict["spine_toc_id"] != "":
		toc_index = OPF_dict["spine_toc_id"]
		if toc_index in OPF_dict["manifest"]:
			toc_dict = OPF_dict["manifest"][toc_index]
			if "href" in toc_dict:
				toc_path = toc_dict["href"]
				print("TOC file: {}".format(toc_path))
				toc_file_contents = epub_zip.read(toc_path)
			else:
				print("ERROR: TOC file at path {}, has no 'href' information".format(toc_path))
				exit(1)
		else:
			print("ERROR: TOC key from spine '{}', is not found in manifest.".format(toc_index))
			exit(2)
	else:
		print("ERROR: Never found a spine toc id in spine attributes.")
		exit(2)

	## Identify Entry points to Spine
	TOC_Handler = TableOfContentsHandler()
	xml.sax.parseString(toc_file_contents, TOC_Handler)

	if Last_TOC_Location != "":
		print(Last_TOC_Location)
		TOC_Handler.updateSRC(Last_TOC_Location)

	TOC_Splitting_list = recursiveNavPointList_2_split_list(copy.deepcopy(TOC_Handler.navPointList))
	# pprint.PrettyPrinter().pprint(TOC_Splitting_list)
	
	## Extract Relevent "Body" html from lists of contiguous spine entrys (between TOC entry points)
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
				full_spine.extend( body_list )



	epub_zip.close()

	general_book_tracklist = generate_book(TOC_Splitting_list, full_spine)
	general_book_dictionary = {
		"tracklist": general_book_tracklist,
		"metadata": OPF_dict["metadata"]
	}

	with open(args.output, "w") as outfile:
		json.dump(general_book_dictionary, outfile, indent=4, sort_keys=True)

def valid_output_file(string):
	## TODO, actually check if this is a valid location...
	return string

if __name__ == "__main__":
	default_output = "generalized_epub.json"
	parser = argparse.ArgumentParser()
	## Load EPUB Files
	## Validation
	parser.add_argument("epub_location", type=epub_type, help="The location for the target epub")
	parser.add_argument("-o", "--output", type=valid_output_file, default=default_output, help="The output location for the general epub json description. Default is '{}'".format(default_output))
	args = parser.parse_args()

	main(args)