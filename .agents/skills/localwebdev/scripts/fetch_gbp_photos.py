#!/usr/bin/env python3
"""Fetch a business's Google Business Profile / Google Maps photos via the Apify
actor `solidcode/google-maps-photos-scraper`, then download them locally so the
localwebdev build can drop them into a gallery.

Runs the actor synchronously (run-sync-get-dataset-items), normalizes each Google
image URL to a web-friendly resolution, downloads up to --max images into --out,
and converts each to width-capped WebP variants — a large one for desktop plus a
small one for phones — so the gallery never ships oversized full-res photos (the
#1 mobile-PageSpeed killer). Writes a `gallery.json` manifest (file, width, height,
file_sm, width_sm, category, owner, source, place) that the site build reads to
wire each photo into a responsive <picture>/srcset.

Stdlib for the fetch itself; the WebP conversion uses Pillow (`pip install
Pillow`) and falls back to keeping the JPEGs if Pillow isn't installed.

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

try:
    from PIL import Image, ImageOps
    _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS  # Pillow >=9.1 vs older
except ImportError:
    Image = None
    _LANCZOS = None

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


def to_webp(src, dst, max_width=0, quality=80):
    """Convert a downloaded JPEG to WebP with Pillow, capping the width at max_width
    (0 = keep the source size). Only downscales, never upscales; honors EXIF
    orientation so nothing ends up sideways. Returns the output (width, height) on
    success, or None on failure so the caller can fall back to the JPEG."""
    try:
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            if max_width and img.width > max_width:
                height = round(img.height * max_width / img.width)
                img = img.resize((max_width, height), _LANCZOS)
            img.save(dst, "WEBP", quality=quality, method=6)
            return img.size
    except (OSError, ValueError) as e:
        log(f"  WebP convert failed: {e}")
        return None


def main():
    ap = argparse.ArgumentParser(description="Fetch GBP/Google Maps photos via Apify.")
    ap.add_argument("--url", required=True, help="Google Maps place URL")
    ap.add_argument("--out", required=True, help="output directory for images")
    ap.add_argument("--max", type=int, default=12, help="max photos to download")
    ap.add_argument("--size", default="s1600",
                    help="Google size directive (e.g. s1600, s2048, s0=original)")
    ap.add_argument("--owner-only", action="store_true",
                    help="keep only owner-posted photos when the actor labels them")
    ap.add_argument("--max-width", type=int, default=1200,
                    help="cap the large WebP width in px (0 = keep source size; never upscales)")
    ap.add_argument("--sm-width", type=int, default=640,
                    help="width of the small responsive variant in px (0 = skip it)")
    ap.add_argument("--webp-quality", type=int, default=80,
                    help="WebP quality 0-100 (default 80)")
    ap.add_argument("--no-webp", dest="webp", action="store_false",
                    help="skip WebP conversion; keep the downloaded JPEGs as-is")
    ap.set_defaults(webp=True)
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
    webp_ok = args.webp and Image is not None
    if args.webp and not webp_ok:
        log("Pillow not installed (`pip install Pillow`) — shipping JPEGs without WebP conversion.")

    manifest, n = [], 0
    for p in photos:
        if n >= args.max:
            break
        src = normalize_size(p["url"], args.size)
        idx = n + 1
        jpg = os.path.join(args.out, f"photo-{idx:02d}.jpg")
        try:
            download(src, jpg)
        except Exception as e:  # skip a bad image, keep going
            log(f"  skip photo-{idx:02d}: {e}")
            continue
        # Convert to width-capped WebP so the repo is never seeded with oversized
        # full-res JPEGs (the #1 mobile-PageSpeed killer): a large variant for
        # desktop and, when the photo is big enough, a small one for phones — the
        # gallery wires the pair into a responsive srcset. Fall back to the JPEG if
        # Pillow is absent or a convert fails.
        entry = {"file": f"photo-{idx:02d}.jpg", "width": None, "height": None,
                 "file_sm": None, "width_sm": None,
                 "category": p["category"], "owner": p["owner"],
                 "source": src, "place": p["place"]}
        if webp_ok:
            large = os.path.join(args.out, f"photo-{idx:02d}.webp")
            dims = to_webp(jpg, large, args.max_width, args.webp_quality)
            if dims:
                entry["file"] = f"photo-{idx:02d}.webp"
                entry["width"], entry["height"] = dims
                if args.sm_width and dims[0] > args.sm_width:
                    small = os.path.join(args.out, f"photo-{idx:02d}-sm.webp")
                    sm = to_webp(jpg, small, args.sm_width, args.webp_quality)
                    if sm:
                        entry["file_sm"], entry["width_sm"] = f"photo-{idx:02d}-sm.webp", sm[0]
                os.remove(jpg)
            else:
                log(f"  WebP convert failed for photo-{idx:02d}; keeping JPEG")
        manifest.append(entry)
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
