(() => {
  const ENDPOINT = "https://ingest.getdatbp.com/data";
  const headers = {
    "Content-Type": "application/json",
    "X-Ingest-Key": "local-only-secret"
  };

  const INTERVAL_MS = 1000;
  const MIN_COUNT = 450; // guard so we don't send before full list is rendered

  const itemSelector = 'div[class^="stats-item-"], div[class*=" stats-item-"]';

  let lastSerialized = "";
  let timer = null;
  let busy = false;
  let paused = false;
  let lastSentAt = null;

  // ---------------- helpers ----------------

  const classifyRGB = (rgb) => {
    if (!rgb || rgb === "transparent" || rgb === "rgba(0, 0, 0, 0)") return null;
    const m = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (!m) return null;
    const r = +m[1], g = +m[2], b = +m[3];
    if (g > r + b && g > 80) return "green";
    if (r > g + b && r > 80) return "red";
    if (r < 80 && g < 80 && b < 80) return "black";
    return (r + g + b) / 3 < 60 ? "black" : null;
  };

  const detectColor = (el) => {
    const cls = (el.className || "") + " " + ((el.parentElement && el.parentElement.className) || "");
    const low = cls.toLowerCase();
    if (low.includes("red")) return "red";
    if (low.includes("black")) return "black";
    if (low.includes("green")) return "green";

    for (let n = el, i = 0; n && i < 3; n = n.parentElement, i++) {
      const label = ((n.getAttribute?.("aria-label")) || "") + " " + ((n.getAttribute?.("title")) || "");
      const l = label.toLowerCase();
      if (l.includes("red")) return "red";
      if (l.includes("black")) return "black";
      if (l.includes("green")) return "green";
    }

    for (let n = el, i = 0; n && i < 3; n = n.parentElement, i++) {
      const cs = getComputedStyle(n);
      const bg = classifyRGB(cs.backgroundColor);
      if (bg) return bg;
      const fg = classifyRGB(cs.color);
      if (fg) return fg;
    }

    const txt = el.textContent?.trim();
    if (txt === "0" || txt === "00") return "green";
    return "unknown";
  };

  function collectOnce() {
    let cards = Array.from(document.querySelectorAll(itemSelector));

    // shadow-DOM fallback
    if (cards.length < MIN_COUNT) {
      const seen = new Set();
      const results = [];
      const crawl = (root) => {
        for (const el of root.querySelectorAll(itemSelector)) {
          if (!seen.has(el)) { seen.add(el); results.push(el); }
        }
        for (const host of root.querySelectorAll("*")) {
          if (host.shadowRoot) crawl(host.shadowRoot);
        }
      };
      crawl(document);
      cards = results;
    }

    return cards.map(card => {
      const span = card.querySelector("span");
      const raw = span ? span.textContent.trim() : "";
      if (!raw) return null;

      const num = raw === "00" ? "00" : parseInt(raw, 10);
      if (raw !== "00" && (Number.isNaN(num) || num < 0 || num > 36)) return null;

      return {
        number: raw === "00" ? "00" : num,
        color: detectColor(span || card),
      };
    }).filter(Boolean);
  }

  async function tick() {
    if (paused || busy) return;
    busy = true;

    try {
      const data = collectOnce();
      if (data.length < MIN_COUNT) return;

      const serialized = JSON.stringify(data);
      if (serialized === lastSerialized) return;

      lastSerialized = serialized;
      lastSentAt = new Date().toISOString();

      const r = await fetch(ENDPOINT, {
        method: "POST",
        mode: "cors",
        headers,
        body: JSON.stringify({ data }),
        keepalive: true,
        credentials: "omit",
      });

      const j = await r.json();
      console.log("✅ Sent update:", { count: data.length, at: lastSentAt, server: j });

      window.__last500 = data;
    } catch (e) {
      console.error("❌ Send error:", e);
    } finally {
      busy = false;
    }
  }

  function start() {
    if (timer) clearInterval(timer);
    timer = setInterval(tick, INTERVAL_MS);
    console.log(`⏱️ Scraper started (${INTERVAL_MS} ms interval)`);
  }

  // ---------------- console controls ----------------

  window.__rollsScraper = {
    pause() { paused = true; console.log("⏸️ paused"); },
    resume() { paused = false; console.log("▶️ resumed"); },
    stop() { clearInterval(timer); timer = null; console.log("🛑 stopped"); },
    runNow: tick,
    status() { return { paused, busy, lastSentAt }; }
  };

  // kick off
  start();
})();
