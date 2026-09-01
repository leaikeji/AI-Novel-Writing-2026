import assert from "node:assert/strict";
import test from "node:test";

import {
  EXPOSED_PLAYBACK_RATES,
  NEGATIVE_CONTROL_RATES,
  PROBE_FREQUENCIES_HZ,
  assessPitchProbeSamples,
  dominantFrequencyFromBins,
  relativeError,
} from "../src/playback-pitch-probe.mjs";


function passingSamples() {
  const samples = [];
  for (const frequency of PROBE_FREQUENCIES_HZ) {
    for (const rate of NEGATIVE_CONTROL_RATES) {
      samples.push({
        dominant_frequency_hz: frequency * rate,
        error_count: 0,
        expected_wall_duration_ms: 1_500 / rate,
        frequency_hz: frequency,
        preserves_pitch: false,
        preserves_pitch_property: false,
        rate,
        stalled_count: 0,
        waiting_count: 0,
        wall_duration_ms: 1_500 / rate,
      });
    }
    for (const rate of EXPOSED_PLAYBACK_RATES) {
      samples.push({
        dominant_frequency_hz: frequency,
        error_count: 0,
        expected_wall_duration_ms: 1_500 / rate,
        frequency_hz: frequency,
        preserves_pitch: true,
        preserves_pitch_property: true,
        rate,
        stalled_count: 0,
        waiting_count: 0,
        wall_duration_ms: 1_500 / rate,
      });
    }
  }
  return samples;
}


test("dominant frequency uses the FFT bin width", () => {
  const bins = [-120, -80, -40, -2, -30];
  assert.equal(dominantFrequencyFromBins(bins, 48_000, 48_000), 3);
  assert.equal(relativeError(103, 100), 0.03);
});


test("the exact positive and negative matrix passes all objective gates", () => {
  assert.deepEqual(assessPitchProbeSamples(passingSamples()), {
    status: "pass",
    failure_codes: [],
  });
});


test("missing samples, pitch drift and ineffective negative controls fail closed", () => {
  assert.deepEqual(assessPitchProbeSamples([]).failure_codes, [
    "PITCH_PROBE_SAMPLE_MATRIX_INCOMPLETE",
  ]);
  const samples = passingSamples();
  const drifting = samples.find((sample) => sample.frequency_hz === 220 && sample.rate === 2 && sample.preserves_pitch);
  drifting.dominant_frequency_hz = 330;
  const negative = samples.find((sample) => sample.frequency_hz === 440 && sample.rate === 1.5 && !sample.preserves_pitch);
  negative.dominant_frequency_hz = 440;
  const result = assessPitchProbeSamples(samples, { errors: 1, warnings: 1 });
  assert.equal(result.status, "hold");
  assert.deepEqual(result.failure_codes, [
    "BROWSER_CONSOLE_ERROR",
    "BROWSER_CONSOLE_WARNING",
    "NEGATIVE_CONTROL_DID_NOT_DETECT_PITCH_SHIFT",
    "PITCH_PRESERVATION_OUT_OF_RANGE",
  ]);
});
