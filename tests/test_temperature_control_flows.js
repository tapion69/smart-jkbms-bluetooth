"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const root=path.join(__dirname,"..","smart-jkbms-bluetooth");
const flows=JSON.parse(fs.readFileSync(path.join(root,"temperature_control_flows.json"),"utf8"));
const base=JSON.parse(fs.readFileSync(path.join(root,"flows.json"),"utf8"));
const get=id=>flows.find(n=>n.id===id);
for(const id of ["b161600000000002","b161600000000004","b161600000000007",
 "b161600000000010","b161600000000011","b161600000000013","b161600000000015"]){
 assert(get(id),"Missing Node-RED node "+id);
}
assert.equal(get("b161600000000004").filename,"filename");
assert.equal(get("b161600000000004").filenameType,"msg");
const html=fs.readFileSync(path.join(root,"ui","temperature.html"),"utf8");
assert(html.includes('id="cards"'));
assert(html.includes('I_UNDERSTAND_THERMAL_PROTECTION_RISK'));
assert(html.includes('confirm('));
const cfg=fs.readFileSync(path.join(root,"config.yaml"),"utf8");
assert(cfg.includes("allow_temperature_control: false"));
const source=base.find(n=>n.id==="65ad8ac512b5e001");
assert(source.wires[0].includes("b161600000000010"));
const now=Date.now();
const a="C8:47:80:1A:1A:EF",b="C8:47:80:1A:27:12";
const memory=new Map(),context={get:k=>memory.get(k),set:(k,v)=>memory.set(k,v)};
const env={get:k=>({
 BLE_BMS_ADDRESSES:a+","+b,BLE_TEMP_CONTROL_ENABLED:"false",BLE_BRIDGE_TOKEN:"abc"
})[k]};
const status={status:()=>{}};
const parser=new Function("msg","global","node","Buffer","Date",get("b161600000000010").func);
const state=new Function("msg","global","env","Date",get("b161600000000008").func);
const action=new Function("msg","env",get("b161600000000012").func);
let d=state({},context,env,Date);
assert.equal(d.payload.batteries.length,2);
assert.equal(d.payload.batteries[0].confirmed,false);
const before=action({payload:{address:a,action:"set_temperature_disabled",disable:true,
 confirmation:"I_UNDERSTAND_THERMAL_PROTECTION_RISK"}},env);
assert.equal(before[1].statusCode,403);
const enabled={get:k=>k==="BLE_TEMP_CONTROL_ENABLED"?"true":env.get(k)};
const cmd=action({payload:{address:a,action:"set_temperature_disabled",disable:true,
 confirmation:"I_UNDERSTAND_THERMAL_PROTECTION_RISK"}},enabled);
assert.equal(cmd[1],null);
assert.equal(cmd[0].url,"http://127.0.0.1:1896/control");
assert.equal(JSON.parse(cmd[0].payload).disable,true);
const raw=Buffer.alloc(300);raw.set([0x55,0xAA,0xEB,0x90,1,3]);
raw.writeUInt16LE(0x0002,282);
raw[299]=raw.subarray(0,299).reduce((s,v)=>(s+v)&255,0);
assert.equal(parser({payload:{address:a,type:1,crc_ok:true,raw_hex:raw.toString("hex")}},context,status,Buffer,Date),null);
d=state({},context,enabled,Date);
assert.equal(d.payload.batteries[0].confirmed,true);
assert.equal(d.payload.batteries[0].disabled,true);
assert.equal(d.payload.batteries[1].confirmed,false);
const invalid=Buffer.from(raw);invalid[299]^=0xff;
assert.equal(parser({payload:{address:b,type:1,crc_ok:true,raw_hex:invalid.toString("hex")}},context,status,Buffer,Date),null);
d=state({},context,enabled,Date);
assert.equal(d.payload.batteries[1].confirmed,false);
const page=fs.readFileSync(path.join(root,"settings.js"),"utf8");
assert(page.includes("httpNodeMiddleware"));
assert(page.includes("bcrypt.compareSync"));
console.log("Protected manual temperature page tests passed: guarded writes, source-of-truth, per-BMS status, CRC, no optimistic state");
