import { defineConfig } from "vite";


function compactInlineCss(value: string): string {
  let output = "";
  let quote: "\"" | "'" | undefined;
  let escaped = false;
  let pendingSpace = false;
  const tight = "{}:;,>()[]";

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    const next = value[index + 1];
    if (quote) {
      output += character;
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = undefined;
      continue;
    }
    if (character === "\"" || character === "'") {
      if (pendingSpace && output && !tight.includes(output.charAt(output.length - 1))) output += " ";
      pendingSpace = false;
      quote = character;
      output += character;
      continue;
    }
    if (character === "/" && next === "*") {
      const end = value.indexOf("*/", index + 2);
      index = end < 0 ? value.length : end + 1;
      pendingSpace = true;
      continue;
    }
    if (/\s/.test(character)) {
      pendingSpace = true;
      continue;
    }
    if (tight.includes(character) && output.endsWith(" ")) output = output.slice(0, -1);
    if (
      pendingSpace
      && output
      && !tight.includes(character)
      && !tight.includes(output.charAt(output.length - 1))
    ) output += " ";
    pendingSpace = false;
    output += character;
  }
  return output.trim();
}


const SOURCE_MAP_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";


function encodeSourceMapInteger(value: number): string {
  let encoded = "";
  let remaining = value < 0 ? ((-value) << 1) + 1 : value << 1;
  do {
    let digit = remaining & 31;
    remaining >>>= 5;
    if (remaining > 0) digit |= 32;
    encoded += SOURCE_MAP_BASE64[digit];
  } while (remaining > 0);
  return encoded;
}


function compactStyleSourceMap(
  source: string,
  id: string,
  generated: string,
  cssLine: number,
  cssEndLine: number,
) {
  let previousOriginalLine = 0;
  const mappings = generated.split("\n").map((_line, generatedLine) => {
    const originalLine = generatedLine <= cssLine
      ? generatedLine
      : cssEndLine + generatedLine - cssLine;
    const segment = `AA${encodeSourceMapInteger(originalLine - previousOriginalLine)}A`;
    previousOriginalLine = originalLine;
    return segment;
  }).join(";");
  return {
    version: 3,
    file: id,
    names: [] as string[],
    sources: [id],
    sourcesContent: [source],
    mappings,
  };
}


function compactNovelStyleLiteral() {
  return {
    name: "compact-novel-style-literal",
    enforce: "pre" as const,
    transform(code: string, id: string) {
      if (!id.endsWith("/frontend/src/styles.ts")) return null;
      const marker = "style.textContent = `";
      const start = code.indexOf(marker);
      const end = start < 0 ? -1 : code.indexOf("`;", start + marker.length);
      if (start < 0 || end < 0) throw new Error("novel style literal was not found");
      const cssStart = start + marker.length;
      const generated = `${code.slice(0, cssStart)}${compactInlineCss(code.slice(cssStart, end))}${code.slice(end)}`;
      const cssLine = code.slice(0, cssStart).split("\n").length - 1;
      const cssEndLine = code.slice(0, end).split("\n").length - 1;
      return {
        code: generated,
        map: compactStyleSourceMap(code, id, generated, cssLine, cssEndLine),
      };
    },
  };
}

export default defineConfig({
  plugins: [compactNovelStyleLiteral()],
  build: {
    // QwenPaw 2.1 runs PawApps in its current Chromium shell. Keeping the
    // generated module at that public runtime boundary avoids legacy syntax
    // transforms and keeps the single-file plugin within the frozen gzip gate.
    target: "esnext",
    lib: {
      entry: "frontend/src/index.ts",
      formats: ["es"],
      fileName: () => "index.js",
    },
    outDir: "frontend/dist",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      // QwenPaw evaluates PawApp frontends from a Blob URL. Relative chunk
      // specifiers cannot be resolved from that origin, so every dynamic
      // import must be inlined into the single distributable module.
      output: { compact: true, inlineDynamicImports: true },
    },
  },
});
