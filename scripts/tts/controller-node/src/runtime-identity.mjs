import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { createRequire } from "node:module";
import { arch, userInfo } from "node:os";
import path from "node:path";

import { ObserverError } from "./contracts.mjs";


const NODE_VERSION = "24.19.0";
const PLAYWRIGHT_VERSION = "1.62.1";
const PLAYWRIGHT_ARCHIVE_SHA512_BASE64 =
  "wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4Hi/rhDMjXGqHewDZ68nYZVw==";
const RUNTIME_RECEIPT_SCHEMA = "moss-tts-t4k-controller-node-runtime-receipt/1.0";
const DEPENDENCY_RECEIPT_SCHEMA = "moss-tts-t4k-controller-node-dependency-receipt/1.0";
const MAX_FILES = 64_000;
const MAX_BYTES = 256 * 1024 * 1024;
const NODE_ARCHIVE_SHA256 = Object.freeze({
  "darwin-arm64": "8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d",
  "darwin-x64": "d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316",
});

function sha256Bytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

function platformKey() {
  if (process.platform !== "darwin") throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  if (arch() === "arm64") return "darwin-arm64";
  if (arch() === "x64") return "darwin-x64";
  throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
}

function fixedPaths() {
  const parent = path.join(
    userInfo().homedir,
    "Library",
    "Application Support",
    "AI小说世界2026",
    "controller-runtime",
  );
  const runtimeRoot = path.join(parent, `node-v${NODE_VERSION}-${platformKey()}`);
  const dependencyRoot = path.join(parent, `observer-dependencies-playwright-core-${PLAYWRIGHT_VERSION}`);
  return Object.freeze({
    dependencyRoot,
    nodeExecutable: path.join(runtimeRoot, "bin", "node"),
    packageRoot: path.join(dependencyRoot, "node_modules", "playwright-core"),
    runtimeRoot,
  });
}

function privateDetails(candidate, kind) {
  let details;
  try {
    details = lstatSync(candidate);
  } catch {
    throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  }
  const isExpected = kind === "directory" ? details.isDirectory() : details.isFile();
  if (
    !isExpected
    || details.isSymbolicLink()
    || details.uid !== process.getuid()
    || (details.mode & 0o077) !== 0
    || (kind === "file" && details.nlink !== 1)
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  return details;
}

function fixedExecutableDetails(candidate) {
  let details;
  try {
    details = lstatSync(candidate);
  } catch {
    throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  }
  if (
    !details.isFile()
    || details.isSymbolicLink()
    || details.uid !== process.getuid()
    || details.nlink !== 1
    || (details.mode & 0o022) !== 0
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  return details;
}

function exactPrivateJson(candidate, keys) {
  privateDetails(candidate, "file");
  let raw;
  let value;
  try {
    raw = readFileSync(candidate, "utf8");
    value = JSON.parse(raw);
  } catch {
    throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  }
  if (
    value === null
    || Array.isArray(value)
    || typeof value !== "object"
    || Object.keys(value).sort().join("\0") !== [...keys].sort().join("\0")
    || raw !== `${canonicalJson(value)}\n`
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  return value;
}

function packageTreeSha256(packageRoot) {
  const digest = createHash("sha256");
  let count = 0;
  let total = 0;
  function visit(directory, relativeParent = "") {
    const rows = readdirSync(directory, { withFileTypes: true })
      // Match Python's deterministic Unicode/code-point ordering used by the
      // offline receipt builder. Locale collation reorders punctuation and
      // makes the same immutable tree hash differently across runtimes.
      .sort((left, right) => (
        left.name < right.name ? -1 : left.name > right.name ? 1 : 0
      ));
    for (const row of rows) {
      count += 1;
      if (count > MAX_FILES) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
      const relative = relativeParent ? `${relativeParent}/${row.name}` : row.name;
      const candidate = path.join(directory, row.name);
      const details = lstatSync(candidate);
      const mode = details.mode & 0o777;
      if (details.isSymbolicLink() || details.uid !== process.getuid() || (mode & 0o077) !== 0) {
        throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
      }
      if (details.isDirectory()) {
        digest.update(`D\0${relative}\0${mode.toString(8)}\n`, "utf8");
        visit(candidate, relative);
      } else if (details.isFile() && details.nlink === 1) {
        total += details.size;
        if (total > MAX_BYTES) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
        digest.update(
          `F\0${relative}\0${mode.toString(8)}\0${details.size}\0${sha256Bytes(readFileSync(candidate))}\n`,
          "utf8",
        );
      } else {
        throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
      }
    }
  }
  privateDetails(packageRoot, "directory");
  visit(packageRoot);
  return digest.digest("hex");
}

export function loadFixedChromium() {
  const fixed = fixedPaths();
  privateDetails(fixed.runtimeRoot, "directory");
  fixedExecutableDetails(fixed.nodeExecutable);
  if (
    process.versions.node !== NODE_VERSION
    || process.execPath !== fixed.nodeExecutable
    || realpathSync(process.execPath) !== fixed.nodeExecutable
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  const runtimeReceipt = exactPrivateJson(
    path.join(fixed.runtimeRoot, ".controller-runtime-receipt.json"),
    new Set([
      "node_executable_sha256",
      "node_version",
      "platform",
      "schema_version",
      "source_archive_sha256",
    ]),
  );
  if (
    runtimeReceipt.schema_version !== RUNTIME_RECEIPT_SCHEMA
    || runtimeReceipt.node_version !== NODE_VERSION
    || runtimeReceipt.platform !== platformKey()
    || runtimeReceipt.node_executable_sha256 !== sha256Bytes(readFileSync(fixed.nodeExecutable))
    || runtimeReceipt.source_archive_sha256 !== NODE_ARCHIVE_SHA256[platformKey()]
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");

  privateDetails(fixed.dependencyRoot, "directory");
  privateDetails(path.join(fixed.dependencyRoot, "node_modules"), "directory");
  if (
    realpathSync(fixed.dependencyRoot) !== fixed.dependencyRoot
    || realpathSync(fixed.packageRoot) !== fixed.packageRoot
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  const dependencyReceipt = exactPrivateJson(
    path.join(fixed.dependencyRoot, ".controller-dependency-receipt.json"),
    new Set([
      "package_name",
      "package_tree_sha256",
      "package_version",
      "schema_version",
      "source_archive_sha512_base64",
    ]),
  );
  let packageMetadata;
  try {
    packageMetadata = JSON.parse(readFileSync(path.join(fixed.packageRoot, "package.json"), "utf8"));
  } catch {
    throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  }
  const treeSha = packageTreeSha256(fixed.packageRoot);
  if (
    dependencyReceipt.schema_version !== DEPENDENCY_RECEIPT_SCHEMA
    || dependencyReceipt.package_name !== "playwright-core"
    || dependencyReceipt.package_version !== PLAYWRIGHT_VERSION
    || dependencyReceipt.source_archive_sha512_base64 !== PLAYWRIGHT_ARCHIVE_SHA512_BASE64
    || dependencyReceipt.package_tree_sha256 !== treeSha
    || packageMetadata.name !== "playwright-core"
    || packageMetadata.version !== PLAYWRIGHT_VERSION
  ) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");

  try {
    const fixedRequire = createRequire(path.join(fixed.dependencyRoot, "controller-loader.cjs"));
    const loaded = fixedRequire(fixed.packageRoot);
    if (!loaded?.chromium) throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
    return loaded.chromium;
  } catch (error) {
    if (error instanceof ObserverError) throw error;
    throw new ObserverError("OBSERVER_RUNTIME_IDENTITY_INVALID");
  }
}
