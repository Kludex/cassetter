/**
 * Base interceptor protocol and shared utilities.
 */

import type { Cassette } from "../cassette.js";

export interface Interceptor {
  install(cassette: Cassette): void;
  uninstall(): void;
}

const LOCALHOST_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "[::1]",
  "::1",
]);

export function isLocalhost(uri: string): boolean {
  try {
    const url = new URL(uri);
    return LOCALHOST_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}
