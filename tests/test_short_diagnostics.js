"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const base=path.join(__dirname,"..","smart-jkbms-bluetooth");
const nodes=JSON.parse(fs.readFileSync(path.join(base,"short_diagnostics_flows.json"),"utf8"));
const fn=nodes.find(n=>n.id==="b111a90000000002"),output=nodes.find(n=>n.id==="b111a90000000004");
assert(fn && output && output.active);
const call=new Function("msg","context","node","Buffer","Date",fn.func);
const state=new Map(),context={get:k=>state.get(k),set:(k,v)=>state.set(k,v)};
let current=1000000;
const clock={now:()=>current}, node={status:()=>{}};
const mac1="C8:47:80:1A:1A:EF",mac2="C8:47:80:1A:27:12";
function run(d){return call({payload:d},context,node,Buffer,clock);}
for(const [mac,rssi] of [[mac1,-42],[mac2,-38]]){
 assert.equal(run({address:mac,type:"device_found",rssi,name:"Batterie"}),null);
 assert.equal(run({address:mac,type:"connected"}),null);
}
const bad=Buffer.alloc(300);bad.set([0x55,0xaa,0xeb,0x90,2,8],0);
bad[299]=bad.subarray(0,299).reduce((a,b)=>(a+b)&255,0);
assert.equal(run({address:mac1,type:2,crc_ok:true,raw_hex:bad.toString("hex"),sequence:8}),null);
const good=Buffer.alloc(300);good.set([0x55,0xaa,0xeb,0x90,2,9],0);
for(let i=0;i<16;i++)good.writeUInt16LE(3200,6+i*2);
good.writeUInt32LE(0xffff,70);good.writeUInt32LE(51200,150);good[173]=21;
good.writeInt16LE(166,162);good.writeInt16LE(165,164);good.writeInt16LE(185,144);
good[299]=good.subarray(0,299).reduce((a,b)=>(a+b)&255,0);
assert.equal(run({address:mac2,type:2,crc_ok:true,raw_hex:good.toString("hex"),sequence:9}),null);
assert.equal(run({address:mac2,validation:"provisional_compare_with_BatMON",source_crc_ok:true,format:"JK02_32S",voltage_v:51.2,soc_pct:21}),null);
const list=run("short_tick");
assert(list&&Array.isArray(list[0]));
assert.equal(list[0].length,4);
const lines=list[0].map(m=>m.payload);
assert(lines.some(s=>s.includes("1A:EF")&&s.includes("DÉCODAGE REJETÉ")));
assert(lines.some(s=>s.includes("1A:EF 24S REJET : cellules 0/24")));
assert(lines.some(s=>s.includes("1A:EF 32S REJET : cellules 0/32")));
assert(lines.some(s=>s.includes("27:12")&&s.includes("MESURES OK")));
for(const l of lines)assert(l.length<=95,"too long: "+l);
const baseNodes=[
...JSON.parse(fs.readFileSync(path.join(base,"flows.json"),"utf8")),
...JSON.parse(fs.readFileSync(path.join(base,"decoder_flows.json"),"utf8"))
];
for(const origin of ["136f1472850339d1","65ad8ac512b5e001","b150100000000004"]){
 assert(baseNodes.find(n=>n.id===origin).wires[0].includes(fn.id));
}
current+=1000;
assert.equal(run({address:mac1,type:"disconnected"}),null);
assert(run("short_tick")[0].some(m=>m.payload.includes("1A:EF | BLE OFF")));
console.log("Per-BMS concise diagnostics OK: 2 batteries, 24S/32S failures, readable lines, wiring, no MQTT");
