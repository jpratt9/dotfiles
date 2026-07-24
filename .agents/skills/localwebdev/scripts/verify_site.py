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
  if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
  await Promise.all([...document.images].filter(i => !i.complete)
    .map(i => new Promise(r => { i.onload = i.onerror = r; })));
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

  // 1. horizontal overflow
  if (de.scrollWidth > vw + TOL) {
    const wide = [...document.querySelectorAll('body *')].filter(e => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > vw + TOL || r.left < -TOL);
    }).map(e => {
      const r = e.getBoundingClientRect();
      return { el: name(e), left: Math.round(r.left), right: Math.round(r.right),
               width: Math.round(r.width) };
    });
    out.failures.overflow = { scrollWidth: de.scrollWidth, clientWidth: vw,
                              elements: wide.slice(0, 15) };
  }

  // 2. hero fold — only meaningful on a page that has a hero section
  const hero = document.querySelector('section[class*="hero" i]');
  if (hero) {
    const clipped = [...hero.querySelectorAll('*')].filter(e => {
      if (!shown(e)) return false;
      if (e.closest('[hidden]')) return false;
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

  // 5. above-the-fold element parked at opacity 0 (can't paint until JS runs)
  if (hero) {
    const dark = [...hero.querySelectorAll('*')].filter(e => {
      const c = getComputedStyle(e);
      return parseFloat(c.opacity) < 0.01 && /transition|animation/.test(
        c.transitionProperty + c.animationName);
    }).map(name);
    if (dark.length) out.failures.hidden_hero = dark.slice(0, 15);
  }

  return JSON.stringify(out);
})()
"""


def parse_viewport(text):
    try:
        w, h = text.lower().split("x", 1)
        w, h = int(w), int(h)
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError(f"bad viewport {text!r}, expected WIDTHxHEIGHT e.g. 390x844")


def check_page(chrome, url, width, height, shot_path=None):
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
    return report


def summarize(reports):
    """(ok, total_failure_count) across every viewport's report."""
    n = sum(len(r.get("failures", {})) for r in reports)
    return n == 0, n


def render(reports):
    """Human-readable lines for the reports."""
    lines = []
    for r in reports:
        vp = r["viewport"]
        fails = r.get("failures", {})
        tag = "OK  " if not fails else "FAIL"
        lines.append(f"{tag} {vp['w']}x{vp['h']}"
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
                reports.append(check_page(chrome, url, w, h,
                                          args.shot if (last and args.shot) else None))
        except Exception as e:
            log(f"verification aborted: {e}")
            return 4
        finally:
            chrome.close()

    ok, n = summarize(reports)
    if args.json:
        print(json.dumps({"page": args.page, "ok": ok, "reports": reports}, indent=1))
    else:
        for line in render(reports):
            print(line, file=sys.stderr)
    log(f"{args.page}: {'all checks passed' if ok else f'{n} check(s) failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
