import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {EventEmitter} from "node:events";

function fixture(denied=false) {
  const timers=new Map(); let stopped=0, requests=0, ended=0;
  const track={readyState:"live",stop(){stopped++;}};
  const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
  class Peer extends EventEmitter {
    static instance;
    constructor(...args){super();this.options=args[3];this.stops=0;Peer.instance=this;}
    stop(){this.stops++;return Promise.resolve();}
    end(){}
    reconnect(){this.emit("call-start");return Promise.resolve();}
  }
  const context=vm.createContext({
    Vapi:Peer,useRef:value=>({current:value}),useEffect:()=>{},
    navigator:{mediaDevices:{getUserMedia:()=>denied
      ? Promise.reject(Object.assign(new Error("Denied"),{name:"NotAllowedError"}))
      : Promise.resolve(stream)}},
    setTimeout:(fn,ms)=>{const id={};timers.set(id,{fn,ms});return id;},
    clearTimeout:id=>timers.delete(id),AbortSignal,
    fetch:async()=>{requests++;return {ok:true,json:async()=>({id:"test-room",webCallUrl:"test-url"})};},
  });
  const source=readFileSync(new URL("../app/web-voice.js",import.meta.url),"utf8")
    .replace(/^import .*;$/gm,"").replace("export function useWebVoice","function useWebVoice");
  vm.runInContext(source,context);
  const voice=context.useWebVoice({session:"test-session",onCallStart(){},onCallEnd(){ended++;},onError(){},onTranscript(){}});
  return {voice,timers,Peer,get stopped(){return stopped;},get requests(){return requests;},get ended(){return ended;}};
}

test("microphone denial creates no room",async()=>{
  const f=fixture(true);
  await assert.rejects(f.voice.prepareCall(),/MICROPHONE_DENIED/);
  assert.equal(f.requests,0);
});

test("consented room receives the live microphone track and explicit hang-up releases it",async()=>{
  const f=fixture();
  await f.voice.prepareCall();
  assert.equal(f.requests,0);
  assert.equal(f.Peer.instance.options.audioSource.readyState,"live");
  await f.voice.startCall();
  assert.equal(f.requests,1);
  await f.voice.endCall();
  assert.equal(f.stopped,1);
});

test("remote hang message allows buffered goodbye audio to drain before cleanup",async()=>{
  const f=fixture();
  await f.voice.prepareCall();await f.voice.startCall();
  const peer=f.Peer.instance;
  peer.emit("message",{type:"hang"});
  assert.equal(peer.stops,0);
  assert.equal(f.ended,0);
  const drain=[...f.timers.values()].find(t=>t.ms===1500);
  assert.ok(drain);
  drain.fn();
  assert.equal(peer.stops,1);
  assert.equal(f.ended,1);
  assert.equal(f.stopped,1);
});
