/**
 * Two routes, no router library: "/" uploads, "/songs/{jobId}" plays.
 *
 * Client routes never start with /jobs or /health, which the Vite proxy
 * sends to the api, so a page load is never swallowed by the proxy.
 */
import { useSyncExternalStore, type MouseEvent } from "react";

export type Route = { page: "upload" } | { page: "song"; jobId: string } | { page: "missing" };

const NAVIGATED = "guitarvis:navigate";

export function routeOf(pathname: string): Route {
  if (pathname === "/") return { page: "upload" };
  const match = /^\/songs\/([^/]+)\/?$/.exec(pathname);
  if (match === null) return { page: "missing" };
  try {
    return { page: "song", jobId: decodeURIComponent(match[1]) };
  } catch {
    return { page: "missing" }; // a malformed escape, such as %E0
  }
}

export function songPath(jobId: string): string {
  return `/songs/${encodeURIComponent(jobId)}`;
}

export function navigate(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new Event(NAVIGATED));
}

/** onClick for an <a>: navigate in place, unless the user asked for a new tab. */
export function followLink(event: MouseEvent<HTMLAnchorElement>): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return;
  }
  event.preventDefault();
  navigate(event.currentTarget.getAttribute("href") ?? "/");
}

export function useRoute(): Route {
  return routeOf(useSyncExternalStore(subscribe, () => window.location.pathname));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAVIGATED, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAVIGATED, onChange);
  };
}
