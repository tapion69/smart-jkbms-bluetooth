"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const flows=JSON.parse(fs.readFileSync(path.join(__dirname,"..","smart-jkbms-bluetooth","decoder_flows.json"),"utf8"));
const node=flows.find(n=>n.id==="b150100000000004");
assert(node,"JK02 decoder Node-RED function missing");
const parse=new Function("msg","context","node","Buffer",node.func);
const stored=new Map(),ctx={get:k=>stored.get(k),set:(k,v)=>stored.set(k,v)},status={status:()=>{}};
function sample(type) {
  const b=Buffer.alloc(300);
  b.set([0x55,0xAA,0xEB,0x90,0x02,0x12],0);
  const slotMask=type==="JK02_32S"?70:54;
  const v=type==="JK02_32S"?150:118;
  const cur=type==="JK02_32S"?158:126;
  const soc=type==="JK02_32S"?173:141;
  const temp=type==="JK02_32S"?[162,164,144]:[130,132,134];
  const nominal=type==="JK02_32S"?178:146;
  const cycles=type==="JK02_32S"?182:150;
  const charge=type==="JK02_32S"?198:166,discharge=type==="JK02_32S"?199:167;
  for(let i=0;i<16;i++) b.writeUInt16LE(3300+i,6+2*i);
  const cellSum=Array.from({length:16},(_,i)=>3300+i).reduce((a,v)=>a+v,0);
  b.writeUInt32LE(0x0000FFFF,slotMask);
  b.writeUInt32LE(cellSum,v); // millivolts
  b.writeInt32LE(-1250,cur);
  b[soc]=76;
  b.writeInt16LE(245,temp[0]);
  b.writeInt16LE(260,temp[1]);
  b.writeInt16LE(310,temp[2]);
  b.writeUInt32LE(100000,nominal);
  b.writeUInt32LE(21,cycles);
  b[charge]=1;
  b[discharge]=1;
  b[299]=b.subarray(0,299).reduce((s,x)=>(s+x)&255,0);
  return b;
}
function run(b) {
 return parse({payload:{type:2,address:"C8:47:80:1A:27:12",crc_ok:true,raw_hex:b.toString("hex").toUpperCase(),sequence:44}},ctx,status,Buffer);
}
for(const format of ["JK02_24S","JK02_32S"]){
 const result=run(sample(format));
 assert(result&&result[0]&&result[0].payload,format+" should decode");
 assert.equal(result[1],null);
 const p=result[0].payload;
 assert.equal(p.format,format);
 assert.equal(p.cell_count,16);
 assert.equal(p.soc_pct,76);
 assert.equal(p.current_a,-1.25);
 assert(p.voltage_v>52 && p.voltage_v<54);
 assert.equal(p.cells.length,16);
 assert.equal(p.validation,"provisional_compare_with_BatMON");
 assert.equal(p.cycles,21);
}
// BMS 1: JK02_32S electrical data is valid, but one temperature probe
// reports an out-of-range sentinel. Do not suppress the whole battery.
for (const [index, key, label] of [[0,"temp1_c","T1"],[1,"temp2_c","T2"],[2,"mos_temp_c","MOS"]]){
 const faulty=sample("JK02_32S");
 faulty.writeInt16LE(32767,[162,164,144][index]);
 faulty[299]=faulty.subarray(0,299).reduce((s,v)=>(s+v)&255,0);
 const decoded=run(faulty);
 assert(decoded&&decoded[0],"One invalid "+label+" must not reject sound pack readings");
 const p=decoded[0].payload;
 assert.equal(p.format,"JK02_32S");
 assert.equal(p.cell_count,16);
 assert.equal(p.soc_pct,76);
 assert.equal(p[key],null,"Invalid channel must not appear as 0°C");
 assert.equal(p.temperature_quality,"partial_unverified");
 assert.deepEqual(p.invalid_temperature_channels,[label]);
 assert.equal(p.invalid_temperature_raw_tenths[label],32767);
 for (const [other,name] of [["temp1_c","T1"],["temp2_c","T2"],["mos_temp_c","MOS"]]){
   if(name!==label)assert(Number.isFinite(p[other]));
 }
}
const twoFaulty=sample("JK02_32S");
twoFaulty.writeInt16LE(32767,162);
twoFaulty.writeInt16LE(32767,144);
twoFaulty[299]=twoFaulty.subarray(0,299).reduce((s,v)=>(s+v)&255,0);
const unsafe=run(twoFaulty);
assert(!unsafe || !unsafe[0],"Two implausible probes remain rejected");
const badCells=sample("JK02_32S");
badCells.writeUInt16LE(9000,6);
badCells[299]=badCells.subarray(0,299).reduce((s,v)=>(s+v)&255,0);
const invalidElectrical=run(badCells);
assert(!invalidElectrical || !invalidElectrical[0],"Unsafe electrical data stays rejected");

const empty=Buffer.alloc(300);empty.set([0x55,0xAA,0xEB,0x90,2,9]);empty[299]=empty.subarray(0,299).reduce((s,v)=>(s+v)&255,0);
const rejected=run(empty);assert.equal(rejected[0],null);assert.equal(rejected[1].payload.reason,"no_plausible_profile");
const invalid=sample("JK02_32S");invalid[299]^=0xff;
assert.equal(run(invalid),null);
const sourceFiles=flows.filter(n=>n.type==="mqtt out" || n.type==="mqtt in");
assert.equal(sourceFiles.length,0);
console.log("JK02 profile decoder tests passed: 24S, 32S, invalid, CRC and no MQTT");
