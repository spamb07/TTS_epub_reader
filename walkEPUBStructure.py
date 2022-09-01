#!/usr/bin/env python3

import argparse
import os.path
import zipfile
import pprint
from lxml import etree
import xml.dom.minidom
from io import StringIO
import copy
import re
import math
from shutil import copyfile
import json
from boto3 import Session
from botocore.exceptions import BotoCoreError, ClientError
from contextlib import closing
import eyed3

epubZipPathList = 	[
						"META-INF/container.xml",
						"mimetype",
					]

def cleanMetaEntry(metaTagString):
	metaTagString = metaTagString.replace("/","-")
	metaTagString = metaTagString.replace("\\","-")
	return metaTagString

def errorOut(errorString, error):
	print(
			"~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n" + \
			"ERROR:\n" + \
			errorString + \
			"\n~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"\
		)
	raise error

def checkEPUBLocationValid(EPUB_Locaiton):
	ebub_error_string = ""

	# Check file exists, is a file, and is a zip
	if not os.path.exists(EPUB_Locaiton):
		ebub_error_string += "EPUB Location does not exist."
	elif not os.path.isfile(EPUB_Locaiton):
		ebub_error_string += "EPUB Location is not a file, but exists."
	elif not zipfile.is_zipfile(EPUB_Locaiton):
		ebub_error_string += "EPUB Location can not be opened by zipfile (EPUBS should be a zip)."
	else:
		pass

	if ebub_error_string == "":
		ebub_error_string = None

	return ebub_error_string

def validateEpubLocation(EPUB_Locaiton):
	# Checking EPUB Location Given
	EPUB_notValid_string = checkEPUBLocationValid(EPUB_Locaiton)
	if EPUB_notValid_string:
		errorString = 	"EPUB Location seems incorrect, location given:\n" + \
						EPUB_Locaiton + "\n\n" + \
						"Specific error given:\n" + \
						EPUB_notValid_string
		error = ValueError("EPUB Location not valid, see std.out")
		errorOut(errorString, error)
	return EPUB_Locaiton

def epubZipMinPathsValid(zipfile_obj):
	ebub_error_string = ""

	for path in epubZipPathList:
		pathObj = zipfile.Path(zipfile_obj, at=path)
		if not pathObj.exists():
			ebub_error_string += "EPUB zip is missing: " + path + "\n"

	if ebub_error_string == "":
		ebub_error_string = None

	return ebub_error_string

def validateEPUBZip(epub_zip_file):
	# Check that epub directory structure has minimum needed components for THIS code, might not be completely valid EPUB
	EPUB_zip_notValid_string = epubZipMinPathsValid(epub_zip_file)

	if EPUB_zip_notValid_string:
			errorString = 	"EPUB Zipfile is missing some required file, error info:\n" + \
							EPUB_zip_notValid_string
			error = ValueError("EPUB zipfile missing file, see std.out")
			errorOut(errorString, error)

def eTree2childrenDataDict(etree):
	etreeDict = {}
	etreeIDsDict = {}

	for child in etree.getchildren():
		## Continue if the element is a comment:

		_, _, ctag = str(child.tag).rpartition('}')
		if ctag not in etreeDict:
			etreeDict[ctag] = []
		cattrib = copy.deepcopy(child.attrib)
		newcattrib = {}
		for key, value in cattrib.items():
			_, _, newKey = key.rpartition('}')
			if newKey != key:
				newcattrib[newKey] = value
			else:
				newcattrib[key] = value

		childText = ''.join(child.itertext()).encode('ascii', 'ignore').decode('ascii').strip()
		if childText:
			newcattrib["text"] = childText
		elif child.text:
			newcattrib["text"] = copy.deepcopy(child.text)

		if "id" in newcattrib:
			etreeIDsDict[newcattrib["id"]] = newcattrib

		etreeDict[ctag].append(newcattrib)

	return etreeDict, etreeIDsDict

def applyManifestMetaRefines(metadataDict, metadataIDsDict):
	if "meta" in metadataDict:
		for metaTag in metadataDict["meta"]:
			if "refines" in metaTag:
				_, _, metaID = metaTag["refines"].rpartition('#')
			else:
				continue
				
			if "property" in metaTag:
				metaProperty = metaTag["property"]
			else:
				continue

			if "text" in metaTag:
				metaText = metaTag["text"]
			else:
				continue

			if "scheme" in metaTag:
				metaScheme = metaTag["scheme"]

			metadataIDsDict[metaID][metaProperty] = metaText

		metadataDict.pop("meta")

def loadManifest(manifestDict, loadedEPUBFileDict, zipfile_obj):
	parser =  etree.XMLParser(remove_comments=True)
	fileName = None

	pp = pprint.PrettyPrinter(indent=4)

	pathHeader = "OEBPS"
	pathHeader_alt = "OPS"
	
	# zipfile_obj.printdir()
	# print(zipfile_obj.namelist())

	extractedImageLocations = {}

	for item in manifestDict["item"]:
		mediaType = item["media-type"]

		if item["href"] in zipfile_obj.namelist():
			fileName = item["href"]
		elif os.path.join(pathHeader,item["href"]) in zipfile_obj.namelist():
			fileName = os.path.join(pathHeader,item["href"])
		elif os.path.join(pathHeader_alt,item["href"]) in zipfile_obj.namelist():
			fileName = os.path.join(pathHeader_alt,item["href"])
		else:
			stringError = "Unable to find the relevent reference\nReference:\n" + str(item["href"]) + "\n\nZipfile's Namelist:\n" + str("\n".join(zipfile_obj.namelist()))
			errorOut(stringError, ValueError("Manifest had mis-referenced location"))
		itemID = item["id"]

		if "xml" in mediaType:
			asText = zipfile_obj.read(fileName)
			asText = asText[asText.index(b'<'):]
			
			try:
				loadedEtree = etree.fromstring(asText, parser = parser)
			except etree.XMLSyntaxError as err:
				print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
				print("XML PARSING ERROR!")
				print(fileName + ":")
				print(str(asText))
				print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
				raise err

			loadedEPUBFileDict[fileName] = loadedEtree
			item["xml"] = fileName
			# item["txt"] = asText
		elif "image" in mediaType:
			unzipPath = os.path.join("/tmp","epub")
			unzipPath_full = os.path.join("/tmp","epub",fileName)
			zipfile_obj.extract(fileName, path=unzipPath)
			extractedImageLocations[item["href"]] = unzipPath_full
		elif "text" in mediaType:
			# item["txt"] = zipfile_obj.read(fileName)
			pass
		else:
			pass
			# print("NOT: " + str(item))
			# print(fileName)

	return extractedImageLocations

def findRefInEPUB(refString,loadedEPUBFileDict):
	if "../" in refString:
		refString = refString.replace("../","")
	if "./" in refString:
		refString = refString.replace("./","")

	refString = refString.split("#", 1)[0]

	# print(refString)
	for key, value in loadedEPUBFileDict.items():
		if refString in key:
			# print(key)
			return key

def readInitialEPUBFiles(zipfile_obj, ignoreTOC = False):
	parser =  etree.XMLParser(remove_comments=True)

	pp = pprint.PrettyPrinter(indent=4)

	loadedEPUBFileDict = {}
	for path in epubZipPathList:
		loadedEPUBFileDict[path] = zipfile_obj.read(path)

	if loadedEPUBFileDict["mimetype"] != b'application/epub+zip':
			errorString = 	"Mimetype not 'application/epub+zip', found the following:\n" + \
							str(loadedEPUBFileDict["mimetype"])
			error = ValueError("EPUB Zip has incorrect mimetype")
			errorOut(errorString, error)

	loadedEPUBFileDict["META-INF/container.xml"] = etree.fromstring(loadedEPUBFileDict["META-INF/container.xml"], parser = parser)
	
	
	contentOPF_location = None
	rootfile_locations = loadedEPUBFileDict["META-INF/container.xml"].findall("./rootfiles/rootfile",loadedEPUBFileDict["META-INF/container.xml"].nsmap)
	for rootFileElement in rootfile_locations:
		rootFilePath = rootFileElement.attrib["full-path"]
		loadedEPUBFileDict[rootFilePath] = etree.fromstring(zipfile_obj.read(rootFilePath), parser = parser)
		
		if ".opf" in rootFilePath.lower():
			contentOPF_location = rootFilePath

	if contentOPF_location:
		contentETree = loadedEPUBFileDict[contentOPF_location]

		metadataETree =	contentETree.find("./metadata",contentETree.nsmap)
		print("Reading metadata")
		metadataDict, metadataIDsDict =  eTree2childrenDataDict(metadataETree)
		applyManifestMetaRefines(metadataDict, metadataIDsDict)
		
		manifestETree =	contentETree.find("./manifest",contentETree.nsmap)
		print("Reading manifest")
		manifestDict, manifestIDsDict =  eTree2childrenDataDict(manifestETree)
		extractedImageLocations = loadManifest(manifestDict, loadedEPUBFileDict, zipfile_obj)
		print("Reading spine")
		spineETree = 	contentETree.find("./spine",contentETree.nsmap)
		spineDict, spineIDsDict =  eTree2childrenDataDict(spineETree)

		print("Manifest: ")
		pp.pprint(manifestIDsDict)

		print()

		print("Spine Dict: ")
		pp.pprint(spineDict)

		# zipfile_obj.printdir()

		for itemref in spineDict["itemref"]:
			if	"idref" in itemref and\
				itemref["idref"] in manifestIDsDict and\
				"xml" in manifestIDsDict[itemref["idref"]]:
				
				itemref["xml"] = manifestIDsDict[itemref["idref"]]["xml"]
				itemref["href"] = manifestIDsDict[itemref["idref"]]["href"]

		ncxETree = None
		ncxDict = None
		ncxTag = None
		if "ncx" in manifestIDsDict :
			ncxTag = "ncx"
		elif "toc.ncx" in manifestIDsDict :
			ncxTag = "toc.ncx"

		if ncxTag:
			ncxETree = loadedEPUBFileDict[manifestIDsDict[ncxTag]["xml"]]
			ncxETree_navMap = ncxETree.findall("./navMap/navPoint",ncxETree.nsmap)
			navPointList = []
			for navPoint in ncxETree_navMap:
				navPointDict, navPointIDsDict =  eTree2childrenDataDict(navPoint)
				# print(navPointDict)
				navPointDict["content"][0]["src"] = findRefInEPUB(navPointDict["content"][0]["src"],loadedEPUBFileDict)
				navLabelETree = navPoint.find("./navLabel",navPoint.nsmap)
				navLabelDict, _ =  eTree2childrenDataDict(navLabelETree)
				navPointDict["text"] = navLabelDict["text"][0]["text"]
				navPointDict["src"] = navPointDict["content"][0]["src"]
				# print(navPointDict["content"])
				navPointDict.pop("navLabel")
				navPointDict.pop("content")
				navPointList.append(navPointDict)
			ncxDict = {"navMap": navPointList}

		print("\n\n")

		entryList = None
		if ncxDict and not ignoreTOC:
			pp.pprint(ncxDict)
			if len(ncxDict["navMap"]) > 1:
				entryList = []
				targetXMLList = []
				nextEntryIndex = 0
				targetEntryStart = ncxDict["navMap"][nextEntryIndex]
				# print(targetEntryStart)
				pp.pprint(spineDict)
				for item in spineDict["itemref"]:
					item["href"] = findRefInEPUB(item["href"],loadedEPUBFileDict)
					if targetEntryStart["src"] is None:
						continue
					ncxSrc = targetEntryStart["src"].split("#", 1)[0]
					# print(ncxSrc)
					if item["href"] == ncxSrc:
						if targetEntryStart:
							entryList.append({\
								"index": nextEntryIndex,
								"text": targetEntryStart["text"],
								"xml": None,
							})

						prevEntryStart = targetEntryStart
						while nextEntryIndex < len(ncxDict["navMap"])-1 and prevEntryStart["src"].split("#", 1)[0] == targetEntryStart["src"].split("#", 1)[0]:
							nextEntryIndex += 1
							targetEntryStart = ncxDict["navMap"][nextEntryIndex]
						if len(entryList) > 1:
							entryList[len(entryList)-2]["xml"] = targetXMLList
						targetXMLList = []

					targetXMLList.append(item["xml"])
				entryList[len(entryList)-1]["xml"] = targetXMLList
			else:
				print("BAD ncxDict...doing each xml as an entry?")
				entryList = []
				targetXMLList = []
				nextEntryIndex = 0
				targetEntryStart = ncxDict["navMap"][nextEntryIndex]
				# print(targetEntryStart)
				pp.pprint(spineDict)
				for item in spineDict["itemref"]:
					item["href"] = findRefInEPUB(item["href"],loadedEPUBFileDict)
					entryList.append({\
						"index": nextEntryIndex,
						"text": targetEntryStart["text"],
						"xml": [item["xml"]],
					})
		else:
			entryList = []
			for entryIndex in range(len(spineDict["itemref"])):
				entry = spineDict["itemref"][entryIndex] 
				entryList.append({\
					"index": entryIndex,
					"text": None,
					"xml": [entry["xml"]],
				})


		# print("metadata:")
		# # print(etree.tostring(metadataETree	, pretty_print=True, encoding="unicode"))
		# pp.pprint(metadataDict)
		# print()

		# print("\nmanifest:")
		# # print(etree.tostring(manifestETree	, pretty_print=True, encoding="unicode"))
		# pp.pprint(manifestDict)
		# print()

		# print("\nextracted images:")
		# pp.pprint(extractedImageLocations)

		# print("\nspine:")
		# # print(etree.tostring(spineETree	, pretty_print=True, encoding="unicode"))
		# pp.pprint(spineDict)
		# print()

		# if ncxETree:
		# 	print("\nncx:")
		# 	# print(etree.tostring(ncxETree	, pretty_print=True, encoding="unicode"))
		# 	pp.pprint(ncxDict)
		# 	print()

		# if entryList:
		# 	print("\nentry list:")
		# 	pp.pprint(entryList)
		# 	print()

	# print("\ndir list:")
	# zipfile_obj.printdir()

	return loadedEPUBFileDict, extractedImageLocations, metadataDict, entryList

def applyEPUBMetaTags(metadataDict, entryList):
	pp = pprint.PrettyPrinter(indent=4)
	### Examples from https://github.com/seanap/Plex-Audiobook-Guide
	# TIT1 (CONTENTGROUP) 	Series, Book #
	# TALB (ALBUM) 	Title
	# TIT3 (SUBTITLE) 	Subtitle
	# TPE1 (ARTIST) 	Author, Narrator
	# TPE2 (ALBUMARTIST) 	Author
	# TCOM (COMPOSER) 	Narrator
	# TCON (GENRE) 	Genre1/Genre2
	# TYER (YEAR) 	Copyright Year*
	# COMM (COMMENT) 	Publisher's Summary (MP3)
	# desc (DESCRIPTION) 	Publisher's Summary (M4B)
	# TSOA (ALBUMSORT) 	If ALBUM only, then %Title%
	# 	If ALBUM and SUBTITLE, then %Title% - %Subtitle%
	# 	If Series, then %Series% %Series-part% - %Title%
	# TDRL (RELEASETIME) 	Audiobook Release Year
	# TPUB (PUBLISHER) 	Publisher
	# TCOP (COPYRIGHT) 	Copyright
	# ASIN (ASIN) 	Amazon Standard Identification Number
	# POPM (RATING WMP) 	Audible Rating
	# WOAF (WWWAUDIOFILE) 	Audible Album URL
	# stik (ITUNESMEDIATYPE) 	M4B Media type = Audiobook
	# pgap (ITUNESGAPLESS) 	M4B Gapless album = 1
	# 'shwm' SHOWMOVEMENT 	Show Movement (M4B), if Series then = 1 else blank
	# MVNM MOVEMENTNAME 	Series
	# MVIN MOVEMENT 	Series Book #
	# TXXX (SERIES)** 	Series
	# TXXX (SERIES-PART)** 	Series Book #
	# TXXX (TMP_GENRE1)** 	Genre 1
	# TXXX (TMP_GENRE2)** 	Genre 2
	# CoverUrl 	Album Cover Art
	# TIT2 (TITLE) 	Not Scraped, but used for Chapter Title
	# 	If no chapter data available set to filename

	# print("metadata:")
	# pp.pprint(metadataDict)
	# print()

	albumMetaTags = {}

	# Apply creator based information
	if "creator" in metadataDict:
		creatorBlockList = metadataDict["creator"]
		if len(creatorBlockList) > 1:
			# Order Creators:
			toReorder = list(range(len(creatorBlockList)))
			while toReorder:
				currentIndex = toReorder[0]
				moveTo = None
				if "display-seq" in creatorBlockList[currentIndex]:
					moveTo = int(creatorBlockList[currentIndex]["display-seq"]) - 1
					copyCreator = creatorBlockList[moveTo]
					creatorBlockList[moveTo] = creatorBlockList[currentIndex]
					creatorBlockList[currentIndex] = copyCreator

				if not moveTo:
					toReorder.pop(toReorder.index(currentIndex))
				elif moveTo in toReorder:
					toReorder.pop(toReorder.index(moveTo))

			# Find creator assignment
			for creator in creatorBlockList:
				if "role" in creator:
					if "aut" in creator["role"].lower():
						if "file-as" in creator:
							author = creator["file-as"]
						else:
							author = creator["text"]

						albumMetaTags["ARTIST"] = author
						albumMetaTags["ALBUMARTIST"] = author
					if "tr" in creator["role"].lower():
						if "file-as" in creator:
							translator = creator["file-as"]
						else:
							translator = creator["text"]
						albumMetaTags["COMPOSER"] = translator

		# If only single creator or Artists never applied, use first creator instead
		creatorBlock = creatorBlockList[0]
		if "ARTIST" not in albumMetaTags:
			if "file-as" in creatorBlock:
				author = creatorBlock["file-as"]
			elif "text" in creatorBlock:
				author = creatorBlock["text"]
			albumMetaTags["ARTIST"] = author
			albumMetaTags["ALBUMARTIST"] = author

	# Apply publisher based information
	if "publisher" in metadataDict:
		publisherBlock = metadataDict["publisher"][0]
		if "file-as" in publisherBlock:
			albumMetaTags["PUBLISHER"] = publisherBlock["file-as"]
		elif "text" in publisherBlock:
			albumMetaTags["PUBLISHER"] = publisherBlock["text"]

	# Apply date based information
	if "date" in metadataDict:
		dateBlockList = metadataDict["date"]
		if len(dateBlockList) > 1:
			for dateBlock in dateBlockList:
				if "event" in dateBlock:
					if "publication" in dateBlock["event"]:
						yearMatch = re.findall(r"([1-2][0-9][0-9][0-9])",dateBlock["text"])
						if yearMatch:
							albumMetaTags["YEAR"] = yearMatch[0]
				if "YEAR" in albumMetaTags:
					break
		else:
			dateBlock = dateBlockList[0]
			yearMatch = re.findall(r"([1-2][0-9][0-9][0-9])",dateBlock["text"])
			if yearMatch:
				albumMetaTags["YEAR"] = yearMatch[0]

	# Apply copyright based information
	if "rights" in metadataDict:
		rightsBlock = metadataDict["rights"][0]
		if "file-as" in rightsBlock:
			albumMetaTags["COPYRIGHT"] = rightsBlock["file-as"]
		elif "text" in rightsBlock:
			albumMetaTags["COPYRIGHT"] = rightsBlock["text"]

		if "YEAR" not in albumMetaTags and "COPYRIGHT" in albumMetaTags and albumMetaTags["COPYRIGHT"]:
			yearMatch = re.findall(r"([1-2][0-9][0-9][0-9])",albumMetaTags["COPYRIGHT"])
			if yearMatch:
				albumMetaTags["YEAR"] = yearMatch[0]

	# Apply title based information
	if "title" in metadataDict:
		titleBlock = metadataDict["title"][0]
		if "file-as" in titleBlock and "text" in titleBlock:
			albumMetaTags["ALBUMSORT"] = titleBlock["text"]
			albumMetaTags["ALBUM"] = titleBlock["file-as"]
		elif "text" in titleBlock:
			albumMetaTags["ALBUMSORT"] = titleBlock["text"]
			albumMetaTags["ALBUM"] = titleBlock["text"]
		elif "file-as" in titleBlock:
			albumMetaTags["ALBUMSORT"] = titleBlock["file-as"]
			albumMetaTags["ALBUM"] = titleBlock["file-as"]

	# Apply creator based information
	if "subject" in metadataDict:
		subjectBlockList = metadataDict["subject"]
		genreList = []
		for subjectBlock in subjectBlockList:
			if "file-as" in subjectBlock:
				genreList.append( subjectBlock["file-as"] )
			elif "text" in subjectBlock:
				genreList.append( subjectBlock["text"] )
		if genreList:
			albumMetaTags["GENRE"] = genreList[0]
			albumMetaTags["TMP_GENREX"] = genreList

	# print("entry list:")
	# pp.pprint(entryList)
	# print()

	for entryIndex in range(len(entryList)):
		entry = entryList[entryIndex]

		entry["metaTags"] = copy.deepcopy(albumMetaTags)
		metaTags = entry["metaTags"]

		if "text" in entry and entry["text"] != None:
			metaTags["TITLE"] = cleanMetaEntry(entry["text"])
		else:
			metaTags["TITLE"] = "Entry Number " + str(entryIndex)

	# print("entry list:")
	# pp.pprint(entryList)
	# print()

	return entryList

def collapse2PTextList(ETreeElement, useDiv=False):
	pp = pprint.PrettyPrinter(indent=4)
	paragraphList = []
	singleTagList = [	"p",
						"h1",
						"h2",
						"h3",
						"h4",
					]

	if useDiv:
		singleTagList.append("div")

	paragraphList.append(''.join(ETreeElement.itertext()).encode('ascii', 'ignore').decode('ascii'))

	_, _, cleanedTag = ETreeElement.tag.rpartition('}')
	isSingleTag = cleanedTag in singleTagList
	# print(cleanedTag + " - " + str(isSingleTag))

	if not isSingleTag:
		for childElement in ETreeElement.getchildren():
			childList = collapse2PTextList(childElement, useDiv=useDiv)

			childrenToRemove = []
			for childIndex in range(len(childList)):
				childText = childList[childIndex]
				if childText in paragraphList[0]:
					childSubstringIndex = paragraphList[0].index(childText)
					# print(childSubstringIndex)
					# print("Before:\n" + paragraphList[0])
					if paragraphList[0][0:childSubstringIndex] == "" or paragraphList[0][0:childSubstringIndex].isspace() or paragraphList[0][childSubstringIndex:] == "" or paragraphList[0][childSubstringIndex:].isspace():
						paragraphList[0] = paragraphList[0].replace(childText," ",1)
					else:
						childrenToRemove.append(childIndex)
					# print("After:\n" + paragraphList[0])
					# print()

			for childIndex in reversed(childrenToRemove):
				childList.pop(childIndex)

			paragraphList.extend(childList)

	return paragraphList

def cleanSSMLString(SSML_P_String):
	SSML_P_String = SSML_P_String.replace("("," ")
	SSML_P_String = SSML_P_String.replace(")"," ")
	SSML_P_String = SSML_P_String.replace("/"," ")
	SSML_P_String = SSML_P_String.replace("\\"," ")
	SSML_P_String = SSML_P_String.replace(":"," ")
	SSML_P_String = SSML_P_String.replace("<"," ")
	SSML_P_String = SSML_P_String.replace(">"," ")
	SSML_P_String = SSML_P_String.replace("=", "equals")
	SSML_P_String = SSML_P_String.replace("&", " and ")
	SSML_P_String = SSML_P_String.replace("\xe2\x80\x9c", "\"")
	SSML_P_String = SSML_P_String.replace("\xe2\x80\x9d", "\"")
	SSML_P_String = SSML_P_String.replace("\r\n", "")
	SSML_P_String = SSML_P_String.replace("\n", "")
	return SSML_P_String

def applyParagraphs2EntryList(entryList, loadedEPUBFileDict, extractedImageLocations, maxParLen = 2000, useDiv = False):
	pp = pprint.PrettyPrinter(indent=4)

	for entry in entryList:
		# pp.pprint(entry)
		if "xml" in entry and len(entry["xml"]) > 0:
			paragraphList = []
			for xmlPage in entry["xml"]:
				if xmlPage in loadedEPUBFileDict:
					# print(xmlPage + ":")
					body =	loadedEPUBFileDict[xmlPage].find("./body",loadedEPUBFileDict[xmlPage].nsmap)
					if not body:
						continue
					# print(etree.tostring(loadedEPUBFileDict[xmlPage], pretty_print=True, encoding="unicode"))
					xmlString = etree.tostring(body, pretty_print=True, encoding="unicode")

					for extractedImageREF, extractedImageLoc  in extractedImageLocations.items():
						if extractedImageREF in xmlString:
							if "images" not in entry:
								entry["images"] = []
							entry["images"].append(extractedImageLoc)

					SSML_P_List = collapse2PTextList(body, useDiv=useDiv)

					onlySpacesIndecies = []
					for P_index in range(len(SSML_P_List)):
						SSML_P_List[P_index] = SSML_P_List[P_index].replace("\n"," ")
						if SSML_P_List[P_index].isspace():
							onlySpacesIndecies.append(P_index)

					for P_index_toRemove in reversed(onlySpacesIndecies):
						SSML_P_List.pop(P_index_toRemove)

					for P_index in range(len(SSML_P_List)):
						SSML_P_List[P_index] = cleanSSMLString(SSML_P_List[P_index])

					while None in SSML_P_List or "" in SSML_P_List or "\n" in SSML_P_List:
						if None in SSML_P_List:
							SSML_P_List.pop(SSML_P_List.index(None))

						if "\n" in SSML_P_List:
							SSML_P_List.pop(SSML_P_List.index("\n"))

						if "" in SSML_P_List:
							SSML_P_List.pop(SSML_P_List.index(""))

					for SSML_P in SSML_P_List:
						if len(SSML_P) > maxParLen:
							Original_SSML_P_dict = {"xml": xmlPage}
							Original_SSML_P_dict["text"] = SSML_P
							Original_SSML_P_dict["chars"] = len(Original_SSML_P_dict["text"])

							targetGroups = math.ceil(len(SSML_P)/maxParLen)
							targetSize = math.floor(len(SSML_P)/targetGroups/100)*100
							sentenceList = re.split('\.',SSML_P)

							currentParagraph = []
							currentChars = 0
							localParagraphList = []
							for sentence in sentenceList:
								currentParagraph.append(sentence + ".")
								currentChars += len(sentence) + 1
								if currentChars > targetSize:
									SSML_P_dict = {"xml": xmlPage}
									SSML_P_dict["text"] = "".join(currentParagraph)
									SSML_P_dict["chars"] = len(SSML_P_dict["text"])

									if SSML_P_dict["chars"] > maxParLen:
										pass
										# pp.pprint(SSML_P_dict)

									paragraphList.append(SSML_P_dict)
									localParagraphList.append(SSML_P_dict)

									currentParagraph = []
									currentChars = 0

							if len(currentParagraph) > 0:
								SSML_P_dict = {"xml": xmlPage}
								SSML_P_dict["text"] = " ".join(currentParagraph)
								SSML_P_dict["chars"] = len(SSML_P_dict["text"])

								if SSML_P_dict["chars"] > maxParLen:
									pass
									# pp.pprint(SSML_P_dict)

								paragraphList.append(SSML_P_dict)
								localParagraphList.append(SSML_P_dict)

								currentParagraph = []
								currentChars = 0

							# print("Original:")
							# pp.pprint(Original_SSML_P_dict)
							# print()
							# print("New:")
							# pp.pprint(localParagraphList)
							# print("\n")

						else:
							SSML_P_dict = {"xml": xmlPage}
							SSML_P_dict["text"] = SSML_P
							SSML_P_dict["chars"] = len(SSML_P)
						
							paragraphList.append(SSML_P_dict)


				else:
					errorOut("XML entry not loaded, Entry:\n" + xmlPage, ValueError("Missing XML entry when loading SSML"))

			entry["paragraphs"] = paragraphList

		# pp.pprint(entry)

def applySSML2EntryList(entryList, maxChars = 2700):
	pp = pprint.PrettyPrinter(indent=4)

	addMarks = True
	addBreaks= False
	breakStrength = "x-strong"
	addProsody = True
	prosodyRate = "medium"
	addEmphasis = False


	
	for entry in entryList:
		if "paragraphs" in entry and len(entry["paragraphs"]) > 0:
			currentChars = 0
			paragraphIndex = 0
			entry["ssml"] = []

			currentSSML = "<speak>\n"
			if addProsody:
				currentSSML = currentSSML + "<prosody rate=\"" + prosodyRate + "\">\n"
			for paragraph in entry["paragraphs"]:
				paragraphLength = paragraph["chars"]
				paragraphText = paragraph["text"]


				paragraph["ssml"] = ""

				paragraph["index"] = paragraphIndex


				if currentChars + paragraphLength < maxChars:
					paragraph["ssml"] += "<p>" + paragraphText + "</p>\n"
					if addMarks:
						paragraph["mark"] = "p" + str(paragraphIndex)
						paragraph["ssml"] += "<mark name=\"" + paragraph["mark"] + "\"/>\n"
						paragraphIndex += 1
					currentSSML += paragraph["ssml"]

					currentChars += paragraphLength

				elif paragraphLength < maxChars:
					if addBreaks:
						currentSSML += "<break strength=\"" + breakStrength + "\"/>\n"
					if addMarks:
						currentSSML += "<mark name=\"end\"/>\n"
					if addProsody:
						currentSSML += "</prosody>\n"
					currentSSML += "</speak>"

					entry["ssml"].append(currentSSML)
					currentSSML = ""

					currentSSML += "<speak>\n"
					if addProsody:
						currentSSML += "<prosody rate=\"" + prosodyRate + "\">\n"
					
					
					paragraph["ssml"] += "<p>" + paragraphText + "</p>\n"
					if addMarks:
						paragraph["mark"] = "p" + str(paragraphIndex)
						paragraph["ssml"] += "<mark name=\"" + paragraph["mark"] + "\"/>\n"
						paragraphIndex += 1
					currentSSML += paragraph["ssml"]

					currentChars = len(paragraphText)
				else:
					# pp.pprint(paragraphText)
					errorOut("Paragraph in Question:\n" +  paragraphText, ValueError("A Single Paragraph exceeds the limits of Polly (" + str(maxChars) + " chars)"))
			if addBreaks:
				currentSSML += "<break strength=\"" + breakStrength + "\"/>\n"
			if addMarks:
						currentSSML += "<mark name=\"end\"/>\n"
			if addProsody:
				currentSSML += "</prosody>\n"
			currentSSML = currentSSML + "</speak>\n"

			entry["ssml"].append(currentSSML)
			currentSSML = ""

def getFirstImage(entryList, extractedImageLocations):
	for entry in entryList:
		if "images" in entry and len(entry["images"]) > 0:
			return entry["images"][0]

	witnessedImage = None
	for key, value in extractedImageLocations.items():
		if not witnessedImage:
			witnessedImage = value

		if "cover" in key.lower():
			return value

	return None

def findTOC(entryList):
	for entryIndex in range(len(entryList)):
		entry = entryList[entryIndex]
		if "xml" in entry and len(entry["xml"]):
			for xmlPage in entry["xml"]:
				if "toc" in xmlPage:
					return entryIndex
				if "paragraphs" in entry:
					for paragraph in entry["paragraphs"]:
						totalString = paragraph["text"]

						if "table of content" in totalString.lower():
							return entryIndex
						if "contents" in totalString.lower():
							return entryIndex

	return -1

def getLikelyTextChapterRange(entryList, likelyTOCEntryIndex):
	SSML_Lengths_List = []
	for entry in entryList:
		if "ssml" in entry:
			SSML_Lengths_List.append(len(entry["ssml"]))
		else:
			SSML_Lengths_List.append(0)

	currentIndexList = []
	consecutiveIndexList = []
	for index in range(len(SSML_Lengths_List)):
		if SSML_Lengths_List[index] != 0:
			currentIndexList.append(index)
		elif len(currentIndexList) > 0:
			consecutiveIndexList.append(currentIndexList)
			currentIndexList = []

	if len(currentIndexList) > 0:
			consecutiveIndexList.append(currentIndexList)

	targetList = consecutiveIndexList[0]
	for consecutiveIndexSet in consecutiveIndexList:
		if len(consecutiveIndexSet) > len(targetList):
			targetList = consecutiveIndexSet

	if likelyTOCEntryIndex and likelyTOCEntryIndex >= targetList[0] and likelyTOCEntryIndex < targetList[len(targetList)-1]:
		return likelyTOCEntryIndex + 1, targetList[len(targetList)-1]
	return targetList[0], targetList[len(targetList)-1]


def readEntryWithPolly(entry ,outfilename, voiceID):
	session = Session() #profile_name="adminuser")
	polly = session.client("polly")

	print("Printing out mp3: " + outfilename + " with voiceID: " + voiceID)
	
	i = 1
	pieces = entry["ssml"]

	# pieces = [pieces[0]]
	chapterJSON = ""

	with open(outfilename, "wb") as out:
		for piece in pieces:
			print("Writing Piece " + str(i) + " out of " + str(len(pieces)))
			# piece = piece.replace("\n","")
			# print(piece)

			try:
				responseAudio = polly.synthesize_speech(Text=piece, TextType="ssml", OutputFormat="mp3",VoiceId=voiceID)
				responseJSON = polly.synthesize_speech(Text=piece, TextType="ssml", OutputFormat="json",SpeechMarkTypes=["ssml","sentence"],VoiceId=voiceID)
			except (BotoCoreError, ClientError) as error:
				print(error)
				print(piece)
				sys.exit(-1)

			if "AudioStream" in responseJSON:
				with closing(responseJSON["AudioStream"]) as stream:
					try:
						chapterJSON = chapterJSON + stream.read().decode("utf-8")
					except IOError as error:
						print(error)
						print(piece)
						sys.exit(-1)

			if "AudioStream" in responseAudio:
				with closing(responseAudio["AudioStream"]) as stream:
					try:
						out.write(stream.read())
					except IOError as error:
						print(error)
						print(piece)
						sys.exit(-1)
			else:
				print("Could not stream audio")
				print(piece)
				sys.exit(-1)

			i=i+1

	ssmlJSON ="[" + ','.join(chapterJSON[:-1].split('\n')) + "]"
	ssmlJSON = json.loads(ssmlJSON)

	entry["returnSSML"] = ssmlJSON

	return ssmlJSON

def applyMetadata2MP3(entry, mp3FileName):
	entry["mp3"] = mp3FileName

	metadata = entry["metaTags"]

	audiofile = eyed3.load(mp3FileName)
	if "ARTIST" in metadata:
		audiofile.tag.artist = metadata["ARTIST"]

	if "ALBUM" in metadata:
		audiofile.tag.album = metadata["ALBUM"]

	if "ALBUMARTIST" in metadata:
		audiofile.tag.album_artist = metadata["ALBUMARTIST"]

	if "TITLE" in metadata:
		audiofile.tag.title = metadata["TITLE"]

	if "TRACK" in metadata:
		audiofile.tag.track_num = metadata["TRACK"]

	audiofile.tag.genre = 183 # u'Audiobook' should be equivalent to 183
	audiofile.tag.save()
	
	lyric = ""
	lyric = lyric + "[ar:{artist}]\n\n".format(artist = metadata["ARTIST"])
	lyric = lyric + "[al:{album}]\n\n".format(album = metadata["ALBUM"])
	lyric = lyric + "[ti:{title}]\n\n".format(title = metadata["TITLE"])
	currentTimeZero = 0
	for ssmlMark in entry["returnSSML"]:
		if ssmlMark["type"] == u"sentence":
			time = ssmlMark["time"] + currentTimeZero
			minutes = time // (60 * 1000)
			time = time - minutes * (60 * 1000)
			seconds = time // 1000
			time = time - seconds * 1000
			hundredths = time // 10

			value = ssmlMark["value"]
			lyric = lyric + "[{mm:02d}:{ss:02d}.{xx:02d}]{value}\n".format(mm = minutes, ss = seconds, xx = hundredths, value = value)

		elif ssmlMark["type"] == u"ssml" and ssmlMark["value"] == u"end":
			currentTimeZero = currentTimeZero + ssmlMark["time"]

	lyricFileName = os.path.splitext(mp3FileName)[0] + ".lrc"
	with open(lyricFileName, "w") as lrc_file:
		lrc_file.write(lyric)

	textOut = ""
	for paragraph in entry["paragraphs"]:
		textOut += paragraph["text"] + "\n\n"

	textFileName = os.path.splitext(mp3FileName)[0] + ".txt"
	with open(textFileName, "w") as txt_file:
		txt_file.write(textOut)

def main(args):
	pp = pprint.PrettyPrinter(indent=4)
	EPUB_Locaiton = validateEpubLocation(args.epub_location)
	
	# Open EPUB as Zip
	with zipfile.ZipFile(EPUB_Locaiton) as epub_zip_file:
		validateEPUBZip(epub_zip_file)

	with zipfile.ZipFile(EPUB_Locaiton) as epub_zip_file:
		loadedEPUBFileDict, extractedImageLocations, metadataDict, entryList = readInitialEPUBFiles(epub_zip_file, ignoreTOC = args.noTOC)

	entryList = applyEPUBMetaTags(metadataDict, entryList)

	applyParagraphs2EntryList(entryList, loadedEPUBFileDict, extractedImageLocations, useDiv = args.useDiv)

	applySSML2EntryList(entryList)

	coverImageLocation = getFirstImage(entryList, extractedImageLocations)

	if not args.noTOC:
		likelyTOCEntryIndex = findTOC(entryList)
	else:
		likelyTOCEntryIndex = None

	likelyTextStartIndex, likelyTextEndIndex = getLikelyTextChapterRange(entryList, likelyTOCEntryIndex)

	if args.startChapterNum:
		likelyTextStartIndex = args.startChapterNum

	if args.endChapterNum:
		likelyTextEndIndex= args.endChapterNum


	print("Cover Image: " + coverImageLocation)
	if likelyTOCEntryIndex:
		print("Likely Table of Contents Entry:")
		paragraphIndex = 0
		for index in range(len(entryList[likelyTOCEntryIndex]["paragraphs"])):
			paragraph = entryList[likelyTOCEntryIndex]["paragraphs"][index]
			if "table of content" in paragraph["text"].lower():
				paragraphIndex = index
				break

		pp.pprint({
					"text":entryList[likelyTOCEntryIndex]["text"],
					"xml":entryList[likelyTOCEntryIndex]["xml"],
					"ssmlLength":len(entryList[likelyTOCEntryIndex]["ssml"]),
					"paragraph":entryList[likelyTOCEntryIndex]["paragraphs"][paragraphIndex]
				})

	print("All Entries:")
	printEntryList = []
	for entry in entryList:
		currentEntry = copy.deepcopy(entry)
		if "ssml" in currentEntry:
			currentEntry["ssml"] = len(currentEntry["ssml"])
		if "paragraphs" in currentEntry:
			currentEntry["paragraphs"] = len(currentEntry["paragraphs"])
		printEntryList.append(currentEntry)
	pp.pprint(printEntryList)

	print("Likely Textual Chapter Range:" + "(" + str(likelyTextStartIndex) + "," + str(likelyTextEndIndex) + ")")
	trackNum = 1
	for entry in entryList[likelyTextStartIndex:min(len(entryList),likelyTextEndIndex+1)]:
		print(str(entry["index"]) + " --- " + str(entry["text"]))

		if "ssml" in entry:
			print("SSML Length: " + str(len(entry["ssml"])))
		else:
			print("SSML Length: " + str(0))

		if "images" in entry:
			print("Images:")
			pp.pprint(entry["images"])

		if "metaTags" in entry:
			entry["metaTags"]["TRACK"] = trackNum
			trackNum += 1
			print("Metadata")
			pp.pprint(entry["metaTags"])

		if "xml" in entry:
			print("XML Listing:")
			pp.pprint(entry["xml"])

		# print()
		# pp.pprint(entry)
		print("\n")

	startEntry = entryList[likelyTextStartIndex]
	metadata = startEntry["metaTags"]

	artist = None
	if "ARTIST" in metadata:
		artist = metadata["ARTIST"]

	album = None
	if "ALBUM" in metadata:
		album = metadata["ALBUM"]


	year = None
	if "YEAR" in metadata:
		year = metadata["YEAR"]

	if year:
		yearString = "[" + year + "] "
	else:
		yearString = ""

	if album:
		albumString = album
	else:
		albumString = "UNKNOWN ALBUM"

	if artist:
		fullPath = os.path.join(artist,yearString + albumString)
	else:
		fullPath = os.path.join(yearString + albumString)
	
	try:
		os.makedirs(fullPath)
	except OSError as error:
		pass
	print(fullPath)

	voice="Amy"
	for entry in entryList[likelyTextStartIndex:min(len(entryList),likelyTextEndIndex+1)]:
		metadata = entry["metaTags"]
		if not metadata["TITLE"]:
			metadata["TITLE"] = ""

		entryJSONfn = str(metadata["TRACK"]) + " - " + str(metadata["TITLE"]) + ".fulldata.json"
		entryMP3fn = str(metadata["TRACK"]) + " - " + str(metadata["TITLE"]) + ".mp3"
		entryJSONpath = os.path.join(fullPath,entryJSONfn)
		entryMP3path = os.path.join(fullPath,entryMP3fn)

		if "images" in entry:
			for imagePath in entry["images"]:
				baseImageName = os.path.basename(imagePath)
				imageOutPath = os.path.join(fullPath,baseImageName)
				copyfile(imagePath, imageOutPath)

		if not args.noRead and "ssml" in entry:
			readEntryWithPolly(entry ,entryMP3path, voice)

			applyMetadata2MP3(entry, entryMP3path)

		with open(entryJSONpath, 'w') as fp:
			json.dump(entry, fp, sort_keys=True, indent=2)

	if coverImageLocation:
		baseImageName = os.path.basename(coverImageLocation)
		imageOutPath = os.path.join(fullPath,baseImageName)
		copyfile(coverImageLocation, imageOutPath)


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("epub_location", help="The location for the target epub")
	parser.add_argument("--noTOC", help="Stipulate there is no table of contents (needed to catch some epubs)", action='store_true', default=False)
	parser.add_argument("--useDiv", help="Add div's as a valid top-level object in the html (breaks most epubs, but a div CAN be used", action='store_true', default=False)
	parser.add_argument("--startChapterNum", help="Overwriting the start chapter number", type=int, default=None)
	parser.add_argument("--endChapterNum", help="Overwriting the ending chapter number", type=int, default=None)
	parser.add_argument("--noRead", help="Turn off polly reading for debugging", action='store_true', default=False)
	args = parser.parse_args()
	main(args)