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

/** The cassette of the `useCassette` scope a request is sent from. */
export const scopes = new AsyncLocalStorage<Cassette>();

/** Cassettes of the open `useCassette` scopes. */
export const openCassettes = new Set<Cassette>();

/** Whether the interceptor backed by `cassette` handles a request, rather than passing it down. */
export function handles(cassette: Cassette): boolean {
  if (liveRequests.getStore()) return false;
  const scope = scopes.getStore();
  if (scope) return scope === cassette;
  // Code that runs in a context made before the scope, such as a pool or a timer, can only be
  // claimed when no other scope could own it. With no scope open the interceptor was installed by hand.
  return openCassettes.size === 0 || (openCassettes.size === 1 && openCassettes.has(cassette));
}

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
