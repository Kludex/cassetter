/**
 * Base interceptor protocol and shared utilities.
 */

import { AsyncLocalStorage } from "node:async_hooks";

import type { Cassette } from "../cassette.js";

export interface Interceptor {
  install(cassette: Cassette): void;
  uninstall(): void;
}

/** Set while an interceptor sends a request live, so one built on another is not recorded twice. */
export const liveRequests = new AsyncLocalStorage<true>();

const LOCALHOST_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "[::1]",
  "::1",
]);

/** Whether a URI points at the local machine. */
export function isLocalhost(uri: string): boolean {
  try {
    const url = new URL(uri);
    return LOCALHOST_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}
