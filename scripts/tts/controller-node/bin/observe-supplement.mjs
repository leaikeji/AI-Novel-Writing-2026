#!/usr/bin/env node
import { readSync } from "node:fs";
import { stdin, stdout, stderr } from "node:process";

import { canonicalJson, parseValidationTokenLine } from "../src/contracts.mjs";
import {
  parseCanonicalSupplementRequest,
  SupplementalObserverError,
} from "../src/supplemental-contracts.mjs";
import {
  collectSupplementalObservation,
  holdProjection,
} from "../src/supplemental-observer.mjs";


async function readStdin() {
  const chunks = [];
  let size = 0;
  for await (const chunk of stdin) {
    size += chunk.length;
    if (size > 16 * 1024) throw new SupplementalObserverError("SUPPLEMENT_REQUEST_INVALID");
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
    throw new SupplementalObserverError("SUPPLEMENT_VALIDATION_CAPABILITY_INVALID");
  }
  if (size === buffer.length) {
    throw new SupplementalObserverError("SUPPLEMENT_VALIDATION_CAPABILITY_INVALID");
  }
  return parseValidationTokenLine(buffer.subarray(0, size));
}

async function main() {
  if (process.argv.length !== 2) {
    throw new SupplementalObserverError("SUPPLEMENT_ARGUMENTS_FORBIDDEN");
  }
  if (process.versions.node !== "24.19.0") {
    throw new SupplementalObserverError("SUPPLEMENT_NODE_VERSION_MISMATCH");
  }
  const validationToken = readValidationCapability();
  const request = parseCanonicalSupplementRequest(await readStdin());
  const report = await collectSupplementalObservation(request, validationToken);
  stdout.write(`${canonicalJson(report)}\n`);
}

try {
  await main();
} catch (error) {
  stderr.write(`${canonicalJson(holdProjection(error))}\n`);
  process.exitCode = 78;
}
