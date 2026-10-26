"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");
const source = path.join(__dirname, "../smart-jkbms-bluetooth/bip_flows.json");
const nodes = JSON.parse(fs.readFileSync(source, "utf8"));
assert.equal(nodes.length, 5);
const ids = nodes.map(n => n.id);
assert.equal(new Set(ids).size, ids.length);
const inject = nodes.find(n => n.type === "inject");
const fn = nodes.find(n => n.type === "function" && n.name === "Check BIP consent");
const http = nodes.find(n => n.type === "http request");
assert(inject && fn && http);
assert.equal(inject.once, true);
assert.equal(inject.crontab, "0 15 * * *");
assert.equal(http.url, "");  // No fixed endpoint in the flow.
const config = fs.readFileSync(path.join(__dirname, "../smart-jkbms-bluetooth/config.yaml"), "utf8");
const runner = fs.readFileSync(path.join(__dirname, "../smart-jkbms-bluetooth/run.sh"), "utf8");
assert.match(config, /^  send_bip: true$/m, "New installs must send BIP by default");
assert.match(config, /^  bip_endpoint: "https:\/\/script\.google\.com\/macros\/s\/.+\/exec"$/m);
assert.match(runner, /\.send_bip \/\/ true/, "Older installations missing this option default ON");
assert.match(runner, /SMART_JKBMS_BIP_ENDPOINT/, "Export collector URL");

const statuses = [];
const node = {status: v => statuses.push(v)};
const id = "f34c41fe-5678-4c9d-bef2-fb4771827a3d";
const endpoint = "https://example.org/collector";
function prepare(values) {
  const context = {
    env: { get: name => values[name] || "" },
    node, msg: {payload:"old"}
  };
  return vm.runInNewContext("(function() {" + fn.func + "\n})()", context);
}
assert.equal(prepare({SEND_BIP:"false",SMART_JKBMS_INSTALL_ID:id,SMART_JKBMS_BIP_ENDPOINT:endpoint}), null);
assert.equal(prepare({SEND_BIP:"true",SMART_JKBMS_INSTALL_ID:id}), null);
const data = prepare({
  SEND_BIP:"true",
  SMART_JKBMS_INSTALL_ID:id,
  SMART_JKBMS_BIP_ENDPOINT:endpoint,
  SMART_JKBMS_VERSION:"0.3.1"
});
assert(data);
assert.equal(data.url, endpoint);
assert.equal(data.method, "POST");
assert.equal(data.followRedirects, false);
assert.equal(data.payload.module, "jkbms");
assert.equal(data.payload.install_id, id);
assert.equal(data.payload.bip, "10");
assert.equal(data.payload.version, "0.3.1");
assert.deepEqual(Object.keys(data.payload).sort(), ["module","install_id","bip","version"].sort());
assert(!/(mac|serial|voltage|current|soc|longitude|latitude|country|city|region)/i.test(fn.func));
console.log("BIP flow tests passed: default-on/opt-out, stable ID, no battery/location data, daily+startup trigger");
