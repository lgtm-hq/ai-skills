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
  const results = await networkControl();
  expect(connect).toHaveBeenCalledWith({ host: endpoint.address, port: endpoint.port, family: 4 });
  expect(results).toMatchObject([{ ...endpoint, outcome }]);
});
