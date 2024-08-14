# TTS_epub_reader
A fairy bad implementation of an epub audiobook generator currently leverging AWS Polly as the "reader." BSD License, so steal away.

I am so sorry for how bad this code is...

Assumes you have your ~/.aws/credentials (or euqivalent) set up properly. For example, it should have the following structure:
````
[default]
aws_access_key_id=...
aws_secret_access_key=...
region=....
````
And it tries its best to work with the following bash command:
````
./generate_audiobook.sh <epub_file.epub>
````

And chatgpt thinks I only have 3 non-standard libraries, God help you if it is wrong and I have some cracy depency structure on my local machine somehow. Makeing a venv is likely a better option, do as I say, not as I do.
````
pip install eyed3 boto3 lxml
````
