"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const root=path.join(__dirname,"..","smart-jkbms-bluetooth");
const pkg=JSON.parse(fs.readFileSync(path.join(root,"mqtt_flows.json"),"utf8"));
const fn=pkg.find(n=>n.id==="b200000000000002");
assert(fn&&fn.outputs===1);
const emitter=new Function("msg","context","env","Buffer","Date",fn.func);
const ctx=new Map();
const context={get:k=>ctx.get(k),set:(k,v)=>ctx.set(k,v)};
const macA="C8:47:80:1A:1A:EF",macB="C8:47:80:1A:27:12";
const env={get:k=>({
 BLE_MQTT_ENABLED:"true",BLE_BRIDGE_TOKEN:"TEST_PRIVATE_TOKEN"})[k]};
const call=e=>emitter({payload:e},context,env,Buffer,Date);
function raw(mac,type=2,seq=5){
 const b=Buffer.alloc(300);
 b.set([0x55,0xAA,0xEB,0x90,type,seq],0);
 if(type===2){
  for(let i=0;i<16;i++)b.writeUInt16LE(3200+i,6+2*i);
  b.writeUInt32LE(0xFFFF,70);
  b.writeUInt32LE(51200,150);b[173]=21;
  b.writeInt16LE(165,162);b.writeInt16LE(165,164);
  b.writeInt16LE(186,144);
  b.writeUInt32LE(68000,174);b.writeUInt32LE(123000,186);
  b[190]=96;b.writeInt16LE(53,170);b[172]=1;
  b.writeUInt32LE(4600,194);
  b[200]=1;b[215]=0;b[280]=0;
  b[281]=0x06; // DRY1 + DRY2 are active.
  b.writeUInt16LE(90,218);     // Emergency countdown 90 seconds
  b.writeInt16LE(1234,236);   // Heating current 1.234 A
  b.writeUInt32LE(7200,270);  // Smart sleep countdown (seconds)
  b.writeUInt16LE(45,278);    // Charge status elapsed
  b.writeUInt32LE(29,266);    // Detailed log records
  b[275]=0;                   // LiFePO4
  b.writeUInt16LE(7,202);     // Discharge OCP recovery
  b.writeUInt16LE(8,204);     // Discharge short recovery
  b.writeUInt16LE(9,206);     // Charge OCP recovery
  b.writeUInt16LE(10,208);    // Charge short recovery
  b.writeUInt16LE(11,210);    // Undervoltage recovery
  b.writeUInt16LE(12,212);    // Overvoltage recovery
  b[201]=1;
  b[245]=1;
  b[274]=0;
  b.writeUInt16LE(33,80);
  b.writeInt16LE(-2000,258);
 }
 b[299]=b.subarray(0,299).reduce((sum,v)=>(sum+v)&255,0);
 return {address:mac,type,sequence:seq,crc_ok:true,raw_hex:b.toString("hex").toUpperCase()};
}
const frame=raw(macA);
const framed=call(frame);
assert(framed);
assert.equal(JSON.parse(framed.payload).frame_type,2);
assert.equal(JSON.parse(framed.payload).kind,"frame");
assert.equal(JSON.parse(framed.payload).raw_hex,frame.raw_hex);
const data={
 address:macA,sequence:5,validation:"provisional_compare_with_BatMON",source_crc_ok:true,
 format:"JK02_32S",voltage_v:51.32,current_a:-0.5,power_w:-25.7,
 soc_pct:21,cell_count:16,
 cells:Array.from({length:16},(_,i)=>({number:i+1,voltage_v:3.2+i*.001})),
 temp1_c:null,temp2_c:null,mos_temp_c:null,electrical_data_only:true,
 temperature_quality:"all_unavailable_raw_minus200"
};
const out=call(data);
assert(out && out.method==="POST");
assert.equal(out.url,"http://127.0.0.1:1896/mqtt");
assert.equal(out.headers["X-BLE-Bridge-Token"],"TEST_PRIVATE_TOKEN");
const msg=JSON.parse(out.payload);
assert.equal(msg.kind,"telemetry");
assert.equal(msg.address,macA);
assert.equal(msg.extras.soh_pct,96);
assert.equal(msg.extras.capacity_remaining_ah,68);
assert.equal(msg.extras.balance_current_a,0.053);
assert.equal(msg.extras.temp3_c,null);
assert.equal(msg.extras.cell_01_resistance_ohm,0.033);
assert.equal(msg.extras.dry_contact_mask,6);
assert.equal(msg.extras.dry1_contact,true);
assert.equal(msg.extras.dry2_contact,true);
assert.equal(msg.extras.emergency_time_countdown_s,90);
assert.equal(msg.extras.emergency_active,true);
assert.equal(msg.extras.heating_current_a,1.234);
assert.equal(msg.extras.smart_sleep_countdown_s,7200);
assert.equal(msg.extras.charge_status_time_s,45);
assert.equal(msg.extras.detail_log_count,29);
assert.equal(msg.extras.battery_type,"LiFePO4");
assert.equal(msg.extras.discharge_ocp_release_s,7);
assert.equal(msg.extras.overvoltage_release_s,12);
assert.equal(msg.extras.balancing_active,true);
assert.equal(msg.extras.charger_connected,true);
assert.equal(msg.extras.total_runtime_formatted,"0j 01h 16m");
assert.equal(call({...data,source_crc_ok:false}),null);
const setting=call(raw(macB,1,7));
assert.equal(JSON.parse(setting.payload).kind,"frame");
assert.equal(JSON.parse(setting.payload).frame_type,1);
assert.equal(call({...raw(macA,1),raw_hex:"FF".repeat(300)}),null);
const lifecycle=call({address:macA,type:"disconnected"});
assert.equal(JSON.parse(lifecycle.payload).kind,"lifecycle");
const disabled={get:k=>k==="BLE_MQTT_ENABLED"?"false":env.get(k)};
assert.equal(emitter({payload:data},context,disabled,Buffer,Date),null);
const src=[
 ...JSON.parse(fs.readFileSync(path.join(root,"flows.json"),"utf8")),
 ...JSON.parse(fs.readFileSync(path.join(root,"decoder_flows.json"),"utf8"))
];
for(const origin of ["136f1472850339d1","65ad8ac512b5e001","b150100000000004"]){
 assert(src.find(n=>n.id===origin).wires[0].includes(fn.id),"Missing publisher edge from "+origin);
}
console.log("MQTT Node-RED mapping tests passed: 2 addresses, source checks, decoded extras, private token, lifecycle");