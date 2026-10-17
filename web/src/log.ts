/**
 * The client's one way to record an error the user cannot see, such as a
 * view that failed while the rest of the page carried on. Every such error
 * goes through here, so the console names them all the same way.
 */

/** `where` says what failed, in a few words: "the guitar failed". */
export function logError(where: string, error: unknown): void {
  console.error(`[guitarvis] ${where}`, error);
}
