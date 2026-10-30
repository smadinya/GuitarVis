/**
 * What the link field says before anything is sent (spec 012). The client
 * checks only that the text is a web address. Which sites work is the api's
 * call, so there is no list here to drift from it.
 */
export const BLANK_HINT = "Paste a link first.";
export const NOT_A_LINK_HINT = "That doesn't look like a link.";
/** The api's limit (spec 012; `guitarvis_fetch.links.MAX_LINK_CHARS`). Past
 * it, the api answers in words meant for developers. */
export const MAX_LINK_CHARS = 2048;

/** A hint for the user, or null when the text may be sent. */
export function linkHint(raw: string): string | null {
  const text = raw.trim();
  if (text === "") return BLANK_HINT;
  if (text.length > MAX_LINK_CHARS || /\s/.test(text)) return NOT_A_LINK_HINT;
  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return NOT_A_LINK_HINT;
  }
  const web = url.protocol === "http:" || url.protocol === "https:";
  return web && url.hostname.includes(".") ? null : NOT_A_LINK_HINT;
}
