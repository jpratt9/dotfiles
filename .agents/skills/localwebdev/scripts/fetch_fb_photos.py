#!/usr/bin/env python3
"""Fetch a business's Facebook Page photos via an Apify Facebook-page scraper,
then download them locally so the localwebdev build can drop them into a gallery
— the Google Business Profile sibling of fetch_gbp_photos.py, emitting the SAME
`gallery.json` so §2's gallery-building instructions work unchanged.

Runs the actor synchronously (run-sync-get-dataset-items). The actor returns a
flat array of the page's POSTS (plus a trailing `page_summary` record); each
photo lives at either `image.uri` (single-photo post) or
`album_preview.images[].uri` (multi-photo post). Because these are the page's own
posts, every photo is owner/brand content. Facebook CDN URLs are already resized
and SIGNED (`oh=`/`oe=` expiry params) — we download each `uri` exactly as given
(rewriting it breaks the signature) and promptly, before it expires.

Downloads up to --max images into --out and converts each to width-capped WebP
variants (large for desktop + small for phones) with Pillow, so the repo never
ships oversized full-res photos. Writes a `gallery.json` manifest (file, width,
height, file_sm, width_sm, category, owner, source, place) matching the GBP one.

Stdlib for the fetch; WebP conversion uses Pillow (`pip install Pillow`) and
falls back to keeping the JPEGs if Pillow isn't installed.

Usage:
  APIFY_TOKEN=... python3 fetch_fb_photos.py \
      --url "https://www.facebook.com/<page>" \
      --out ~/dev/<slug>/public/assets/gallery \
      --max 12 --max-posts 25

Exit codes: 0 = at least one photo downloaded; 2 = no photos / actor returned
nothing; 3 = bad usage / missing token; 4 = actor call failed.
"""
import argparse
import json
import os
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

# api-empire/facebook-page-posts-scraper. Input: startUrls (array of page URLs or
# bare page names) + maxPostsPerProfile; useApifyProxy since Facebook blocks
# unproxied scrapers. Output is a flat array of the page's posts, plus a trailing
# page_summary record.
ACTOR = "api-empire~facebook-page-posts-scraper"
RUN_SYNC = (
    "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    "?token={token}&format=json"
)


def log(msg):
    print(f"[fb-photos] {msg}", file=sys.stderr)


def run_actor(page_url, token, max_posts, timeout=300):
    """Run the actor synchronously and return the list of dataset items (posts)."""
    endpoint = RUN_SYNC.format(actor=ACTOR, token=token)
    body = json.dumps({
        "startUrls": [page_url],
        "maxPostsPerProfile": max_posts,
        "proxyConfiguration": {"useApifyProxy": True},
    }).encode("utf-8")
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
    """Flatten the actor's posts into [{url, width, height, place, caption}].

    Each post carries its photo(s) at `image.uri` (single) and/or
    `album_preview.images[].uri` (album); both are None on the other kind. Skip
    the trailing `page_summary` record and video posts (no still photo). Every
    photo is the page's own post, so it's owner/brand content."""
    out = []
    for item in items:
        if not isinstance(item, dict) or item.get("recordType") == "page_summary":
            continue
        place = ((item.get("author") or {}).get("name") or "").strip()
        caption = (item.get("message") or "").strip()

        def add(img):
            if isinstance(img, dict) and img.get("uri"):
                out.append({"url": img["uri"], "width": img.get("width"),
                            "height": img.get("height"), "place": place,
                            "caption": caption})

        add(item.get("image"))                                   # single-photo post
        album = item.get("album_preview")
        if isinstance(album, dict):
            for im in album.get("images") or []:                 # multi-photo post
                add(im)
    return out


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
    orientation. Returns the output (width, height) on success, or None on failure
    so the caller can fall back to the JPEG."""
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
    ap = argparse.ArgumentParser(description="Fetch Facebook Page photos via Apify.")
    ap.add_argument("--url", required=True, help="Facebook page URL")
    ap.add_argument("--out", required=True, help="output directory for images")
    ap.add_argument("--max", type=int, default=12, help="max photos to download")
    ap.add_argument("--max-posts", type=int, default=25,
                    help="how many recent posts the actor scrapes (maxPostsPerProfile)")
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
        log("No Apify token. Set APIFY_TOKEN or pass --token. Skipping FB photos.")
        sys.exit(3)

    log(f"Running actor {ACTOR} for: {args.url}")
    t0 = time.time()
    items = run_actor(args.url, args.token, args.max_posts)
    photos = extract_photos(items)
    log(f"Actor returned {len(photos)} photo(s) in {time.time() - t0:.0f}s")

    if not photos:
        log("No photos found for this page.")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)
    webp_ok = args.webp and Image is not None
    if args.webp and not webp_ok:
        log("Pillow not installed (`pip install Pillow`) — shipping JPEGs without WebP conversion.")

    manifest, n = [], 0
    for p in photos:
        if n >= args.max:
            break
        idx = n + 1
        jpg = os.path.join(args.out, f"photo-{idx:02d}.jpg")
        try:
            download(p["url"], jpg)          # signed FB CDN url — download verbatim
        except Exception as e:  # skip a bad/expired image, keep going
            log(f"  skip photo-{idx:02d}: {e}")
            continue
        # Pre-fill dims from the actor payload so the manifest still has them when
        # Pillow is absent; to_webp overwrites with the real converted size.
        entry = {"file": f"photo-{idx:02d}.jpg", "width": p.get("width"),
                 "height": p.get("height"), "file_sm": None, "width_sm": None,
                 "category": "", "owner": True, "source": p["url"], "place": p["place"]}
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
    print(json.dumps({"count": len(manifest), "dir": args.out,
                      "files": [m["file"] for m in manifest]}))


if __name__ == "__main__":
    main()
