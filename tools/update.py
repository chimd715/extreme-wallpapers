#!/usr/bin/env python3
"""Extreme 새 탭 배경 사진첩을 갱신한다.

    python3 tools/update.py              새 사진을 넣고 오래된 사진을 zip으로 보관한다 (manifest.json, archive/index.json 수정)
    python3 tools/update.py --prune      manifest.json에 없는 library 릴리즈 파일을 지운다 (manifest를 올린 뒤에 실행)
    python3 tools/update.py --dry-run    무엇을 할지 출력만 한다 (내려받기·올리기 없음)

출처
- 위키미디어 공용 추천 사진 (풍경 분류). curated.json의 사진을 먼저 넣고, 다 쓰면 새로 추천된 사진을 자동으로 고른다.
  3840px 썸네일을 받아 가로 2560px JPEG로 줄여 library 릴리즈에 올린다.
- Unsplash "Wallpapers" 주제 (저장소 비밀 값 UNSPLASH_ACCESS_KEY가 있을 때만). Unsplash API 규칙대로 사진은 Unsplash
  주소에서 바로 받게 하고(사본을 올리지 않음), 사진첩에 넣을 때 다운로드 알림을 보낸다.

보관: 사진첩이 MAX_IMAGES장을 넘거나 MAX_AGE_DAYS일이 지난 사진(MIN_IMAGES장은 남김)은 사진과 출처 정보(credits.json)를
zip 하나로 묶어 archive 릴리즈에 올리고 사진첩에서 뺀다. archive/index.json에 기록이 남아 다시 들어오지 않는다.

필요한 것: Python 3.10+, Pillow, gh(GitHub CLI, GH_TOKEN).
"""
import argparse
import datetime as dt
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO = os.environ.get("GITHUB_REPOSITORY", "chimd715/extreme-wallpapers")
USER_AGENT = "ExtremeWallpapers/1.0 (https://github.com/%s)" % REPO
LIBRARY_TAG = "library"
ARCHIVE_TAG = "archive"

WIDTH = 2560                 # 사진첩 사진의 가로 크기 (Brave 새 탭 사진과 같음)
JPEG_QUALITY = 82
INITIAL_COUNT = 24           # 사진첩이 비어 있을 때 한 번에 넣을 수
WIKIMEDIA_PER_RUN = 6        # 주마다 넣을 위키미디어 사진 수
UNSPLASH_PER_RUN = 2         # 주마다 넣을 Unsplash 사진 수 (키가 있을 때)
MAX_IMAGES = 60
MIN_IMAGES = 24
MAX_AGE_DAYS = 120

CATEGORIES = [
    "Featured pictures of landscapes",
    "Featured pictures of mountains",
    "Featured pictures of lakes",
    "Featured pictures of coasts",
    "Featured pictures of forests",
]
ALLOWED_LICENSES = ("CC BY-SA", "CC BY", "CC0", "Public domain", "FAL")
MIN_SOURCE_WIDTH = 3000
RATIO_RANGE = (1.45, 1.9)    # 가로 화면에 꽉 차는 비율만
UNSPLASH_TOPICS = ["wallpapers", "nature"]
UNSPLASH_UTM = "utm_source=extreme&utm_medium=referral"


# -- 파일 ---------------------------------------------------------------------------

def load(name, default):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(name, value):
    path = os.path.join(ROOT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def log(*parts):
    print(*parts, flush=True)


# -- 네트워크 -------------------------------------------------------------------------

def fetch(url, headers=None, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001
            if attempt == attempts - 1:
                raise
            log("  retry %s (%s)" % (url[:90], error))
            time.sleep(3 * (attempt + 1))


def fetch_json(url, headers=None):
    return json.loads(fetch(url, headers))


def gh(*args, check=True):
    return subprocess.run(["gh", *args, "--repo", REPO], check=check, text=True, capture_output=True)


# -- 위키미디어 공용 --------------------------------------------------------------------

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
INFO_PARAMS = {
    "prop": "imageinfo",
    "iiprop": "url|size|user|extmetadata",
    "iiurlwidth": 3840,
    "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|ObjectName",
}


def commons(params):
    query = {"action": "query", "format": "json", "formatversion": 2, **params}
    return fetch_json(COMMONS_API + "?" + urllib.parse.urlencode(query))


def plain(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def clean_author(text):
    """"This Photo was taken by X", "Original: X Derivative work: Y" 같은 문구를 이름만 남긴다."""
    if "Derivative work" in text and "Original:" in text:
        text = text.split("Derivative work")[0].split("Original:", 1)[1]
    text = re.sub(r"^(this photo was taken by|photo by|photograph by|photographer:|author:)\s*", "", text.strip(), flags=re.I)
    text = re.split(r"\s[.·|]\s|\s+feel free", text, flags=re.I)[0]
    text = text.strip(" .,;:-")
    return text[:80].rstrip() if len(text) > 80 else text


def author_name(artist_html):
    name = clean_author(plain(artist_html))
    if not name or "@" in name or name.lower().startswith(("feel free", "please", "own work")):
        # 이름 대신 안내 문구만 있으면 작가의 위키미디어 사용자 이름을 쓴다
        user = re.search(r"User:([^\"&#?/|]+)", artist_html)
        name = urllib.parse.unquote(user.group(1)).replace("_", " ").strip() if user else ""
    return name


def page_info(page):
    info = (page.get("imageinfo") or [None])[0]
    if not info or not info.get("height"):
        return None
    meta = info.get("extmetadata", {})
    return {
        "pageid": page["pageid"],
        "title": page["title"],
        "width": info["width"],
        "height": info["height"],
        "thumb": info.get("thumburl") or info["url"],
        "page": info["descriptionurl"],
        # 작가 칸에 이름이 없으면 올린 사람
        "author": author_name(meta.get("Artist", {}).get("value") or "") or info.get("user", ""),
        "license": plain(meta.get("LicenseShortName", {}).get("value")),
        "licenseUrl": meta.get("LicenseUrl", {}).get("value") or None,
        "name": plain(meta.get("ObjectName", {}).get("value")) or None,
    }


def wikimedia_by_titles(titles):
    found = {}
    for start in range(0, len(titles), 25):
        data = commons({"titles": "|".join(titles[start:start + 25]), **INFO_PARAMS})
        for page in data["query"]["pages"]:
            info = page_info(page)
            if info:
                found[info["title"]] = info
    return found


def wikimedia_recent(limit_per_category=50):
    """분류에 최근 추가된 추천 사진부터."""
    results = []
    for category in CATEGORIES:
        data = commons({
            "generator": "categorymembers", "gcmtitle": "Category:" + category, "gcmtype": "file",
            "gcmsort": "timestamp", "gcmdir": "desc", "gcmlimit": limit_per_category, **INFO_PARAMS,
        })
        pages = data.get("query", {}).get("pages", [])
        results.extend(filter(None, (page_info(page) for page in pages)))
        time.sleep(0.5)
    return results


def wikimedia_eligible(info):
    ratio = info["width"] / info["height"]
    return (info["license"].startswith(ALLOWED_LICENSES) and info["width"] >= MIN_SOURCE_WIDTH
            and RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1] and info["author"])


def resize_jpeg(data):
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    icc = image.info.get("icc_profile")
    image = image.convert("RGB")
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True, icc_profile=icc)
    return out.getvalue(), image.width, image.height


def wikimedia_entry(info, today, folder):
    data, width, height = resize_jpeg(fetch(info["thumb"]))
    entry_id = "wm-%d" % info["pageid"]
    path = os.path.join(folder, entry_id + ".jpg")
    with open(path, "wb") as f:
        f.write(data)
    entry = {
        "id": entry_id,
        "source": "wikimedia",
        "title": info["title"],
        "url": "https://github.com/%s/releases/download/%s/%s.jpg" % (REPO, LIBRARY_TAG, entry_id),
        "width": width,
        "height": height,
        "bytes": len(data),
        "author": info["author"],
        "license": info["license"],
        "licenseUrl": info["licenseUrl"],
        "page": info["page"],
        "addedAt": today,
    }
    return entry, path


# -- Unsplash -------------------------------------------------------------------------

def unsplash_candidates(key, seen):
    headers = {"Authorization": "Client-ID " + key, "Accept-Version": "v1"}
    picks = []
    for topic in UNSPLASH_TOPICS:
        url = "https://api.unsplash.com/topics/%s/photos?orientation=landscape&order_by=latest&per_page=30" % topic
        for photo in fetch_json(url, headers):
            entry_id = "us-" + photo["id"]
            ratio = photo["width"] / photo["height"]
            if (entry_id in seen or photo.get("premium") or photo.get("plus")
                    or photo["width"] < MIN_SOURCE_WIDTH or not RATIO_RANGE[0] <= ratio <= RATIO_RANGE[1]):
                continue
            seen.add(entry_id)
            picks.append(photo)
    return picks, headers


def unsplash_entry(photo, headers, today, dry_run):
    if not dry_run:
        # Unsplash API 규칙: 사진을 쓸 때 다운로드 알림을 보낸다
        fetch(photo["links"]["download_location"], headers)
    raw = photo["urls"]["raw"]
    separator = "&" if "?" in raw else "?"
    user = photo["user"]
    return {
        "id": "us-" + photo["id"],
        "source": "unsplash",
        "title": photo.get("alt_description") or photo.get("description") or None,
        "url": raw + separator + "w=%d&q=%d&fm=jpg&fit=max" % (WIDTH, JPEG_QUALITY),
        "width": WIDTH,
        "height": round(WIDTH * photo["height"] / photo["width"]),
        "author": user["name"],
        "authorUrl": user["links"]["html"] + "?" + UNSPLASH_UTM,
        "license": "Unsplash License",
        "licenseUrl": "https://unsplash.com/license",
        "page": photo["links"]["html"] + "?" + UNSPLASH_UTM,
        "addedAt": today,
    }


# -- 릴리즈 ----------------------------------------------------------------------------

def ensure_release(tag, title, notes):
    if gh("release", "view", tag, check=False).returncode != 0:
        gh("release", "create", tag, "--title", title, "--notes", notes, "--latest=false")


def release_assets(tag):
    result = gh("release", "view", tag, "--json", "assets", "-q", ".assets[].name", check=False)
    return set(result.stdout.split()) if result.returncode == 0 else set()


# -- 보관 ------------------------------------------------------------------------------

def choose_archive(images, today):
    """사진첩에서 뺄 사진 (오래된 것부터)."""
    ordered = sorted(images, key=lambda image: (image["addedAt"], image["id"]))
    archived = []
    while len(ordered) > MAX_IMAGES:
        archived.append(ordered.pop(0))
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    while len(ordered) > MIN_IMAGES and ordered[0]["addedAt"] < cutoff:
        archived.append(ordered.pop(0))
    return archived


def build_archive(entries, today, folder, existing_names):
    name = "wallpapers-%s.zip" % today
    counter = 2
    while name in existing_names:
        name = "wallpapers-%s-%d.zip" % (today, counter)
        counter += 1
    path = os.path.join(folder, name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:  # JPEG은 더 줄지 않는다
        for entry in entries:
            archive.writestr(entry["id"] + ".jpg", fetch(entry["url"]))
        archive.writestr("credits.json", json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    return name, path


# -- 실행 ------------------------------------------------------------------------------

def update(dry_run):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    manifest = load("manifest.json", {"schemaVersion": 1, "updatedAt": None, "images": []})
    index = load("archive/index.json", {"archives": []})
    curated = load("curated.json", {"titles": []})["titles"]
    blocked = set(load("blocklist.json", {"items": []})["items"])

    images = manifest["images"]
    archived_entries = [entry for archive in index["archives"] for entry in archive["images"]]
    seen = {entry["id"] for entry in images + archived_entries} | blocked
    seen_titles = {entry.get("title") for entry in images + archived_entries if entry["source"] == "wikimedia"} | blocked

    want = INITIAL_COUNT if not images else WIKIMEDIA_PER_RUN
    queue = [title for title in curated if title not in seen_titles]
    log("Library: %d images, %d archived, curated queue: %d" % (len(images), len(archived_entries), len(queue)))

    picks = []
    curated_info = wikimedia_by_titles(queue[:want * 2]) if queue else {}
    for title in queue:
        info = curated_info.get(title)
        if info and "wm-%d" % info["pageid"] not in seen and len(picks) < want:
            picks.append(info)
            seen.add("wm-%d" % info["pageid"])
    if len(picks) < want:
        for info in wikimedia_recent():
            if len(picks) >= want:
                break
            entry_id = "wm-%d" % info["pageid"]
            if entry_id in seen or info["title"] in seen_titles or not wikimedia_eligible(info):
                continue
            picks.append(info)
            seen.add(entry_id)
    log("Wikimedia picks: %d" % len(picks))
    for info in picks:
        log("  + %s (%s, %s)" % (info["title"], info["author"][:40], info["license"]))

    key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    unsplash_photos, unsplash_headers = [], {}
    if key:
        candidates, unsplash_headers = unsplash_candidates(key, seen)
        unsplash_photos = candidates[:UNSPLASH_PER_RUN]
        log("Unsplash picks: %d" % len(unsplash_photos))
        for photo in unsplash_photos:
            log("  + us-%s (%s)" % (photo["id"], photo["user"]["name"]))
    else:
        log("Unsplash: skipped (no UNSPLASH_ACCESS_KEY)")

    if dry_run:
        projected = images + [{"id": "wm-%d" % i["pageid"], "addedAt": today} for i in picks]
        for entry in choose_archive(projected, today):
            log("  - would archive %s (added %s)" % (entry["id"], entry["addedAt"]))
        return

    with tempfile.TemporaryDirectory() as folder:
        new_entries, files = [], []
        for info in picks:
            try:
                entry, path = wikimedia_entry(info, today, folder)
            except Exception as error:  # noqa: BLE001  사진 하나가 실패해도 나머지는 넣는다
                log("  ! skipped %s: %s" % (info["title"], error))
                continue
            new_entries.append(entry)
            files.append(path)
        for photo in unsplash_photos:
            new_entries.append(unsplash_entry(photo, unsplash_headers, today, dry_run))

        if files:
            ensure_release(LIBRARY_TAG, "Library", "Extreme 새 탭 배경 사진첩의 현재 사진 (manifest.json이 가리키는 파일).")
            gh("release", "upload", LIBRARY_TAG, *files, "--clobber")
        images = images + new_entries

        archived = choose_archive(images, today)
        if archived:
            ensure_release(ARCHIVE_TAG, "Archive", "사진첩에서 뺀 사진을 날짜별 zip으로 보관한다. 각 zip의 credits.json에 출처와 이용 허가가 있다.")
            name, path = build_archive(archived, today, folder, release_assets(ARCHIVE_TAG))
            gh("release", "upload", ARCHIVE_TAG, path, "--clobber")
            removed = {entry["id"] for entry in archived}
            images = [entry for entry in images if entry["id"] not in removed]
            index["archives"].append({"file": name, "createdAt": today, "images": archived})
            save("archive/index.json", index)
            log("Archived %d images into %s" % (len(archived), name))

    if new_entries or archived:
        images.sort(key=lambda image: (image["addedAt"], image["id"]), reverse=True)
        save("manifest.json", {
            "schemaVersion": 1,
            "updatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "images": images,
        })
    log("Library now: %d images (+%d, -%d)" % (len(images), len(new_entries), len(archived)))


def prune(dry_run):
    referenced = {entry["id"] + ".jpg" for entry in load("manifest.json", {"images": []})["images"]
                  if entry["source"] == "wikimedia"}
    stale = sorted(name for name in release_assets(LIBRARY_TAG) if name.endswith(".jpg") and name not in referenced)
    for name in stale:
        log("  - %s" % name)
        if not dry_run:
            gh("release", "delete-asset", LIBRARY_TAG, name, "--yes")
    log("Pruned %d library files" % len(stale))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prune", action="store_true", help="manifest.json에 없는 library 릴리즈 파일을 지운다")
    parser.add_argument("--dry-run", action="store_true", help="출력만 하고 바꾸지 않는다")
    args = parser.parse_args()
    if args.prune:
        prune(args.dry_run)
    else:
        update(args.dry_run)


if __name__ == "__main__":
    main()
