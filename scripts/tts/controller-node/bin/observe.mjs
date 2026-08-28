#!/usr/bin/env node
import { readSync } from "node:fs";
import { stdin, stdout } from "node:process";

import {
  canonicalJson,
  ObserverError,
  parseCanonicalRequest,
  parseValidationTokenLine,
} from "../src/contracts.mjs";
import { collectFixedObservation } from "../src/observer.mjs";


async function readStdin() {
  const chunks = [];
  let size = 0;
  for await (const chunk of stdin) {
    size += chunk.length;
    if (size > 16 * 1024) throw new ObserverError("OBSERVER_REQUEST_INVALID");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function readValidationCapability() {
  const buffer = Buffer.alloc(130);
  let size = 0;
  try {
    while (size < buffer.length) {
      const count = readSync(3, buffer, size, buffer.length - size, null);
      if (count === 0) break;
      size += count;
    }
  } catch {
    throw new ObserverError("OBSERVER_VALIDATION_CAPABILITY_INVALID");
  }
  if (size === buffer.length) {
    throw new ObserverError("OBSERVER_VALIDATION_CAPABILITY_INVALID");
  }
  return parseValidationTokenLine(buffer.subarray(0, size));
}

async function main() {
  if (process.argv.length !== 2) throw new ObserverError("OBSERVER_ARGUMENTS_FORBIDDEN");
  if (process.versions.node !== "24.19.0") throw new ObserverError("OBSERVER_NODE_VERSION_MISMATCH");
  const validationToken = readValidationCapability();
  const request = parseCanonicalRequest(await readStdin());
  const report = await collectFixedObservation(request, validationToken);
  stdout.write(`${canonicalJson(report)}\n`);
}

try {
  await main();
} catch (error) {
  const code = error instanceof ObserverError ? error.code : "OBSERVER_FAILED";
  process.stderr.write(`${canonicalJson({ error_code: code, status: "hold" })}\n`);
  process.exitCode = 78;
}
