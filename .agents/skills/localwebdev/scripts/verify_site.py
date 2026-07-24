#!/usr/bin/env python3
"""Post-build verifier for localwebdev sites — the deterministic replacement for
"open it and eyeball the hero".

Drives headless Chrome over the DevTools Protocol rather than the command line,
which sidesteps the two traps that make CLI screenshots useless here:

  * `chrome --headless --screenshot` frequently never exits, so every capture
    costs a subprocess timeout (~75s of dead waiting) instead of ~2s.
  * `--window-size=390,844` does NOT give a 390px viewport — Chrome clamps the
    window to a ~500px minimum, so a "mobile" screenshot is really a 500px
    render. Bugs at 390px stay invisible and phantom ones appear.

`Emulation.setDeviceMetricsOverride` sets a true viewport at any width, and the
checks below are geometry assertions evaluated in the page, so the result is a
pass/fail — not a picture someone has to squint at.

Checks, per viewport:
  overflow      the page scrolls horizontally (scrollWidth > clientWidth)
  hero_fold     anything inside the hero <section> extends past the fold
  broken_images an <img> finished loading with naturalWidth 0 (bad src)
  zero_size     an <img> renders at ~0px (e.g. <picture> not carrying grid height)
  hidden_hero   an above-the-fold element is parked at opacity 0 (LCP killer)

Stdlib only — includes a minimal RFC-6455 client, since Python ships no
WebSocket support and CDP requires one.

Usage:
  python3 verify_site.py --dir ~/dev/<slug>
  python3 verify_site.py --dir ~/dev/<slug> --page contact.html --viewport 390x844
  python3 verify_site.py --dir ~/dev/<slug> --shot /tmp/hero.png --json

Exit codes: 0 = all checks passed; 1 = at least one check failed;
            3 = bad usage / page missing; 4 = could not drive Chrome.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

DEFAULT_VIEWPORTS = ("390x844", "768x1024", "1440x900")


def log(msg):
    print(f"[verify] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# minimal WebSocket (RFC 6455) — CDP needs one and the stdlib has none
# --------------------------------------------------------------------------

def encode_frame(payload, opcode=1):
    """Client->server frame. Clients MUST mask (RFC 6455 §5.3)."""
    data = payload.encode() if isinstance(payload, str) else payload
    head = bytearray([0x80 | opcode])
    n = len(data)
    if n < 126:
        head.append(0x80 | n)
    elif n < (1 << 16):
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    mask = os.urandom(4)
    head += mask
    return bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def decode_frame(buf):
    """Parse one frame from the front of `buf`.

    Returns (fin, opcode, payload, rest) or None when more bytes are needed."""
    if len(buf) < 2:
        return None
    fin = bool(buf[0] & 0x80)
    opcode = buf[0] & 0x0F
    masked = bool(buf[1] & 0x80)
    n = buf[1] & 0x7F
    i = 2
    if n == 126:
        if len(buf) < i + 2:
            return None
        n = struct.unpack(">H", buf[i:i + 2])[0]
        i += 2
    elif n == 127:
        if len(buf) < i + 8:
            return None
        n = struct.unpack(">Q", buf[i:i + 8])[0]
        i += 8
    mask = b""
    if masked:
        if len(buf) < i + 4:
            return None
        mask = buf[i:i + 4]
        i += 4
    if len(buf) < i + n:
        return None
    data = buf[i:i + n]
    if masked:
        data = bytes(b ^ mask[j % 4] for j, b in enumerate(data))
    return fin, opcode, data, buf[i + n:]


class WebSocket:
    """Just enough client to talk CDP to a Chrome page target."""

    def __init__(self, url, timeout=30):
        if not url.startswith("ws://"):
            raise ValueError(f"only ws:// supported, got {url!r}")
        rest = url[len("ws://"):]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("handshake closed early")
            self.buf += chunk
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"handshake failed: {head.splitlines()[:1]}")

    def send(self, text):
        self.sock.sendall(encode_frame(text, opcode=1))

    def recv(self):
        """Next complete text message, reassembling continuation frames."""
        parts = []
        while True:
            got = decode_frame(self.buf)
            if got is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("socket closed")
                self.buf += chunk
                continue
            fin, opcode, data, self.buf = got
            if opcode == 0x9:                                  # ping -> pong
                self.sock.sendall(encode_frame(data, opcode=0xA))
                continue
            if opcode == 0x8:
                raise ConnectionError("server closed")
            if opcode == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Chrome
# --------------------------------------------------------------------------

def find_chrome(env=None):
    env = os.environ if env is None else env
    explicit = env.get("CHROME_PATH")
    if explicit:
        return explicit
    for c in CHROME_CANDIDATES:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return None


class Chrome:
    """Headless Chrome with one page target, spoken to over CDP."""

    def __init__(self, binary, profile_dir):
        self.proc = subprocess.Popen(
            [binary, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-first-run", "--no-default-browser-check",
             "--disable-background-networking", "--disable-extensions",
             "--hide-scrollbars", "--mute-audio",
             "--remote-debugging-port=0", f"--user-data-dir={profile_dir}",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.port = self._await_port(profile_dir)
        self.ws = WebSocket(self._page_target())
        self._id = 0

    def _await_port(self, profile_dir, deadline=30.0):
        """Chrome writes the chosen port to DevToolsActivePort once listening."""
        path = os.path.join(profile_dir, "DevToolsActivePort")
        end = time.time() + deadline
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("chrome exited before opening a debug port")
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        port = f.read().split("\n")[0].strip()
                    if port:
                        return int(port)
                except (OSError, ValueError):
                    pass
            time.sleep(0.05)
        raise RuntimeError("timed out waiting for chrome's debug port")

    def _page_target(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/json/list", timeout=15) as r:
            targets = json.load(r)
        for t in targets:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
        raise RuntimeError("chrome exposed no page target")

    def call(self, method, params=None, timeout=60):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(self.ws.recv())
            if msg.get("id") != mid:
                continue                                        # an event; ignore
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# --------------------------------------------------------------------------
# the in-page probe
# --------------------------------------------------------------------------

PROBE_JS = r"""
(async () => {
  const TOL = 1.5;
  // Every wait below is BOUNDED. loading="lazy" images below the fold never
  // load and never fire load/error, so an unbounded Promise.all on them hangs
  // forever; a webfont that 404s can wedge document.fonts.ready the same way.
  const bounded = (p, ms) => Promise.race([p, new Promise(r => setTimeout(r, ms))]);

  if (document.fonts && document.fonts.ready) {
    try { await bounded(document.fonts.ready, 5000); } catch (e) {}
  }
  await bounded(Promise.all([...document.images].filter(i => !i.complete)
    .map(i => new Promise(r => { i.onload = i.onerror = r; }))), 5000);
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

  const de = document.documentElement;
  const vw = de.clientWidth, vh = de.clientHeight;
  const name = e => e.tagName.toLowerCase() +
    (e.id ? '#' + e.id : '') +
    (e.className && typeof e.className === 'string' && e.className.trim()
      ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  const shown = e => {
    const r = e.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return false;
    const c = getComputedStyle(e);
    return c.display !== 'none' && c.visibility !== 'hidden';
  };

  const out = { viewport: { w: vw, h: vh }, failures: {} };

  // 1. horizontal overflow. The element scan runs UNCONDITIONALLY — gating it
  // behind scrollWidth > vw misses everything when a page sets
  // `overflow-x: hidden` on body, which clips the overflow (hiding the symptom)
  // without fixing it.
  // An element that bleeds past the viewport but is CLIPPED by a scoped ancestor
  // (e.g. a decorative ring inside `overflow-x: clip` on the hero) causes no
  // scrolling and no cut-off content — that's intentional bleed, not a bug.
  // body/html are excluded on purpose: clipping there is the global mask that
  // hides real overflow instead of fixing it.
  const contained = e => {
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'hidden' || ox === 'clip' || ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  const wide = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && (r.right > vw + TOL || r.left < -TOL) && !contained(e);
  }).map(e => {
    const r = e.getBoundingClientRect();
    return { el: name(e), left: Math.round(r.left), right: Math.round(r.right),
             width: Math.round(r.width) };
  });
  if (wide.length || de.scrollWidth > vw + TOL) {
    out.failures.overflow = { scrollWidth: de.scrollWidth, clientWidth: vw,
                              elements: wide.slice(0, 15) };
  }

  // 2. hero fold — only meaningful on a page that has a hero section
  const hero = document.querySelector('section[class*="hero" i]');
  if (hero) {
    // A decorative layer deliberately sized past its box (e.g. `inset: -10%`)
    // and clipped by an ancestor's overflow isn't visible past the fold.
    const clippedVertically = e => {
      for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
        const oy = getComputedStyle(p).overflowY;
        if (oy === 'hidden' || oy === 'clip' || oy === 'auto' || oy === 'scroll') return true;
      }
      return false;
    };
    const clipped = [...hero.querySelectorAll('*')].filter(e => {
      if (!shown(e)) return false;
      if (e.closest('[hidden]')) return false;
      if (clippedVertically(e)) return false;
      return e.getBoundingClientRect().bottom > vh + TOL;
    }).map(e => {
      const r = e.getBoundingClientRect();
      return { el: name(e), bottom: Math.round(r.bottom), viewportBottom: vh };
    });
    const hr = hero.getBoundingClientRect();
    if (hr.bottom > vh + TOL) {
      clipped.unshift({ el: name(hero), bottom: Math.round(hr.bottom), viewportBottom: vh });
    }
    if (clipped.length) out.failures.hero_fold = clipped.slice(0, 15);
  }

  // 3/4. images that failed to load, or render at ~0px
  const broken = [], zero = [];
  for (const img of document.images) {
    if (img.complete && img.naturalWidth === 0) broken.push({ el: name(img), src: img.currentSrc || img.src });
    if (!shown(img)) continue;
    const r = img.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) zero.push({ el: name(img), w: r.width, h: r.height });
  }
  if (broken.length) out.failures.broken_images = broken.slice(0, 15);
  if (zero.length) out.failures.zero_size_images = zero.slice(0, 15);

  // 4b. an image told to fill its cell (object-fit: cover/contain) that leaves a
  // vertical gap — e.g. <picture> not carrying a stretched grid row's height, so
  // height:100% resolves against auto and the image sits short of its cell.
  // Only `cover`/`contain` count: `fill` is the CSS initial value and would
  // match every unstyled image on the page.
  const gaps = [];
  for (const img of document.images) {
    if (!shown(img)) continue;
    const fit = getComputedStyle(img).objectFit;
    if (fit !== 'cover' && fit !== 'contain') continue;
    let cell = img.parentElement;
    while (cell && cell.parentElement && cell.parentElement !== document.body) {
      const pd = getComputedStyle(cell.parentElement).display;
      if (pd === 'grid' || pd === 'flex') break;
      cell = cell.parentElement;
    }
    if (!cell) continue;
    const r = img.getBoundingClientRect(), cr = cell.getBoundingClientRect();
    const gap = cr.bottom - r.bottom;
    if (cr.height > 0 && gap > 8) {
      gaps.push({ el: name(img), cell: name(cell), imgH: Math.round(r.height),
                  cellH: Math.round(cr.height), gap: Math.round(gap) });
    }
  }
  if (gaps.length) out.failures.image_gap = gaps.slice(0, 15);

  // 5. above-the-fold element parked at opacity 0 (can't paint until JS runs)
  if (hero) {
    const dark = [...hero.querySelectorAll('*')].filter(e => {
      const c = getComputedStyle(e);
      if (parseFloat(c.opacity) >= 0.01) return false;
      // "has an entrance animation" = a non-zero transition duration or a named
      // animation. Testing the transition *value* for the word "transition"
      // never matches (it reads e.g. "opacity"), which silently disabled this.
      return parseFloat(c.transitionDuration) > 0 || c.animationName !== 'none';
    }).map(name);
    if (dark.length) out.failures.hidden_hero = dark.slice(0, 15);
  }

  return JSON.stringify(out);
})()
"""


# Installed BEFORE any page script runs, so a verification submit never reaches
# FormBackend/Web3Forms and never creates a junk lead.
FETCH_STUB = r"""
window.__verifySubmitted = false;
const __realFetch = window.fetch;
window.fetch = function (url, opts) {
  const u = String(url || '');
  if (/formbackend|web3forms|formspree|api\./i.test(u)) {
    window.__verifySubmitted = true;
    return Promise.resolve(new Response('{"success":true}', {
      status: 200, headers: { 'Content-Type': 'application/json' } }));
  }
  return __realFetch.apply(this, arguments);
};
"""

# Fills the form, submits it, and reports where the user is left afterwards.
SUBMIT_JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const vis = e => {
    const r = e.getBoundingClientRect(), c = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && c.display !== 'none' &&
           c.visibility !== 'hidden' && parseFloat(c.opacity) > 0.01;
  };
  // Wait for load: script.js is deferred, and submitting before its handler is
  // attached triggers a native POST that navigates away and kills this context.
  if (document.readyState !== 'complete') {
    await new Promise(r => window.addEventListener('load', r, { once: true }));
  }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

  const form = document.querySelector('form');
  if (!form) return JSON.stringify({ skipped: 'no form on this page' });

  for (const el of form.querySelectorAll('input, textarea')) {
    if (['hidden', 'checkbox', 'radio', 'submit', 'button'].includes(el.type)) continue;
    el.value = el.type === 'email' ? 'verify@example.com'
             : el.type === 'tel' ? '5555550142'
             : el.tagName === 'TEXTAREA' ? 'Automated build verification — please ignore.'
             : 'Build Verification';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // Reproduce what a real user does: they fill top-to-bottom and tap the submit
  // button, so the button is what they're looking at. Park it near the bottom of
  // the viewport. Testing from scroll 0 hides the entire bug class.
  const btn = form.querySelector('[type="submit"], button');
  if (btn) { btn.scrollIntoView({ block: 'end' }); await sleep(300); }

  const scrollBefore = window.scrollY;
  const heightBefore = document.documentElement.scrollHeight;
  // Where the thing they just tapped sits in the viewport, before submitting.
  const anchorBefore = btn ? btn.getBoundingClientRect().top : null;
  if (form.requestSubmit) form.requestSubmit();
  else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

  // wait for a visible status/confirmation
  let status = null;
  for (let i = 0; i < 60 && !status; i++) {
    await sleep(100);
    status = [...form.querySelectorAll('.form-status, [role="status"], [aria-live]')].find(vis);
  }
  await sleep(400);   // let any scroll settle

  const out = {
    submitted: !!window.__verifySubmitted,
    scrollBefore, scrollAfter: window.scrollY,
    heightBefore, heightAfter: document.documentElement.scrollHeight,
    failures: {},
  };
  if (!status) {
    out.failures.no_confirmation = 'form submitted but no visible status element appeared';
    return JSON.stringify(out);
  }

  const vh = document.documentElement.clientHeight;
  const r = status.getBoundingClientRect();
  out.status = { top: Math.round(r.top), bottom: Math.round(r.bottom), viewportH: vh };

  // THE check: the control the user just tapped must not jump under them.
  // Collapsing the fields shortens the form, yanks the button upward, and fills
  // the screen with whatever was below — the "it teleported me" bug.
  // Movement caused by an INTENTIONAL scroll (scrollIntoView on the
  // confirmation) is fine — that's the fix, not the bug. Subtract it out and
  // judge only the movement the page inflicted on a stationary viewport.
  if (anchorBefore !== null && btn.isConnected) {
    const scrollDelta = window.scrollY - scrollBefore;
    const moved = btn.getBoundingClientRect().top - anchorBefore;
    const reflow = moved + scrollDelta;
    out.anchorShift = Math.round(moved);
    out.scrollDelta = Math.round(scrollDelta);
    out.reflowShift = Math.round(reflow);
  }

  // THE defect: the document changing height on submit. Collapsing the fields
  // shortens the page, so everything below slides up under a stationary
  // viewport and the user is dumped somewhere they didn't ask to be. Where the
  // button ends up doesn't matter once the confirmation is deliberately scrolled
  // into view — the page not moving underneath them does.
  const heightDelta = out.heightAfter - out.heightBefore;
  if (Math.abs(heightDelta) > 100) {
    out.failures.document_collapse = {
      heightDelta,
      note: 'the page changed height on submit, yanking content under the user; '
            + 'freeze the form height (min-height = its rendered height) before '
            + 'hiding the fields, then scrollIntoView the confirmation',
    };
  }

  // the confirmation must actually be on screen after submitting
  if (r.bottom < 0 || r.top > vh) {
    out.failures.confirmation_offscreen = {
      top: Math.round(r.top), viewportH: vh,
      note: 'user was left looking at a different part of the page',
    };
  }

  // ...and not tucked under a sticky/fixed header
  const header = [...document.querySelectorAll('header, nav, .nav')].find(e => {
    const p = getComputedStyle(e).position;
    return (p === 'sticky' || p === 'fixed') && vis(e);
  });
  if (header) {
    const hb = header.getBoundingClientRect().bottom;
    if (r.top < hb - 1 && r.bottom > 0) {
      out.failures.confirmation_under_header = {
        statusTop: Math.round(r.top), headerBottom: Math.round(hb),
        note: 'add scroll-padding-top / scroll-margin-top for the sticky header',
      };
    }
  }
  return JSON.stringify(out);
})()
"""


# Prepares a page to be photographed screen-by-screen. Without this the frames
# are worthless: below-the-fold sections photograph as empty bands (scroll-reveal
# parks them at opacity:0), lazy images photograph as blank boxes, and any
# infinite animation makes no two runs alike.
FILMSTRIP_PREP_JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  if (document.readyState !== 'complete') {
    await new Promise(r => window.addEventListener('load', r, { once: true }));
  }

  // 1. Freeze animation + transition so two runs of the same page match.
  const st = document.createElement('style');
  st.setAttribute('data-verify-filmstrip', '');
  st.textContent = '*,*::before,*::after{animation-play-state:paused !important;' +
                   'animation-delay:-1ms !important;transition:none !important;}';
  document.head.appendChild(st);

  // 2. Lazy images must fetch now or they photograph as blank boxes.
  for (const img of document.images) {
    img.loading = 'eager';
    try { img.decoding = 'sync'; } catch (e) {}
  }

  // 3. Round-trip the scroll to fire every IntersectionObserver and lazy fetch,
  //    then come back to the top. Also settles the height, which grows as
  //    lazy images arrive -- measuring before this gives too few frames.
  const H = () => document.documentElement.scrollHeight;
  const vh = window.innerHeight;
  for (let y = 0; y < H(); y += vh) { window.scrollTo(0, y); await sleep(40); }
  window.scrollTo(0, H()); await sleep(200);
  window.scrollTo(0, 0);   await sleep(120);

  // 4. Un-hide anything still parked at opacity:0 by a reveal system. Detected
  //    by BEHAVIOUR (transition/animation + transparent), not by class name, so
  //    it works no matter what a given build called the class.
  for (const el of document.querySelectorAll('body *')) {
    const c = getComputedStyle(el);
    const animated = c.transitionDuration !== '0s' || c.animationName !== 'none';
    if (animated && parseFloat(c.opacity) < 0.05) {
      el.style.setProperty('opacity', '1', 'important');
      el.style.setProperty('transform', 'none', 'important');
    }
  }

  // 5. Let every image finish decoding so nothing photographs half-painted.
  await Promise.all([...document.images]
    .filter(i => i.src && !i.complete)
    .map(i => new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 3000); })));
  await sleep(150);

  window.scrollTo(0, 0);
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return JSON.stringify({ height: H(), viewportH: window.innerHeight });
})()
"""


def capture_filmstrip(chrome, out_dir, page_name, width, height):
    """Photograph the page one full screen at a time, top to bottom.

    Deliberately NOT a single tall full-page capture: a 10000px page squeezed
    into one image is unreadable, and the whole point is that something can
    actually look at each screen the way a visitor would see it.
    """
    res = chrome.call("Runtime.evaluate", {
        "expression": FILMSTRIP_PREP_JS, "awaitPromise": True, "returnByValue": True,
    }, timeout=120)
    raw = res.get("result", {}).get("value")
    info = json.loads(raw) if raw else {"height": height}
    total = max(int(info.get("height") or height), height)

    # ceil(total / height) without importing math
    frames = max(1, (total + height - 1) // height)
    stem = f"{page_name}-{width}x{height}-"

    # Drop stale frames for this page+viewport so an old longer run can't leave
    # orphans that look like current output.
    try:
        for old in os.listdir(out_dir):
            if old.startswith(stem) and old.endswith(".png"):
                os.remove(os.path.join(out_dir, old))
    except OSError:
        pass

    paths = []
    for i in range(frames):
        y = min(i * height, max(0, total - height))
        chrome.call("Runtime.evaluate", {
            "expression": f"window.scrollTo(0,{y}); 0", "returnByValue": True,
        })
        time.sleep(0.14)
        img = chrome.call("Page.captureScreenshot", {"format": "png"})
        path = os.path.join(out_dir, f"{stem}{i + 1:02d}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(img["data"]))
        paths.append(path)

    return {"viewport": f"{width}x{height}", "page_height": total, "frames": paths}


def check_form_submit(chrome, url, width, height):
    """Submit the page's form with fetch stubbed out, then report where the user
    is left. Returns None when the page has no form."""
    chrome.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 768,
    })
    chrome.call("Page.enable")
    chrome.call("Page.addScriptToEvaluateOnNewDocument", {"source": FETCH_STUB})
    chrome.call("Page.navigate", {"url": url})
    try:
        res = chrome.call("Runtime.evaluate", {
            "expression": SUBMIT_JS, "awaitPromise": True, "returnByValue": True,
        }, timeout=90)
    except RuntimeError as e:
        # The execution context died because the form did a real, native POST
        # instead of an AJAX submit — a genuine defect for these builds, not a
        # harness failure.
        if "navigated" in str(e) or "context" in str(e).lower():
            return {"viewport": {"w": width, "h": height}, "form": True,
                    "failures": {"native_navigation":
                                 "form performed a full-page POST instead of "
                                 "submitting via fetch — the inline confirmation "
                                 "never shows"}}
        raise
    raw = res.get("result", {}).get("value")
    if raw is None:
        raise RuntimeError("form probe returned nothing")
    report = json.loads(raw)
    if report.get("skipped"):
        return None
    report["viewport"] = {"w": width, "h": height}
    return report


def static_checks(public_dir):
    """Cheap markup/CSS invariants that need no layout engine. Returns a dict of
    failures (empty when clean)."""
    fails = {}
    css_path = os.path.join(public_dir, "styles.css")
    if not os.path.exists(css_path):
        return fails
    try:
        css = open(css_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return fails

    import re as _re
    # Strip comments first — otherwise a comment *explaining* that a property was
    # deliberately omitted reads as the property being present.
    css = _re.sub(r"/\*.*?\*/", "", css, flags=_re.S)

    sticky = _re.search(r"position:\s*(sticky|fixed)", css)
    if sticky and "scroll-padding-top" not in css:
        fails["missing_scroll_padding"] = (
            "a sticky/fixed header exists but html has no scroll-padding-top — "
            "anchors and scrollIntoView will land under it"
        )
    if _re.search(r"body\s*\{[^}]*overflow-x:\s*hidden", css, _re.S):
        fails["overflow_x_hidden"] = (
            "body sets overflow-x:hidden — that hides horizontal overflow "
            "instead of fixing it; remove it and fix the real cause"
        )
    if "min-width: 0" not in css and "min-width:0" not in css:
        fails["no_min_width_reset"] = (
            "no `min-width: 0` reset — flex/grid children default to "
            "min-width:auto and refuse to shrink, the top cause of blowouts"
        )
    return fails


def parse_viewport(text):
    try:
        w, h = text.lower().split("x", 1)
        w, h = int(w), int(h)
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError(f"bad viewport {text!r}, expected WIDTHxHEIGHT e.g. 390x844")


def check_page(chrome, url, width, height, shot_path=None,
               filmstrip_dir=None, page_name=None):
    """Load `url` at an exact viewport and return the probe's report."""
    chrome.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height,
        "deviceScaleFactor": 1, "mobile": width < 768,
    })
    chrome.call("Page.enable")
    chrome.call("Page.navigate", {"url": url})
    res = chrome.call("Runtime.evaluate", {
        "expression": PROBE_JS, "awaitPromise": True, "returnByValue": True,
    }, timeout=90)
    raw = res.get("result", {}).get("value")
    if raw is None:
        raise RuntimeError(f"probe returned nothing at {width}x{height}")
    report = json.loads(raw)
    if shot_path:
        img = chrome.call("Page.captureScreenshot", {"format": "png"})
        with open(shot_path, "wb") as f:
            f.write(base64.b64decode(img["data"]))
    # Runs last: the prep mutates the DOM (forces reveals visible, freezes
    # animation), so it must not happen before the probe has measured.
    if filmstrip_dir:
        report["filmstrip"] = capture_filmstrip(
            chrome, filmstrip_dir, page_name, width, height)
    return report


def summarize(reports, static_fails=None):
    """(ok, total_failure_count) across every viewport's report plus statics."""
    n = sum(len(r.get("failures", {})) for r in reports)
    n += len(static_fails or {})
    return n == 0, n


def render(reports):
    """Human-readable lines for the reports."""
    lines = []
    for r in reports:
        vp = r["viewport"]
        fails = r.get("failures", {})
        tag = "OK  " if not fails else "FAIL"
        label = f"{vp['w']}x{vp['h']}" + (" submit" if r.get("form") else "")
        lines.append(f"{tag} {label}"
                     + ("" if not fails else f"  ({', '.join(sorted(fails))})"))
        for kind, detail in sorted(fails.items()):
            items = detail.get("elements", detail) if isinstance(detail, dict) else detail
            for item in (items if isinstance(items, list) else [items])[:6]:
                lines.append(f"       {kind}: {item}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify a built localwebdev site.")
    ap.add_argument("--dir", required=True, help="project dir (contains public/)")
    ap.add_argument("--page", default="index.html", help="page under public/ to check")
    ap.add_argument("--viewport", action="append", metavar="WxH",
                    help=f"repeatable; default {' '.join(DEFAULT_VIEWPORTS)}")
    ap.add_argument("--shot", help="save a PNG of the LAST viewport here")
    ap.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    ap.add_argument("--no-form", action="store_true",
                    help="skip the submit-the-form check")
    ap.add_argument("--no-static", action="store_true",
                    help="skip the static CSS invariant checks")
    ap.add_argument("--no-filmstrip", action="store_true",
                    help="skip the screen-by-screen capture (ON by default)")
    ap.add_argument("--filmstrip-dir", default=None,
                    help="where frames are written (default <dir>/.verify)")
    args = ap.parse_args(argv)

    page = os.path.join(os.path.expanduser(args.dir), "public", args.page)
    if not os.path.exists(page):
        log(f"no such page: {page}")
        return 3
    try:
        viewports = [parse_viewport(v) for v in (args.viewport or DEFAULT_VIEWPORTS)]
    except ValueError as e:
        log(str(e))
        return 3

    binary = find_chrome()
    if not binary:
        log("no Chrome/Chromium found (set CHROME_PATH) — skipping verification.")
        return 4

    url = "file://" + os.path.abspath(page)
    page_name = os.path.splitext(os.path.basename(args.page))[0]

    filmstrip_dir = None
    if not args.no_filmstrip:
        filmstrip_dir = args.filmstrip_dir or os.path.join(
            os.path.expanduser(args.dir), ".verify")
        try:
            os.makedirs(filmstrip_dir, exist_ok=True)
        except OSError as e:
            log(f"cannot write filmstrip to {filmstrip_dir}: {e}")
            filmstrip_dir = None

    reports = []
    with tempfile.TemporaryDirectory(prefix="verify-chrome-") as profile:
        try:
            chrome = Chrome(binary, profile)
        except Exception as e:
            log(f"could not start Chrome: {e}")
            return 4
        try:
            for i, (w, h) in enumerate(viewports):
                last = i == len(viewports) - 1
                reports.append(check_page(
                    chrome, url, w, h,
                    args.shot if (last and args.shot) else None,
                    filmstrip_dir=filmstrip_dir, page_name=page_name))
            if not args.no_form:
                # narrowest viewport — where a post-submit scroll jump actually bites
                w, h = min(viewports, key=lambda v: v[0])
                form_report = check_form_submit(chrome, url, w, h)
                if form_report is not None:
                    form_report["form"] = True
                    reports.append(form_report)
        except Exception as e:
            log(f"verification aborted: {e}")
            return 4
        finally:
            chrome.close()

    static_fails = {} if args.no_static else static_checks(
        os.path.join(os.path.expanduser(args.dir), "public"))

    ok, n = summarize(reports, static_fails)
    if args.json:
        print(json.dumps({"page": args.page, "ok": ok, "static": static_fails,
                          "reports": reports}, indent=1))
    else:
        for line in render(reports):
            print(line, file=sys.stderr)
        for kind, detail in sorted(static_fails.items()):
            print(f"FAIL static  {kind}: {detail}", file=sys.stderr)

    strips = [r["filmstrip"] for r in reports if r.get("filmstrip")]
    if strips and not args.json:
        total = sum(len(s["frames"]) for s in strips)
        print("", file=sys.stderr)
        for s in strips:
            print(f"  {s['viewport']}  ({s['page_height']}px tall, "
                  f"{len(s['frames'])} screens)", file=sys.stderr)
            for p in s["frames"]:
                print(f"    {p}", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"  ^^ READ ALL {total} FRAME(S) ABOVE BEFORE DEPLOYING. The assertions "
              f"cannot judge", file=sys.stderr)
        print("     visual quality -- they pass happily on a hero with no padding, a "
              "section", file=sys.stderr)
        print("     collapsed to a sliver, or text sitting on top of an image. Look at "
              "every", file=sys.stderr)
        print("     screen, fix what looks wrong, re-run.", file=sys.stderr)

    log(f"{args.page}: {'all checks passed' if ok else f'{n} check(s) failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
