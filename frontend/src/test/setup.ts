import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());

// jsdom has no EventSource; a silent stub keeps components that stream events renderable.
class StubEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {}
  addEventListener(): void {}
  close(): void {
    this.readyState = StubEventSource.CLOSED;
  }
}
globalThis.EventSource ??= StubEventSource as unknown as typeof EventSource;
