#!/usr/bin/env python3
"""Fetch a business's Google Business Profile / Google Maps photos via the Apify
actor `solidcode/google-maps-photos-scraper`, then download them locally so the
localwebdev build can drop them into a gallery.

Runs the actor synchronously (run-sync-get-dataset-items), normalizes each Google
image URL to a web-friendly resolution, downloads up to --max images into --out,
and writes a `gallery.json` manifest (filename, category, owner flag, source URL)
that the site build reads to render the gallery.

Stdlib only — no pip install needed at runtime.

Usage:
  APIFY_TOKEN=... python3 fetch_gbp_photos.py \
      --url "https://www.google.com/maps/place/..." \
      --out ~/dev/<slug>/public/assets/gallery \
      --max 12 --size s1600 --owner-only

Exit codes: 0 = at least one photo downloaded; 2 = no photos / actor returned
nothing; 3 = bad usage / missing token; 4 = actor call failed.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

ACTOR = "solidcode~google-maps-photos-scraper"
RUN_SYNC = (
    "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    "?token={token}&format=json"
)

# Keys we try, in order, when pulling a URL / category / owner-flag out of a
# photo object (the actor's exact field names can vary between versions).
URL_KEYS = ("imageUrl", "image", "url", "photoUrl", "src", "link", "photo_url")
CATEGORY_KEYS = ("category", "photoCategory", "label", "group", "categoryName")
OWNER_KEYS = ("isOwner", "byOwner", "is_owner", "owner")


def log(msg):
    print(f"[gbp-photos] {msg}", file=sys.stderr)


def run_actor(place_url, token, timeout=300):
    """Run the actor synchronously and return the list of dataset items."""
    endpoint = RUN_SYNC.format(actor=ACTOR, token=token)
    body = json.dumps({"placeUrls": [place_url]}).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        log(f"Apify HTTP {e.code}: {detail}")
        sys.exit(4)
    except (urllib.error.URLError, TimeoutError) as e:
        log(f"Apify request failed: {e}")
        sys.exit(4)
    if isinstance(data, dict):  # error payload or single item
        if "error" in data:
            log(f"Apify error: {data['error']}")
            sys.exit(4)
        data = [data]
    return data


def extract_photos(items):
    """Flatten dataset items into a list of dicts: {url, category, owner, place}."""
    out = []
    for item in items:
        place = item.get("placeName") or item.get("place") or ""
        photos = item.get("photos") or item.get("images") or []
        for p in photos:
            if isinstance(p, str):
                url, cat, owner = p, "", False
            elif isinstance(p, dict):
                url = next((p[k] for k in URL_KEYS if p.get(k)), None)
                cat = next((str(p[k]) for k in CATEGORY_KEYS if p.get(k)), "")
                owner = any(bool(p.get(k)) for k in OWNER_KEYS) or (
                    "owner" in cat.lower()
                )
            else:
                continue
            if url:
                out.append({"url": url, "category": cat, "owner": owner, "place": place})
    return out


def normalize_size(url, size):
    """Rewrite a Google image URL's size directive (the part after the final '=')."""
    host_ok = "googleusercontent.com" in url or "ggpht.com" in url
    if not host_ok:
        return url
    last_seg = url.rsplit("/", 1)[-1]
    if "=" in last_seg:
        return url.rsplit("=", 1)[0] + "=" + size
    return url + "=" + size


def download(url, dest, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            raise ValueError(f"not an image (content-type: {ctype or 'unknown'})")
        with open(dest, "wb") as f:
            f.write(resp.read())


def main():
    ap = argparse.ArgumentParser(description="Fetch GBP/Google Maps photos via Apify.")
    ap.add_argument("--url", required=True, help="Google Maps place URL")
    ap.add_argument("--out", required=True, help="output directory for images")
    ap.add_argument("--max", type=int, default=12, help="max photos to download")
    ap.add_argument("--size", default="s1600",
                    help="Google size directive (e.g. s1600, s2048, s0=original)")
    ap.add_argument("--owner-only", action="store_true",
                    help="keep only owner-posted photos when the actor labels them")
    ap.add_argument("--token", default=os.environ.get("APIFY_TOKEN"),
                    help="Apify API token (defaults to $APIFY_TOKEN)")
    args = ap.parse_args()

    if not args.token:
        log("No Apify token. Set APIFY_TOKEN or pass --token. Skipping GBP photos.")
        sys.exit(3)

    log(f"Running actor {ACTOR} for: {args.url}")
    t0 = time.time()
    items = run_actor(args.url, args.token)
    photos = extract_photos(items)
    log(f"Actor returned {len(photos)} photo(s) in {time.time() - t0:.0f}s")

    if args.owner_only:
        owned = [p for p in photos if p["owner"]]
        if owned:
            log(f"Filtering to {len(owned)} owner-posted photo(s)")
            photos = owned
        else:
            log("No photos were labeled owner-posted; keeping all (review rights).")

    if not photos:
        log("No photos found for this place.")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)
    manifest, n = [], 0
    for p in photos:
        if n >= args.max:
            break
        src = normalize_size(p["url"], args.size)
        fname = f"photo-{n + 1:02d}.jpg"
        try:
            download(src, os.path.join(args.out, fname))
        except Exception as e:  # skip a bad image, keep going
            log(f"  skip {fname}: {e}")
            continue
        manifest.append({
            "file": fname,
            "category": p["category"],
            "owner": p["owner"],
            "source": src,
            "place": p["place"],
        })
        n += 1

    if not manifest:
        log("Every download failed.")
        sys.exit(2)

    with open(os.path.join(args.out, "gallery.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"Downloaded {len(manifest)} photo(s) → {args.out} (+ gallery.json)")
    # Machine-readable summary on stdout for the caller.
    print(json.dumps({"count": len(manifest), "dir": args.out,
                      "files": [m["file"] for m in manifest]}))


if __name__ == "__main__":
    main()
