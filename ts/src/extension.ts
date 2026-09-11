import { extname } from "node:path";

const CASSETTE_EXTENSIONS = ["toml", "yaml", "yml"] as const;

/** Canonical cassette suffix: `yaml`, `yml`, or `toml`. */
export function normalizeCassetteExtension(value: string): string {
  const extension = value.replace(/^\./, "").toLowerCase();
  if ((CASSETTE_EXTENSIONS as readonly string[]).includes(extension)) {
    return extension;
  }
  throw new Error(
    `cassette_extension must be one of ${CASSETTE_EXTENSIONS.join(", ")}, got '${value}'`,
  );
}

/** Append `extension` when `path` is not already a cassette file. */
export function applyCassetteExtension(path: string, extension: string): string {
  const existing = extname(path).replace(/^\./, "").toLowerCase();
  if ((CASSETTE_EXTENSIONS as readonly string[]).includes(existing)) {
    return path;
  }
  return `${path}.${extension}`;
}
