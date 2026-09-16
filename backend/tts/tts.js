#!/usr/bin/env node
// FairClip offline TTS bridge — vendored meSpeak (eSpeak port) in Node.
// Usage: node tts.js --text "..." --voice en-us --variant m3 --out /tmp/x.wav
"use strict";
const fs = require("fs");
const path = require("path");

function arg(name) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
}

const vendor = path.join(__dirname, "vendor");
const mespeak = require(path.join(vendor, "src", "index.js"));

const text = arg("text") || "";
const voice = arg("voice") || "en-us";
const variant = arg("variant") || "";
const out = arg("out") || "";
if (!text || !out) {
  console.error("missing --text/--out");
  process.exit(2);
}

let cfgLoaded = false;
try {
  mespeak.loadConfig(require(path.join(vendor, "src", "mespeak_config.json")));
  cfgLoaded = true;
} catch (e) { /* already loaded? */ }

let vpath = path.join(vendor, "voices", "en", voice + ".json");
if (!fs.existsSync(vpath)) vpath = path.join(vendor, "voices", "en", "en-us.json");
mespeak.loadVoice(require(vpath));

const data = mespeak.speak(text, { rawdata: true, variant: variant || undefined });
if (!data) {
  console.error("synthesis failed");
  process.exit(3);
}
fs.writeFileSync(out, Buffer.from(data));
console.log(JSON.stringify({ ok: true, bytes: data.byteLength }));
