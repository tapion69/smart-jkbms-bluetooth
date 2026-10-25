"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const dir = path.join(__dirname,"..","smart-jkbms-bluetooth");
const extra = JSON.parse(fs.readFileSync(path.join(dir,"summary_flows.json"),"utf8"));
const f = extra.find(x=>x.id==="f5500ba6100a0001");
const dbg = extra.find(x=>x.id==="f5500ba6100a0002");
assert(f && dbg && dbg.active===true);
const run = new Function("msg","context","node","Date",f.func);
const mem = new Map();
const context = {get:k=>mem.get(k),set:(k,v)=>mem.set(k,v)};
const node = {status:()=>{}};
let now=12000;
const clock = {now:()=>now};
const a="C8:47:80:1A:1A:EF",b="C8:47:80:1A:27:12";
function msg(address) {return {topic:"test",payload:{
    address,validation:"provisional_compare_with_BatMON",
    voltage_v:52.78,current_a:-12.345,power_w:-651.57,soc_pct:74,
    cell_count:16,cell_delta_mv:8,temp1_c:24.5,temp2_c:25.3,
    mos_temp_c:28.8,format:"JK02_32S"
}};}
const first=run(msg(a),context,node,clock);
assert(first);
assert.equal(first.topic,"jk/"+a+"/resume");
assert.equal(typeof first.payload,"string");
assert(first.payload.includes("52.78 V"));
assert(first.payload.includes("SOC 74%"));
assert(first.payload.includes("16 cellules"));
assert(first.payload.includes("Δ 8 mV"));
assert(first.payload.includes("T1 24.5°C"));
assert.equal(run(msg(a),context,node,clock),null);
assert(run(msg(b),context,node,clock),"second BMS must have independent rate limiting");
now+=9999;
assert.equal(run(msg(a),context,node,clock),null);
now+=1;
assert(run(msg(a),context,node,clock));
const oneTemperatureBad=msg(a);
oneTemperatureBad.payload.mos_temp_c=null;
oneTemperatureBad.payload.invalid_temperature_channels=["MOS"];
now+=10001;
const quality=run(oneTemperatureBad,context,node,clock);
assert(quality&&quality.payload.includes("TEMP MOS INVALIDE"),"Temperature warning must be prominent");
assert(quality.payload.includes("MOS N/D"),"Null temperature must never display as 0°C");
assert(!quality.payload.includes("MOS 0.0°C"));
const bad=msg(a);delete bad.payload.voltage_v;
now+=10001;
assert.equal(run(bad,context,node,clock),null);
const unvalidated=msg(a);unvalidated.payload.validation="unverified";
assert.equal(run(unvalidated,context,node,clock),null);
const flows = JSON.parse(fs.readFileSync(path.join(dir,"flows.json"),"utf8"));
const decoder = JSON.parse(fs.readFileSync(path.join(dir,"decoder_flows.json"),"utf8"));
const noisy=[
  "d4cb3acdbe43f291","5524471869b2e0af","8d30a20107f452b3",
  "b150100000000006","b150100000000007"
];
const existing=[...flows,...decoder];
for(const id of noisy) {
 const n=existing.find(x=>x.id===id);
 assert(n && n.type==="debug" && n.active===false,"noisy debug must be disabled: "+id);
}
const source=decoder.find(x=>x.id==="b150100000000004");
assert(source.wires[0].includes(f.id),"new installs need summary to be wired");
console.log("Quiet bilingual-friendly summary tests passed (two BMS, 10 seconds, format, no raw flood)");
