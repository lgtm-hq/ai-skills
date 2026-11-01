import { expect, test } from "bun:test";
import endpoint from "../network-control.json";
import { windowsNetworkControl, type WinsockLibrary } from "./windows-network-control";

type Operation = keyof WinsockLibrary["symbols"] | "dlclose";
interface Scenario {
  connectError?: number;
  pending?: boolean;
  socketError?: number;
  timeout?: boolean;
  fail?: Operation;
  throws?: Operation;
  malformed?: boolean;
  exceptionalOnly?: boolean;
}

function fake(scenario: Scenario = {}) {
  const calls: Operation[] = [];
  // Exercise all 64 bits of SOCKET; truncation to a JS number loses identity.
  const handle = 0x20000000000001n;
  function called(operation: Operation): boolean {
    calls.push(operation);
    if (scenario.throws === operation) throw new Error(`injected ${operation}`);
    return scenario.fail === operation;
  }
  function view(value: Parameters<WinsockLibrary["symbols"]["connect"]>[1]): DataView {
    if (!ArrayBuffer.isView(value)) throw new Error("expected native buffer");
    return new DataView(value.buffer, value.byteOffset, value.byteLength);
  }
  const library: WinsockLibrary = {
    symbols: {
      WSAStartup: (version, data) => {
        expect(version).toBe(0x0202);
        expect(view(data).byteLength).toBe(408);
        return called("WSAStartup") ? 10092 : 0;
      },
      socket: (family, type, protocol) => {
        expect([family, type, protocol]).toEqual([2, 1, 6]);
        return called("socket") ? 0xffffffffffffffffn : handle;
      },
      ioctlsocket: (socket, command, value) => {
        expect(socket).toBe(handle);
        expect(command >>> 0).toBe(0x8004667e);
        expect(view(value).getUint32(0, true)).toBe(1);
        return called("ioctlsocket") ? -1 : 0;
      },
      connect: (socket, address, length) => {
        expect(socket).toBe(handle);
        const data = view(address);
        expect(length).toBe(16);
        expect(data.getUint16(0, true)).toBe(2);
        expect(data.getUint16(2, false)).toBe(endpoint.port);
        expect(Array.from({ length: 4 }, (_, i) => data.getUint8(4 + i))).toEqual(
          endpoint.address.split(".").map(Number),
        );
        expect(Array.from({ length: 8 }, (_, i) => data.getUint8(8 + i))).toEqual(Array(8).fill(0));
        called("connect");
        return scenario.pending || scenario.connectError ? -1 : 0;
      },
      WSAGetLastError: () => {
        const previous = calls.at(-1);
        called("WSAGetLastError");
        return scenario.fail === previous
          ? 10013
          : scenario.pending
            ? 10035
            : (scenario.connectError ?? 0);
      },
      select: (ignored, readable, writable, exceptional, timeout) => {
        expect(ignored).toBe(0);
        expect(readable).toBeNull();
        for (const value of [writable, exceptional]) {
          expect(view(value).byteLength).toBe(520);
          expect(view(value).getUint32(0, true)).toBe(1);
          expect(view(value).getBigUint64(8, true)).toBe(handle);
        }
        expect([view(timeout).getInt32(0, true), view(timeout).getInt32(4, true)]).toEqual([2, 0]);
        if (called("select")) return -1;
        view(writable).setUint32(0, scenario.socketError || scenario.exceptionalOnly ? 0 : 1, true);
        view(exceptional).setUint32(
          0,
          scenario.socketError || scenario.exceptionalOnly ? 1 : 0,
          true,
        );
        return scenario.timeout ? 0 : 1;
      },
      getsockopt: (socket, level, option, error, length) => {
        expect([socket, level, option]).toEqual([handle, 0xffff, 0x1007]);
        expect(view(length).getInt32(0, true)).toBe(4);
        if (called("getsockopt")) return -1;
        view(error).setInt32(0, scenario.socketError ?? 0, true);
        if (scenario.malformed) view(length).setInt32(0, 0, true);
        return 0;
      },
      closesocket: (socket) => {
        expect(socket).toBe(handle);
        return called("closesocket") ? -1 : 0;
      },
      WSACleanup: () => (called("WSACleanup") ? -1 : 0),
    },
    close: () => {
      called("dlclose");
    },
  };
  return { library, calls };
}

test.each([false, true])(
  "Winsock success (pending=%s) closes every owned resource",
  async (pending) => {
    const { library, calls } = fake({ pending });
    const result = await windowsNetworkControl({ load: async () => library });
    expect(result).toEqual([
      { ...endpoint, backend: "winsock", outcome: "connected", cleanup_errors: [] },
    ]);
    expect(calls.slice(-3)).toEqual(["closesocket", "WSACleanup", "dlclose"]);
  },
);

test.each([10013, 10061, 10051, 10065, 10060, 10049])(
  "Winsock retains native connect/SO_ERROR %s without laundering refusal",
  async (code) => {
    for (const pending of [false, true]) {
      const { library, calls } = fake(
        pending ? { pending, socketError: code } : { connectError: code },
      );
      const [result] = await windowsNetworkControl({ load: async () => library });
      expect(result).toEqual({
        ...endpoint,
        backend: "winsock",
        outcome: code === 10013 ? "explicit-denial" : "inconclusive",
        raw_error: { api: pending ? "SO_ERROR" : "connect", code },
        cleanup_errors: [],
      });
      expect(calls.slice(-3)).toEqual(["closesocket", "WSACleanup", "dlclose"]);
      if (!pending) expect(calls.indexOf("WSAGetLastError")).toBe(calls.indexOf("connect") + 1);
    }
  },
);

test.each(["WSAStartup", "socket", "ioctlsocket", "select", "getsockopt"] as const)(
  "Winsock %s failure stays unknown and cleans up only acquired resources",
  async (fail) => {
    const { library, calls } = fake({ pending: true, fail });
    const [result] = await windowsNetworkControl({ load: async () => library });
    expect(result?.outcome).toBe("inconclusive");
    expect(result?.raw_error).toEqual({ api: fail, code: fail === "WSAStartup" ? 10092 : 10013 });
    expect(calls.filter((c) => c === "closesocket").length).toBe(
      ["WSAStartup", "socket"].includes(fail) ? 0 : 1,
    );
    expect(calls.filter((c) => c === "WSACleanup").length).toBe(fail === "WSAStartup" ? 0 : 1);
    expect(calls.at(-1)).toBe("dlclose");
  },
);

test.each(["WSAStartup", "socket", "ioctlsocket", "connect", "select", "getsockopt"] as const)(
  "Winsock exception at %s cleans up and retains raw error",
  async (throws) => {
    const { library, calls } = fake({ pending: true, throws });
    const [result] = await windowsNetworkControl({ load: async () => library });
    expect(result?.outcome).toBe("inconclusive");
    expect(result?.raw_error).toEqual({ api: throws, message: `Error: injected ${throws}` });
    expect(calls.filter((c) => c === "closesocket").length).toBe(
      ["WSAStartup", "socket"].includes(throws) ? 0 : 1,
    );
    expect(calls.filter((c) => c === "WSACleanup").length).toBe(throws === "WSAStartup" ? 0 : 1);
    expect(calls.at(-1)).toBe("dlclose");
  },
);

test.each([{ timeout: true }, { malformed: true }, { exceptionalOnly: true }])(
  "Winsock ambiguous readiness %j stays inconclusive",
  async (scenario) => {
    const { library, calls } = fake({ pending: true, ...scenario });
    const [result] = await windowsNetworkControl({ load: async () => library });
    expect(result?.outcome).toBe("inconclusive");
    expect(calls.slice(-3)).toEqual(["closesocket", "WSACleanup", "dlclose"]);
  },
);

test.each(["closesocket", "WSACleanup", "dlclose"] as const)(
  "Winsock cleanup exception %s invalidates success and denial, attempts all cleanup",
  async (throws) => {
    for (const connectError of [undefined, 10013]) {
      const { library, calls } = fake({ throws, connectError });
      const [result] = await windowsNetworkControl({ load: async () => library });
      expect(result?.outcome).toBe("inconclusive");
      expect(result?.cleanup_errors).toEqual([
        { api: throws, message: `Error: injected ${throws}` },
      ]);
      expect(calls.slice(-3)).toEqual(["closesocket", "WSACleanup", "dlclose"]);
    }
  },
);

test.each(["closesocket", "WSACleanup"] as const)(
  "Winsock cleanup error code %s invalidates proof and retains native error",
  async (fail) => {
    const { library, calls } = fake({ fail });
    const [result] = await windowsNetworkControl({ load: async () => library });
    expect(result?.outcome).toBe("inconclusive");
    expect(result?.cleanup_errors).toEqual([{ api: fail, code: 10013 }]);
    expect(calls).toContain("closesocket");
    expect(calls).toContain("WSACleanup");
    expect(calls.at(-1)).toBe("dlclose");
  },
);

test("Winsock unavailable library stays unknown without creating sockets", async () => {
  const [result] = await windowsNetworkControl({
    load: async () => {
      throw new Error("FFI unavailable");
    },
  });
  expect(result).toEqual({
    ...endpoint,
    backend: "winsock",
    outcome: "inconclusive",
    raw_error: { api: "dlopen", message: "Error: FFI unavailable" },
    cleanup_errors: [],
  });
});

test.each([undefined, "relative"])(
  "Winsock refuses untrusted DLL search path %s before loading",
  async (root) => {
    const upper = process.env.SYSTEMROOT,
      mixed = process.env.SystemRoot;
    try {
      delete process.env.SYSTEMROOT;
      delete process.env.SystemRoot;
      if (root) process.env.SYSTEMROOT = root;
      const [result] = await windowsNetworkControl();
      expect(result?.outcome).toBe("inconclusive");
      expect(result?.raw_error).toEqual({
        api: "dlopen",
        message: "Error: absolute SystemRoot required",
      });
      expect(result?.cleanup_errors).toEqual([]);
    } finally {
      if (upper !== undefined) process.env.SYSTEMROOT = upper;
      else delete process.env.SYSTEMROOT;
      if (mixed !== undefined) process.env.SystemRoot = mixed;
      else delete process.env.SystemRoot;
    }
  },
);
