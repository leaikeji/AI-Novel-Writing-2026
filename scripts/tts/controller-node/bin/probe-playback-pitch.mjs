#!/usr/bin/env node
import { stderr, stdout } from "node:process";

import { canonicalJson, EDGE_PATH } from "../src/contracts.mjs";
import { collectPlaybackPitchProbe } from "../src/playback-pitch-probe.mjs";
import { loadFixedChromium } from "../src/runtime-identity.mjs";


async function main() {
  if (process.argv.length !== 2) throw new Error("PITCH_PROBE_ARGUMENTS_FORBIDDEN");
  const report = await collectPlaybackPitchProbe({
    chromium: loadFixedChromium(),
    executablePath: EDGE_PATH,
  });
  stdout.write(`${canonicalJson(report)}\n`);
  if (report.status !== "pass") process.exitCode = 78;
}


try {
  await main();
} catch {
  stderr.write(`${canonicalJson({ error_code: "PITCH_PROBE_FAILED", status: "hold" })}\n`);
  process.exitCode = 78;
}
