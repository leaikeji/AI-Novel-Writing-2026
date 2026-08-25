const moduleUrl = new URL(
  "../../../../../frontend/src/selection-edit-review.ts",
  import.meta.url,
);
const { rebuildSelectionEditTexts } = await import(moduleUrl.href);

const segments = [];
const baseParts = [];
const candidateParts = [];
for (let index = 0; index < 2_000; index += 1) {
  const equal = "甲乙丙";
  const original = "旧句。";
  const replacement = "新句！";
  segments.push({
    segment_id: `equal-${index}`,
    kind: "equal",
    text: equal,
  });
  segments.push({
    segment_id: `replace-${index}`,
    kind: "replace",
    original_text: original,
    replacement_text: replacement,
  });
  baseParts.push(equal, original);
  candidateParts.push(equal, replacement);
}

const base = baseParts.join("");
const candidate = candidateParts.join("");
for (let index = 0; index < 50; index += 1) {
  rebuildSelectionEditTexts(segments);
}

const samples = [];
for (let index = 0; index < 500; index += 1) {
  const startedAt = performance.now();
  const rebuilt = rebuildSelectionEditTexts(segments);
  const elapsed = performance.now() - startedAt;
  if (rebuilt.baseText !== base || rebuilt.candidateText !== candidate) {
    throw new Error("12k reconstruction mismatch");
  }
  samples.push(elapsed);
}
samples.sort((left, right) => left - right);

const percentile = (fraction) => samples[
  Math.min(samples.length - 1, Math.ceil(samples.length * fraction) - 1)
];
const report = {
  probe: "selection-edit 12k bidirectional reconstruction",
  runtime: `node ${process.version}`,
  samples: samples.length,
  segments: segments.length,
  base_characters: Array.from(base).length,
  candidate_characters: Array.from(candidate).length,
  reconstructed_base: true,
  reconstructed_candidate: true,
  p50_ms: Number(percentile(0.50).toFixed(4)),
  p95_ms: Number(percentile(0.95).toFixed(4)),
  max_ms: Number(samples[samples.length - 1].toFixed(4)),
  gate_ms: 100,
  passed: percentile(0.95) < 100,
};

console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
