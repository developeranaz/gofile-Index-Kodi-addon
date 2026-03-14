import sys
import re
import json
import os
import urllib.request
import urllib.parse
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
from urllib.parse import urlencode, parse_qs, urljoin

# ─── Addon bootstrap ────────────────────────────────────────────────────────────
addon         = xbmcaddon.Addon()
addon_handle  = int(sys.argv[1])
addon_url     = sys.argv[0]
base_url      = addon.getSetting("base_url") or "https://go.sundaran.workers.dev/"

# Poster sources (no API key required)
TMDB_IMG_BASE  = "https://image.tmdb.org/t/p/w300"
TMDB_SEARCH_MOVIE = "https://api.themoviedb.org/3/search/movie?api_key=2dca580c2a14b55200e784d157207b4d&query={query}&page=1"
TMDB_SEARCH_TV   = "https://api.themoviedb.org/3/search/tv?api_key=2dca580c2a14b55200e784d157207b4d&query={query}&page=1"

# Path for persistent poster cache
profile_dir = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
if not xbmcvfs.exists(profile_dir):
    xbmcvfs.mkdir(profile_dir)
CACHE_FILE = os.path.join(profile_dir, "poster_cache.json")

# ─── Helpers ─────────────────────────────────────────────────────────────────────

def log(msg, level=xbmc.LOGDEBUG):
    xbmc.log(f"[plugin.video.sundaran] {msg}", level)


def fetch(url, timeout=8):
    """HTTP GET → str | None."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Mobile Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         base_url,
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except Exception as exc:
        log(f"fetch failed: {url} → {exc}", xbmc.LOGERROR)
        return None


def clean_title(filename):
    """
    Strip common noise from a filename to get a clean movie/show title.
    Handles patterns like [tag], (year), quality, audio, etc.
    Returns a tuple (clean_title, year, is_tv, season, episode)
    """
    original = filename
    # Remove file extension
    name = re.sub(r"\.(mkv|mp4|avi|mov|ts|m4v|webm|mpg|mpeg)$", "", filename, flags=re.I)

    # Replace dots/underscores/hyphens with spaces
    name = re.sub(r"[._\-]", " ", name)

    # Remove content in square brackets and parentheses (common for release groups)
    name = re.sub(r"\[.*?\]|\(.*?\)", "", name)

    # Try to extract season/episode pattern (S01E02, 1x02, etc.)
    tv_match = re.search(r"[Ss](\d+)[Ee](\d+)", name)
    if tv_match:
        season = int(tv_match.group(1))
        episode = int(tv_match.group(2))
        is_tv = True
    else:
        # Alternative pattern: 1x02
        tv_match = re.search(r"(\d+)x(\d+)", name)
        if tv_match:
            season = int(tv_match.group(1))
            episode = int(tv_match.group(2))
            is_tv = True
        else:
            is_tv = False
            season = episode = None

    # Extract year (4 digits, typically 1900-2099)
    year_match = re.search(r"\b(19|20)\d{2}\b", name)
    year = int(year_match.group(0)) if year_match else None

    # Remove common quality/format tags (including those with year, but keep year if present)
    # We'll remove everything after the year (if year exists) or after a certain point
    tags = [
        r"1080p", r"720p", r"480p", r"4k", r"2160p",
        r"bluray", r"webrip", r"web.?dl", r"hdtv", r"dvdrip",
        r"x264", r"x265", r"hevc", r"avc", r"aac", r"ac3", r"dts",
        r"hdr", r"sdr", r"remux", r"extended", r"theatrical",
        r"proper", r"repack", r"multi", r"hindi", r"tamil", r"telugu",
        r"malayalam", r"dual audio", r"season.*", r"s\d+e\d+", r"episode.*"
    ]
    # Build a regex that matches any of these tags (case insensitive) as whole words or with spaces
    tag_pattern = r"\s*(?:" + "|".join(tags) + r").*$"
    name = re.sub(tag_pattern, "", name, flags=re.I)

    # Clean up multiple spaces
    name = re.sub(r"\s+", " ", name).strip()

    # If we ended up with an empty string, fallback to original cleaned filename
    if not name:
        name = re.sub(r"[._\-]", " ", original)
        name = re.sub(r"\..*$", "", name)  # remove extension

    return name, year, is_tv, season, episode


# ─── Persistent poster cache ─────────────────────────────────────────────────────

def load_cache():
    """Load poster cache from JSON file."""
    if xbmcvfs.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_cache(cache):
    """Save poster cache to JSON file."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    except:
        pass


_poster_cache = load_cache()


def get_poster(title, is_tv=False):
    """
    Fetch a poster URL from TMDB (movie or TV).
    Returns URL string or empty string on failure.
    """
    try:
        query = urllib.parse.quote_plus(title)
        api_url = TMDB_SEARCH_TV.format(query=query) if is_tv else TMDB_SEARCH_MOVIE.format(query=query)
        data = fetch(api_url, timeout=6)
        if not data:
            return ""
        js = json.loads(data)
        results = js.get("results", [])
        if results:
            path = results[0].get("poster_path", "")
            if path:
                return f"{TMDB_IMG_BASE}{path}"
    except Exception as exc:
        log(f"get_poster failed for '{title}' (TV={is_tv}): {exc}", xbmc.LOGWARNING)
    return ""


def poster_for(filename):
    """Return cached or freshly fetched poster URL for a given filename."""
    global _poster_cache
    # Use cache if available
    if filename in _poster_cache:
        return _poster_cache[filename]

    # Clean title and detect type
    title, year, is_tv, season, episode = clean_title(filename)
    # Optionally append year to title to improve search? TMDB handles year separately, but we can include it.
    search_title = title
    if year:
        search_title += f" {year}"

    url = get_poster(search_title, is_tv=is_tv)
    _poster_cache[filename] = url
    save_cache(_poster_cache)  # persist after each new fetch
    log(f"poster for '{filename}' → '{url}' (TV={is_tv})")
    return url


# ─── Directory listing ────────────────────────────────────────────────────────────

def list_items(url):
    html = fetch(url)
    if not html:
        xbmcgui.Dialog().notification("Sundaran", "Could not reach server.", xbmcgui.NOTIFICATION_ERROR, 4000)
        return

    # ── Parent-folder link ────────────────────────────────────────────────────────
    if url != base_url:
        parent_match = re.search(r'<a href="(/\?folder=[^"]+)">.*?Back to Parent Folder</a>', html)
        if parent_match:
            parent_url = urljoin(base_url, parent_match.group(1))
            li = xbmcgui.ListItem("⬆  Parent folder")
            li.setArt({"icon": "DefaultFolderBack.png"})
            xbmcplugin.addDirectoryItem(addon_handle, f"{addon_url}?url={parent_url}", li, isFolder=True)

    # ── Parse file table ─────────────────────────────────────────────────────────
    tbody = re.search(r'<tbody id="fileBody">([\s\S]*?)</tbody>', html)
    if not tbody:
        xbmcgui.Dialog().notification("Sundaran", "Empty folder.", xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(addon_handle)
        return

    items = re.findall(r'<a href="([^"]+)">\s*(?:[📁🎥]\s*)?([^<]+)</a>', tbody.group(1))

    for href, raw_name in items:
        name = raw_name.strip()
        if href == "../" or name == "Parent Directory" or not name:
            continue

        item_url = urljoin(base_url, href)

        if "/download/" in href:
            _add_video(name, item_url)
        elif "?folder=" in href:
            _add_folder(name, item_url)
        else:
            log(f"unknown item type skipped: {href}", xbmc.LOGWARNING)

    # ── Minimalist view hints ─────────────────────────────────────────────────────
    xbmcplugin.setContent(addon_handle, "movies")  # works for both movies and TV shows
    xbmcplugin.addSortMethod(addon_handle, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.addSortMethod(addon_handle, xbmcplugin.SORT_METHOD_DATE)
    xbmcplugin.endOfDirectory(addon_handle)


def _add_folder(name, item_url):
    li = xbmcgui.ListItem(name)
    li.setArt({
        "icon":      "DefaultFolder.png",
        "thumb":     "DefaultFolder.png",
        "fanart":    addon.getAddonInfo("fanart"),
    })
    li.setInfo("video", {"title": name, "mediatype": "video"})
    xbmcplugin.addDirectoryItem(addon_handle, f"{addon_url}?url={item_url}", li, isFolder=True)


def _add_video(name, item_url):
    poster = poster_for(name)
    title, year, is_tv, season, episode = clean_title(name)

    li = xbmcgui.ListItem(title)
    li.setArt({
        "thumb":  poster or "DefaultVideo.png",
        "poster": poster or "DefaultVideo.png",
        "fanart": addon.getAddonInfo("fanart"),
        "icon":   poster or "DefaultVideo.png",
    })

    if is_tv and season is not None and episode is not None:
        # TV episode
        info = {
            "title": title,
            "season": season,
            "episode": episode,
            "mediatype": "episode",
            "tvshowtitle": title,  # assume show title same as cleaned title
        }
        if year:
            info["year"] = year
        li.setInfo("video", info)
        li.setProperty("IsPlayable", "true")
    else:
        # Movie (or unknown)
        info = {"title": title, "mediatype": "movie"}
        if year:
            info["year"] = year
        li.setInfo("video", info)
        li.setProperty("IsPlayable", "true")

    xbmcplugin.addDirectoryItem(addon_handle, item_url, li, isFolder=False)


# ─── Router ──────────────────────────────────────────────────────────────────────

def router():
    params = parse_qs(sys.argv[2][1:])
    url    = params.get("url", [base_url])[0]
    log(f"routing → {url}")
    list_items(url)


if __name__ == "__main__":
    router()