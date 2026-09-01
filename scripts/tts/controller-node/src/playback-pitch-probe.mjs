export const PLAYBACK_PITCH_PROBE_SCHEMA = "moss-tts-playback-pitch-probe/1.0";

export const EXPOSED_PLAYBACK_RATES = Object.freeze([
  0.5,
  0.75,
  1,
  1.25,
  1.5,
  1.75,
  2,
  2.25,
  2.5,
  2.75,
  3,
]);

export const PROBE_FREQUENCIES_HZ = Object.freeze([220, 440]);
export const NEGATIVE_CONTROL_RATES = Object.freeze([1.5, 2]);


function finitePositive(value, name) {
  if (!Number.isFinite(value) || value <= 0) throw new TypeError(`${name} must be positive`);
  return value;
}


export function relativeError(actual, expected) {
  return Math.abs(finitePositive(actual, "actual") - finitePositive(expected, "expected")) / expected;
}


export function dominantFrequencyFromBins(bins, sampleRate, fftSize) {
  if (!Array.isArray(bins) || bins.length < 2) throw new TypeError("bins must contain frequency magnitudes");
  finitePositive(sampleRate, "sampleRate");
  finitePositive(fftSize, "fftSize");
  let peakIndex = 1;
  for (let index = 2; index < bins.length; index += 1) {
    if (Number.isFinite(bins[index]) && bins[index] > bins[peakIndex]) peakIndex = index;
  }
  return peakIndex * sampleRate / fftSize;
}


function sampleKey(sample) {
  return `${sample.frequency_hz}:${sample.rate}:${sample.preserves_pitch ? "on" : "off"}`;
}


function exactSampleSet(samples) {
  const expected = new Set();
  for (const frequency of PROBE_FREQUENCIES_HZ) {
    for (const rate of EXPOSED_PLAYBACK_RATES) expected.add(`${frequency}:${rate}:on`);
    for (const rate of NEGATIVE_CONTROL_RATES) expected.add(`${frequency}:${rate}:off`);
  }
  const actual = new Set(samples.map(sampleKey));
  return samples.length === expected.size
    && expected.size === actual.size
    && [...expected].every((key) => actual.has(key));
}


function metricWithin(actual, expected, tolerance) {
  return Number.isFinite(actual)
    && Number.isFinite(expected)
    && actual > 0
    && expected > 0
    && relativeError(actual, expected) <= tolerance;
}


export function assessPitchProbeSamples(samples, consoleCounts = { errors: 0, warnings: 0 }) {
  if (!Array.isArray(samples) || !exactSampleSet(samples)) {
    return Object.freeze({
      status: "hold",
      failure_codes: Object.freeze(["PITCH_PROBE_SAMPLE_MATRIX_INCOMPLETE"]),
    });
  }

  const failures = new Set();
  const byKey = new Map(samples.map((sample) => [sampleKey(sample), sample]));
  for (const frequency of PROBE_FREQUENCIES_HZ) {
    const baseline = byKey.get(`${frequency}:1:on`);
    if (!baseline || !Number.isFinite(baseline.dominant_frequency_hz)) {
      failures.add("PITCH_PROBE_BASELINE_INVALID");
      continue;
    }
    for (const rate of EXPOSED_PLAYBACK_RATES) {
      const sample = byKey.get(`${frequency}:${rate}:on`);
      if (
        !sample
        || sample.preserves_pitch_property !== true
        || !metricWithin(sample.dominant_frequency_hz, baseline.dominant_frequency_hz, 0.03)
      ) failures.add("PITCH_PRESERVATION_OUT_OF_RANGE");
      if (!sample || !metricWithin(sample.wall_duration_ms, sample.expected_wall_duration_ms, 0.10)) {
        failures.add("PLAYBACK_DURATION_OUT_OF_RANGE");
      }
      if (!sample || sample.waiting_count !== 0 || sample.stalled_count !== 0 || sample.error_count !== 0) {
        failures.add("PLAYBACK_EVENT_FAILURE");
      }
    }
    for (const rate of NEGATIVE_CONTROL_RATES) {
      const negative = byKey.get(`${frequency}:${rate}:off`);
      const positive = byKey.get(`${frequency}:${rate}:on`);
      const expectedShift = baseline.dominant_frequency_hz * rate;
      if (
        !negative
        || negative.preserves_pitch_property !== false
        || !metricWithin(negative.dominant_frequency_hz, expectedShift, 0.12)
        || !positive
        || Math.abs(negative.dominant_frequency_hz - positive.dominant_frequency_hz)
          / baseline.dominant_frequency_hz < 0.20
      ) failures.add("NEGATIVE_CONTROL_DID_NOT_DETECT_PITCH_SHIFT");
      if (!negative || !metricWithin(negative.wall_duration_ms, negative.expected_wall_duration_ms, 0.10)) {
        failures.add("PLAYBACK_DURATION_OUT_OF_RANGE");
      }
    }
  }
  if (consoleCounts.errors !== 0) failures.add("BROWSER_CONSOLE_ERROR");
  if (consoleCounts.warnings !== 0) failures.add("BROWSER_CONSOLE_WARNING");
  return Object.freeze({
    status: failures.size === 0 ? "pass" : "hold",
    failure_codes: Object.freeze([...failures].sort()),
  });
}


async function collectOneSample(page, input) {
  return page.evaluate(async ({ frequencyHz, rate, preservesPitch }) => {
    const sampleRate = 48_000;
    const durationSeconds = 3;
    const sampleCount = Math.round(sampleRate * durationSeconds);
    const buffer = new ArrayBuffer(44 + sampleCount * 2);
    const view = new DataView(buffer);
    const writeAscii = (offset, text) => {
      for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
    };
    writeAscii(0, "RIFF");
    view.setUint32(4, 36 + sampleCount * 2, true);
    writeAscii(8, "WAVE");
    writeAscii(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(36, "data");
    view.setUint32(40, sampleCount * 2, true);
    for (let index = 0; index < sampleCount; index += 1) {
      const fade = Math.min(1, index / 480, (sampleCount - index - 1) / 480);
      const value = Math.sin(2 * Math.PI * frequencyHz * index / sampleRate) * 0.45 * fade;
      view.setInt16(44 + index * 2, Math.round(value * 32_767), true);
    }

    const objectUrl = URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
    const audio = document.createElement("audio");
    if (!("preservesPitch" in audio)) throw new Error("PRESERVES_PITCH_UNAVAILABLE");
    audio.preload = "auto";
    audio.src = objectUrl;
    const counts = { error: 0, stalled: 0, waiting: 0 };
    await new Promise((resolve, reject) => {
      const onReady = () => {
        cleanup();
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new Error("AUDIO_METADATA_FAILED"));
      };
      const cleanup = () => {
        audio.removeEventListener("canplaythrough", onReady);
        audio.removeEventListener("error", onError);
      };
      audio.addEventListener("canplaythrough", onReady, { once: true });
      audio.addEventListener("error", onError, { once: true });
      audio.load();
    });
    // load() resets the media playback state. Apply both values after the
    // asset is ready, matching the product driver's pre-play ordering.
    audio.preservesPitch = preservesPitch;
    audio.playbackRate = rate;
    audio.addEventListener("waiting", () => { counts.waiting += 1; });
    audio.addEventListener("stalled", () => { counts.stalled += 1; });
    audio.addEventListener("error", () => { counts.error += 1; });

    const context = new AudioContext({ sampleRate });
    const analyser = context.createAnalyser();
    analyser.fftSize = 32_768;
    analyser.smoothingTimeConstant = 0;
    const source = context.createMediaElementSource(audio);
    source.connect(analyser);
    analyser.connect(context.destination);
    const bins = new Float32Array(analyser.frequencyBinCount);
    const peaks = [];
    const playingAt = new Promise((resolve) => {
      audio.addEventListener("playing", () => resolve(performance.now()), { once: true });
    });
    const endedAt = new Promise((resolve) => {
      audio.addEventListener("ended", () => resolve(performance.now()), { once: true });
    });
    await context.resume();
    const playPromise = audio.play();
    const startedAt = await playingAt;
    await playPromise;
    const sampler = setInterval(() => {
      if (audio.currentTime < 0.12 || audio.currentTime > durationSeconds - 0.12) return;
      analyser.getFloatFrequencyData(bins);
      let peakIndex = 1;
      for (let index = 2; index < bins.length; index += 1) {
        if (bins[index] > bins[peakIndex]) peakIndex = index;
      }
      peaks.push(peakIndex * context.sampleRate / analyser.fftSize);
    }, 25);
    const finishedAt = await Promise.race([
      endedAt,
      new Promise((_, reject) => setTimeout(() => reject(new Error("AUDIO_PROBE_TIMEOUT")), 14_000)),
    ]);
    clearInterval(sampler);
    const wallDurationMs = finishedAt - startedAt;
    audio.pause();
    source.disconnect();
    analyser.disconnect();
    await context.close();
    URL.revokeObjectURL(objectUrl);
    if (peaks.length === 0) throw new Error("AUDIO_PROBE_NO_SPECTRUM");
    peaks.sort((left, right) => left - right);
    const dominantFrequencyHz = peaks[Math.floor(peaks.length / 2)];
    return {
      dominant_frequency_hz: dominantFrequencyHz,
      error_count: counts.error,
      expected_wall_duration_ms: durationSeconds * 1_000 / rate,
      frequency_hz: frequencyHz,
      preserves_pitch: preservesPitch,
      preserves_pitch_property: audio.preservesPitch,
      rate,
      stalled_count: counts.stalled,
      waiting_count: counts.waiting,
      wall_duration_ms: wallDurationMs,
    };
  }, input);
}


export async function collectPlaybackPitchProbe({ chromium, executablePath }) {
  if (!chromium?.launch || typeof executablePath !== "string" || executablePath.length === 0) {
    throw new TypeError("fixed chromium and executable path are required");
  }
  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--autoplay-policy=no-user-gesture-required"],
  });
  const consoleCounts = { errors: 0, warnings: 0 };
  try {
    const page = await browser.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleCounts.errors += 1;
      if (message.type() === "warning") consoleCounts.warnings += 1;
    });
    const samples = [];
    for (const frequencyHz of PROBE_FREQUENCIES_HZ) {
      for (const rate of NEGATIVE_CONTROL_RATES) {
        samples.push(await collectOneSample(page, { frequencyHz, rate, preservesPitch: false }));
      }
      for (const rate of EXPOSED_PLAYBACK_RATES) {
        samples.push(await collectOneSample(page, { frequencyHz, rate, preservesPitch: true }));
      }
    }
    const assessment = assessPitchProbeSamples(samples, consoleCounts);
    return Object.freeze({
      browser_version: browser.version(),
      console_counts: Object.freeze({ ...consoleCounts }),
      failure_codes: assessment.failure_codes,
      generated_at: new Date().toISOString(),
      samples: Object.freeze(samples.map((sample) => Object.freeze(sample))),
      schema_version: PLAYBACK_PITCH_PROBE_SCHEMA,
      status: assessment.status,
    });
  } finally {
    await browser.close();
  }
}
