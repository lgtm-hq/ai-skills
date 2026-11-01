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
  ["error", "EACCES", "explicit-denial"],
  ["error", "ENETUNREACH", "explicit-denial"],
  ["error", "ECONNREFUSED", "inconclusive"],
  ["error", "ETIMEDOUT", "inconclusive"],
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
