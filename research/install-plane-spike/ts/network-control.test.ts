import { afterEach, expect, spyOn, test } from "bun:test";
import { Socket } from "node:net";
import endpoint from "../network-control.json";
import { networkControl } from "./network-control";

afterEach(() => {
  connect.mockRestore();
});
let connect = spyOn(Socket.prototype, "connect");

test.each([
  ["connect", undefined, "connected"],
  ["timeout", undefined, "inconclusive"],
])("network diagnostic %s/%s stays scoped", async (event, code, outcome) => {
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    queueMicrotask(() => this.emit(event, Object.assign(new Error("boundary"), { code })));
    return this;
  });
  // Exercise the generated Node diagnostic even when tests run on Bun/Windows.
  const results = await networkControl({ isBun: false });
  expect(connect).toHaveBeenCalledWith({ host: endpoint.address, port: endpoint.port, family: 4 });
  expect(results).toMatchObject([{ ...endpoint, outcome }]);
});

test.each(
  ["create", "settimeout", "connect", "close"].flatMap((stage) =>
    ["EACCES", "ENETUNREACH"].map((code) => ({ stage, code })),
  ),
)("$stage lifecycle $code errors are scoped to the failing operation", async ({ stage, code }) => {
  const error = Object.assign(new Error("lifecycle failure"), {
    code,
    errno: code === "EACCES" ? -13 : -101,
    syscall: "connect",
  });
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    if (stage === "connect") throw error;
    this.emit("connect");
    return this;
  });
  const timeout = spyOn(Socket.prototype, "setTimeout").mockImplementation(function (this: Socket) {
    if (stage === "settimeout") throw error;
    return this;
  });
  const originalDestroy = Socket.prototype.destroy;
  const destroy = spyOn(Socket.prototype, "destroy").mockImplementation(function (this: Socket) {
    if (stage === "close") throw error;
    return originalDestroy.call(this);
  });
  try {
    const results = await networkControl({
      isBun: false,
      platform: "linux",
      createSocket: () => {
        if (stage === "create") throw error;
        return new Socket();
      },
    });
    expect(results).toMatchObject([
      {
        ...endpoint,
        outcome: stage === "connect" && code === "EACCES" ? "explicit-denial" : "inconclusive",
        stage,
        error: error.message,
        raw_error: { code: error.code, errno: error.errno, syscall: error.syscall },
      },
    ]);
    expect(destroy).toHaveBeenCalledTimes(stage === "create" ? 0 : 1);
  } finally {
    timeout.mockRestore();
    destroy.mockRestore();
  }
});

test.each([false, true])("cleanup error overrides connected=%s", async (connected) => {
  const error = Object.assign(new Error("connect denied"), { code: "EACCES", syscall: "connect" });
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    this.emit(connected ? "connect" : "error", error);
    return this;
  });
  const destroy = spyOn(Socket.prototype, "destroy").mockImplementation(() => {
    throw Object.assign(new Error("close failed"), { code: "EPERM" });
  });
  try {
    expect(await networkControl({ isBun: false })).toMatchObject([
      {
        outcome: "inconclusive",
        outcome_before_cleanup: connected ? "connected" : "explicit-denial",
        cleanup_error: { stage: "close", error: "close failed", raw_error: { code: "EPERM" } },
      },
    ]);
    expect(destroy).toHaveBeenCalledTimes(1);
  } finally {
    destroy.mockRestore();
  }
});

test("a permission error for another syscall is inconclusive", async () => {
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    this.emit(
      "error",
      Object.assign(new Error("bind failed"), { code: "EACCES", syscall: "bind" }),
    );
    return this;
  });
  expect(await networkControl({ isBun: false })).toMatchObject([{ outcome: "inconclusive" }]);
});

for (const platform of ["linux", "darwin", "win32"] as const) {
  test.each([
    ["EACCES", -4092],
    ["EPERM", -4048],
    ["ENETUNREACH", -4062],
    ["EHOSTUNREACH", -4073],
    ["ECONNREFUSED", -4078],
    ["ETIMEDOUT", -4039],
    [undefined, undefined],
  ] as const)(
    `${platform} Node connection error %s retains permission evidence only`,
    async (code, errno) => {
      const error = Object.assign(new Error("boundary"), { code, errno, syscall: "connect" });
      const destroy = spyOn(Socket.prototype, "destroy");
      try {
        connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
          queueMicrotask(() => this.emit("error", error));
          return this;
        });
        const results = await networkControl({ platform, isBun: false });
        const denied = code === "EACCES" || (platform !== "win32" && code === "EPERM");
        expect(results).toEqual([
          {
            ...endpoint,
            outcome: denied ? "explicit-denial" : "inconclusive",
            error: error.message,
            stage: "connect",
            raw_error: { code, errno, syscall: "connect" },
          },
        ]);
        expect(connect).toHaveBeenCalledWith({
          host: endpoint.address,
          port: endpoint.port,
          family: 4,
        });
        expect(destroy).toHaveBeenCalledTimes(1);
      } finally {
        destroy.mockRestore();
      }
    },
  );
}

test("only Bun Win64 selects native Winsock; unsupported ABI fails closed", async () => {
  let calls = 0;
  const windows = async () => {
    calls++;
    return [];
  };
  expect(await networkControl({ platform: "win32", isBun: true, arch: "x64", windows })).toEqual(
    [],
  );
  expect(calls).toBe(1);
  expect(
    await networkControl({ platform: "win32", isBun: true, arch: "arm64", windows }),
  ).toMatchObject([{ outcome: "inconclusive" }]);
  expect(calls).toBe(1);
});

test("asynchronous cleanup failure invalidates a connected baseline", async () => {
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    this.emit("connect");
    return this;
  });
  const destroy = spyOn(Socket.prototype, "destroy").mockImplementation(function (this: Socket) {
    queueMicrotask(() => {
      this.emit("error", Object.assign(new Error("async close failed"), { code: "EPERM" }));
      this.emit("close");
    });
    return this;
  });
  try {
    expect(await networkControl({ isBun: false })).toMatchObject([
      {
        outcome: "inconclusive",
        outcome_before_cleanup: "connected",
        cleanup_error: { stage: "close", error: "async close failed" },
      },
    ]);
    expect(destroy).toHaveBeenCalledTimes(1);
  } finally {
    destroy.mockRestore();
  }
});

test.each([
  ["win32", false],
  ["linux", true],
] as const)("%s isBun=%s preserves node:net and never loads Winsock", async (platform, isBun) => {
  connect = spyOn(Socket.prototype, "connect").mockImplementation(function (this: Socket) {
    queueMicrotask(() => this.emit("connect"));
    return this;
  });
  const results = await networkControl({
    platform,
    isBun,
    windows: async () => {
      throw new Error("must not load");
    },
  });
  expect(results).toMatchObject([{ ...endpoint, outcome: "connected" }]);
});
