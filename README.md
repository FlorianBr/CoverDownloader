# CoverDownloader

## What is it

Checks recursively all MP3s for missing cover images in their ID3 Tags. Missing covers are grabbed from last.fm and stored in the MP3 file. Existing data is not overwritten.

## How

- Create a last.fm API key at <https://www.last.fm/api/account/create>
- Install the required packages:  ``pip install mutagen requests``
- Add your key at line 10 in the python file ``LASTFM_API_KEY = <YourKey>``
- Start the program and specify the directory as a parameter ``python add_covers.py ./music/``
