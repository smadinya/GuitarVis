/** An XMLHttpRequest for tests: records the request, answers when told. */
export class FakeXhr {
  static last: FakeXhr | null = null;

  method = "";
  url = "";
  readonly headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = "";
  readonly upload: {
    onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: unknown): void {
    this.body = body;
  }

  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  respond(status: number, body: unknown): void {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.onload?.();
  }

  fail(): void {
    this.onerror?.();
  }

  aborted = false;

  /** As a browser does: the request stops, and onabort fires. */
  abort(): void {
    this.aborted = true;
    this.onabort?.();
  }
}

/** The FakeXhr the code under test created, which must exist. */
export function lastXhr(): FakeXhr {
  if (FakeXhr.last === null) throw new Error("no XMLHttpRequest was made");
  return FakeXhr.last;
}
