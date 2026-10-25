"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const flows = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "smart-jkbms-bluetooth", "flows.json"), "utf8"));
const node = flows.find(n => n.id === "65ad8ac512b5e001");
assert(node, "Frame assembler function missing");
const fn = new Function("msg", "context", "Buffer", node.func);
const values = new Map();
const context = {get: k => values.get(k), set: (k, v) => values.set(k, v)};
const a = "C8:47:80:1A:27:12", b = "C8:47:80:1A:1A:EF";

function input(address, chunk) {
  return fn({payload: {type: "raw_notification", address, hex: chunk.toString("hex"), time: 12345}}, context, Buffer);
}
function frame(type = 2) {
  const b = Buffer.alloc(300);
  b.set([0x55, 0xaa, 0xeb, 0x90, type, 17], 0);
  for (let i = 6; i < 299; i++) b[i] = i & 0xff;
  b[299] = b.subarray(0, 299).reduce((acc, v) => (acc + v) & 0xff, 0);
  return b;
}
const first = frame(2);
assert.equal(input(a, first.subarray(0, 1)), null);
assert.equal(input(a, first.subarray(1, 45)), null);
assert.equal(input(b, Buffer.from("AT\r\n")), null); // separate device buffer
const result = input(a, first.subarray(45));
assert.equal(result[0].length, 1);
assert.equal(result[0][0].payload.crc_ok, true);
assert.equal(result[0][0].payload.frame_length, 300);
assert.equal(result[0][0].payload.type, 2);
assert.equal(result[0][0].payload.address, a);
assert.equal(result[0][0].payload.raw_hex, first.toString("hex").toUpperCase());
const broken = Buffer.from(first);
broken[299] ^= 255;
const invalid = input(a, broken);
assert.equal(invalid[1][0].payload.reason, "invalid_header_type_or_crc");
const device = frame(3);
assert.equal(input(a, device)[0][0].payload.type, 3);
console.log("Node-RED JK02 raw-frame reassembly tests passed");
