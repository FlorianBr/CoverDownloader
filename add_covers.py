import os
import sys
import requests
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error as ID3Error
from mutagen.id3 import ID3NoHeaderError

# Configuration
LASTFM_API_KEY = "<CHANGE_ME>"
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
SUPPORTED_IMAGE_SIZES = ["extralarge", "large", "medium"]

# Colorful output
def printERR(s): print("\033[91m{}\033[00m".format(s))
def printWARN(s): print("\033[93m{}\033[00m".format(s))

# Get artist and album from ID3 tags
def get_mp3_tags(file_path: Path) -> tuple[str | None, str | None]:
    try:
        audio = MP3(str(file_path))
        tags = audio.tags
        
        if tags is None:
            return None, None
            
        artist = str(tags.get("TPE1", [None])[0]) if tags.get("TPE1") else None
        album = str(tags.get("TALB", [None])[0]) if tags.get("TALB") else None
        album_artist = str(tags.get("TPE2", [None])[0]) if tags.get("TPE2") else None
        
        if album_artist:
            artist = album_artist
            
        return artist, album
        
    except Exception as e:
        printWARN(f"[WRN]\t\tUnable to read tags: {file_path}: {e}")
        return None, None

# Embed a image in the MP3 tag
def embed_cover_in_mp3(file_path: Path, image_data: bytes) -> bool:
    try:
        try:
            audio = ID3(str(file_path))
        except ID3NoHeaderError:
            audio = ID3()
        
        mime_type = "image/jpeg"
        if image_data[:4] == b'\x89PNG':
            mime_type = "image/png"
        
        audio.add(APIC(
            encoding=3,
            mime=mime_type,
            type=3,
            desc="Cover",
            data=image_data
        ))
        
        audio.save(str(file_path))
        print(f"[INF]\t\tCover stored {file_path.name}")
        return True
        
    except Exception as e:
        printERR(f"[ERR]\t\tError storing cover {file_path}: {e}")
        return False


# Extract album and artist from directory
def get_album_info_from_path(directory: Path) -> tuple[str, str]:
    dir_name = directory.name
    parent_name = directory.parent.name
    artist = parent_name.strip()
    album = dir_name.strip()
    return artist, album

# Check if file has a cover image
def has_cover_image(file_path: Path) -> bool:
    try:
        audio = ID3(str(file_path))
        for tag in audio.keys():
            if tag.startswith("APIC"):
                return True
        return False
    except ID3NoHeaderError:
        return False
    except Exception as e:
        printERR(f"[ERR] Unable to check {file_path}: {e}")
        return False

# Get the cover from last.fm and return the binary data, or none in case of error
def fetch_cover_from_lastfm(artist: str, album: str) -> bytes | None:
    params = {
        "method": "album.getinfo",
        "api_key": LASTFM_API_KEY,
        "artist": artist,
        "album": album,
        "format": "json"
    }
    headers = {
        "user-agent": "CoverGrabber"
    }
    
    print(f"[INF]\t\tSearching cover for '{artist}' - '{album}'")
    try:
        response = requests.get(LASTFM_API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        printERR(f"[ERR] Network error: {e}")
        return None
       
    data = response.json()

    if "error" in data:
        printERR(f"[ERR]\t\tLast.fm API Error: {data.get('message', 'Unknown error')}")
        return None

    # Extract Data
    album_info = data.get("album", {})
    images = album_info.get("image", [])

    # Extract image
    image_url = None
    for size in SUPPORTED_IMAGE_SIZES:
        for img in images:
            if img.get("size") == size and img.get("#text"):
                image_url = img["#text"]
                break
            if image_url:
                break
        
    if not image_url:
        printERR(f"[ERR] No cover found for '{artist}' - '{album}'")
        return None
            
    print(f"[INF]\t\tCover found: {image_url}")

    # Download the cover
    try:
        img_response = requests.get(image_url, timeout=15)
        img_response.raise_for_status()
    except requests.exceptions.RequestException as e:
        printERR(f"[ERR] Network error: {e}")
        return None
        
    # Check if its a image
    content_type = img_response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        printWARN(f"[WRN] Downloaded file is not a image: {content_type}")
        return None
    
    # TODO: Also save the image to a file
            
    return img_response.content


# Process the directory
def process_directory(directory: Path, stats: dict) -> None:
    mp3_files = list(directory.glob("*.mp3"))
    
    if not mp3_files:
        return
    
    print(f"[INF] Parsing {directory} - Found {len(mp3_files)} MP3s")
    
    # Check if cover is missing    
    files_without_cover = [f for f in mp3_files if not has_cover_image(f)]
    
    if not files_without_cover:
        print("[INF]\t\tCover exists, skipping")
        stats["skipped_dirs"] += 1
        return

    print(f"[INF]\t\tMissing covers: {len(files_without_cover)} files")

    # Get artist and album from Tags    
    artist, album = None, None
    for mp3_file in mp3_files:
        tag_artist, tag_album = get_mp3_tags(mp3_file)
        if tag_artist and tag_album:
            artist = tag_artist
            album = tag_album
            print(f"[INF]\t\tGot metadata from tags: Artist='{artist}', Album='{album}'")
            break

    # Fallback: Use directories
    if not artist or not album:     
        artist, album = get_album_info_from_path(directory)
        print(f"[INF]\t\tGot metadaten from directory: Artist='{artist}', Album='{album}'")
    
    # Fetch cover from last.fm
    cover_data = fetch_cover_from_lastfm(artist, album)

    if cover_data is None:
        printWARN(f"[WRN] No cover found for '{artist}' - '{album}'")
        stats["not_found"] += len(files_without_cover)
        return
    
    # Add cover to all files without cover
    for mp3_file in files_without_cover:
        stats["processed"] += 1
        if embed_cover_in_mp3(mp3_file, cover_data):
            stats["success"] += 1
        else:
            stats["errors"] += 1


# Scan recursive
def scan_music_library(root_path: str) -> None:
    root = Path(root_path)
    
    if not root.exists():
        printERR(f"[ERR] Path does not exist: {root_path}")
        sys.exit(1)
    
    if not root.is_dir():
        printERR(f"[ERR] Path is no directory: {root_path}")
        sys.exit(1)
    
    print(f"[INF] Starting Scan: {root_path}")
    
    stats = {
        "processed": 0,
        "success": 0,
        "errors": 0,
        "not_found": 0,
        "skipped_dirs": 0
    }

    # Process recursive    
    for dirpath in sorted(root.rglob("*")):
        if dirpath.is_dir():
            process_directory(dirpath, stats)
    
    # Show result    
    print("Summary:")
    print(f"  Files:               {stats['processed']}")
    print(f"  Files updated:       {stats['success']}")
    print(f"  Errors:              {stats['errors']}")
    print(f"  No covers:           {stats['not_found']}")
    print(f"  Skipped directories: {stats['skipped_dirs']}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python add_covers.py <Path>")
        sys.exit(1)
    
    music_path = sys.argv[1]
    scan_music_library(music_path)

if __name__ == "__main__":
    main()
