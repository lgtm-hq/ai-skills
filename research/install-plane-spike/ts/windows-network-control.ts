import type { Library } from "bun:ffi";
import { win32 } from "node:path";
import endpoint from "../network-control.json";

// Win64 ABI: SOCKET is UINT_PTR, not a pointer. All calls are synchronous so
// WSAGetLastError is read on the calling thread immediately after a failed call.
const SYMBOLS = {
  WSAStartup: { args: ["u16", "ptr"], returns: "i32" },
  WSACleanup: { args: [], returns: "i32" },
  WSAGetLastError: { args: [], returns: "i32" },
  socket: { args: ["i32", "i32", "i32"], returns: "u64" },
  ioctlsocket: { args: ["u64", "i32", "ptr"], returns: "i32" },
  connect: { args: ["u64", "ptr", "i32"], returns: "i32" },
  select: { args: ["i32", "ptr", "ptr", "ptr", "ptr"], returns: "i32" },
  getsockopt: { args: ["u64", "i32", "i32", "ptr", "ptr"], returns: "i32" },
  closesocket: { args: ["u64"], returns: "i32" },
} as const;

type NativeSymbols = Library<typeof SYMBOLS>["symbols"];
type WinsockSymbols = {
  [K in keyof NativeSymbols]: (
    ...args: Parameters<NativeSymbols[K]>
  ) => ReturnType<NativeSymbols[K]>;
};
export interface WinsockLibrary {
  symbols: WinsockSymbols;
  close(): void;
}

async function loadWinsock(): Promise<WinsockLibrary> {
  const root = process.env.SYSTEMROOT ?? process.env.SystemRoot;
  if (!root || !win32.isAbsolute(root)) throw new Error("absolute SystemRoot required");
  // Deferred import: Node's emitted diagnostic and non-Windows Bun never load FFI.
  const { dlopen } = await import("bun:ffi");
  return dlopen(win32.join(root, "System32", "ws2_32.dll"), SYMBOLS);
}

interface RawError {
  api: string;
  code?: number;
  message?: string;
}
interface Observation {
  address: string;
  port: number;
  backend: "winsock";
  outcome: "connected" | "explicit-denial" | "inconclusive";
  raw_error?: RawError;
  cleanup_errors: RawError[];
}

// https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-select
// A failed nonblocking connect is signaled in exceptfds; SO_ERROR, not Bun's
// node:net translation, supplies the authoritative native connection error.
export async function windowsNetworkControl({
  load = loadWinsock,
}: { load?: () => Promise<WinsockLibrary> } = {}): Promise<Observation[]> {
  const result: Observation = {
    ...endpoint,
    backend: "winsock",
    outcome: "inconclusive",
    cleanup_errors: [],
  };
  let library: WinsockLibrary | undefined;
  let started = false;
  let socket: bigint | undefined;
  let api = "dlopen";
  const fail = (operation: string, code: number) => {
    result.raw_error = { api: operation, code };
    // Refusal, unreachable, timeout and unknown errors never prove policy denial.
    result.outcome =
      (operation === "connect" || operation === "SO_ERROR") && code === 10013
        ? "explicit-denial"
        : "inconclusive";
  };
  try {
    library = await load();
    const native = library.symbols;
    api = "WSAStartup";
    // sizeof(WSADATA) = 408 on Win64. WSAStartup returns its own error code.
    const startup = native.WSAStartup(0x0202, new Uint8Array(408));
    if (startup !== 0) {
      fail(api, startup);
      return [result];
    }
    started = true;
    api = "socket";
    const handle = native.socket(2, 1, 6); // AF_INET, SOCK_STREAM, IPPROTO_TCP
    if (handle === 0xffffffffffffffffn) {
      fail(api, native.WSAGetLastError());
      return [result];
    }
    socket = handle;
    api = "ioctlsocket";
    const nonblocking = new Uint32Array([1]);
    // FIONBIO is a signed Windows long (0x8004667e).
    if (native.ioctlsocket(socket, -2147195266, nonblocking) !== 0) {
      fail(api, native.WSAGetLastError());
      return [result];
    }
    const address = new Uint8Array(16); // sockaddr_in, zeroed sin_zero
    const view = new DataView(address.buffer);
    view.setUint16(0, 2, true); // host-order family
    view.setUint16(2, endpoint.port, false); // network-order port/address
    address.set(endpoint.address.split(".").map(Number), 4);
    api = "connect";
    if (native.connect(socket, address, address.length) === 0) {
      result.outcome = "connected";
      return [result];
    }
    const error = native.WSAGetLastError();
    if (error !== 10035) {
      fail(api, error);
      return [result];
    } // WSAEWOULDBLOCK
    const fdset = () => {
      const bytes = new Uint8Array(520); // count, alignment, 64 UINT_PTR slots
      const data = new DataView(bytes.buffer);
      data.setUint32(0, 1, true);
      data.setBigUint64(8, handle, true);
      return bytes;
    };
    const writable = fdset(),
      exceptional = fdset();
    const timeout = new Int32Array([2, 0]); // timeval: two Windows longs, <=2s
    api = "select";
    const ready = native.select(0, null, writable, exceptional, timeout);
    if (ready < 0) {
      fail(api, native.WSAGetLastError());
      return [result];
    }
    if (ready === 0) {
      result.raw_error = { api, message: "two-second timeout" };
      return [result];
    }
    api = "getsockopt";
    const socketError = new Int32Array(1),
      length = new Int32Array([4]);
    if (native.getsockopt(socket, 0xffff, 0x1007, socketError, length) !== 0) {
      fail(api, native.WSAGetLastError());
      return [result];
    }
    if (length[0] !== 4) throw new Error("unexpected SO_ERROR size");
    const code = socketError[0]!;
    if (code !== 0) {
      fail("SO_ERROR", code);
      return [result];
    }
    // Zero SO_ERROR alone is insufficient; require writable, not exceptional.
    if (
      new DataView(writable.buffer).getUint32(0, true) === 1 &&
      new DataView(exceptional.buffer).getUint32(0, true) === 0
    ) {
      result.outcome = "connected";
    } else {
      result.raw_error = { api: "select/SO_ERROR", message: "inconsistent readiness" };
    }
  } catch (error: unknown) {
    result.outcome = "inconclusive";
    result.raw_error = { api, message: String(error) };
  } finally {
    // Attempt every cleanup even if a previous cleanup throws. Never retain a
    // passing observation after any failed cleanup; handles never leave this scope.
    const cleanup = (operation: string, close: () => number | void) => {
      try {
        const code = close();
        if (code !== undefined && code !== 0) {
          result.cleanup_errors.push({ api: operation, code: library!.symbols.WSAGetLastError() });
        }
      } catch (error: unknown) {
        result.cleanup_errors.push({ api: operation, message: String(error) });
      }
    };
    if (socket !== undefined) cleanup("closesocket", () => library!.symbols.closesocket(socket!));
    if (started) cleanup("WSACleanup", () => library!.symbols.WSACleanup());
    if (library) cleanup("dlclose", () => library!.close());
    if (result.cleanup_errors.length) result.outcome = "inconclusive";
  }
  return [result];
}
