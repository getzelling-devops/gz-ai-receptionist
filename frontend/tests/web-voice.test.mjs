import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {EventEmitter} from "node:events";

function fixture(denied=false, extra={}) {
  const timers=new Map(); let stopped=0, requests=0, ended=0;
  const track={readyState:"live",stop(){stopped++;}};
  const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
  class Peer extends EventEmitter {
    static instance;
    constructor(...args){super();this.options=args[3];this.stops=0;Peer.instance=this;}
    stop(){this.stops++;return Promise.resolve();}
    end(){}
    reconnect(){this.emit("call-start");return Promise.resolve();}
    setMuted(value){this.muted=value;}
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
  const voice=context.useWebVoice({session:"test-session",onCallStart(){},onCallEnd(){ended++;},onError(){},onTranscript(){},...extra});
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

test("speaking and partial transcripts are reported for display and final lines are unchanged",async()=>{
  const seen={speech:[],partial:[],final:[]};
  const f=fixture(false,{onSpeechChange:v=>seen.speech.push(v),onPartialTranscript:t=>seen.partial.push(t.text),onTranscript:t=>seen.final.push(t.text)});
  await f.voice.prepareCall();await f.voice.startCall();
  const peer=f.Peer.instance;
  peer.emit("speech-start");peer.emit("speech-end");
  peer.emit("message",{type:"transcript",transcriptType:"partial",role:"assistant",transcript:"Hello"});
  peer.emit("message",{type:"transcript",transcriptType:"final",role:"assistant",transcript:"Hello there"});
  assert.deepEqual(seen.speech,[true,false]);
  assert.deepEqual(seen.partial,["Hello"]);
  assert.deepEqual(seen.final,["Hello there"]);
});

test("mute stops sending microphone audio without ending the call",async()=>{
  const f=fixture();
  await f.voice.prepareCall();await f.voice.startCall();
  f.voice.setMuted(true);
  assert.equal(f.Peer.instance.muted,true);
  assert.equal(f.ended,0);
  assert.equal(f.stopped,0);
  f.voice.setMuted(false);
  assert.equal(f.Peer.instance.muted,false);
});

test("duplicate SDK call-start events announce a single call",async()=>{
  let started=0;
  const f=fixture(false,{onCallStart(){started++;}});
  await f.voice.prepareCall();await f.voice.startCall();
  f.Peer.instance.emit("call-start");f.Peer.instance.emit("call-start");
  assert.equal(started,1);
});

test("setup timeout cannot disconnect an already active call",async()=>{
  const f=fixture();
  await f.voice.prepareCall();
  f.Peer.instance.reconnect=function(){this.emit("call-start");return new Promise(()=>{});};
  const pending=f.voice.startCall();
  await new Promise(resolve=>setImmediate(resolve));
  const timeout=[...f.timers.values()].find(t=>t.ms===35000);
  assert.ok(timeout);timeout.fn();await pending;
  assert.equal(f.Peer.instance.stops,0);
  assert.equal(f.stopped,0);
});

test("an unexplained active-call end is reported as an interruption",async()=>{
  const outcomes=[];
  const f=fixture(false,{onCallEnd(value){outcomes.push(value);}});
  await f.voice.prepareCall();await f.voice.startCall();
  f.Peer.instance.emit("call-end");
  assert.equal(outcomes[0].unexpected,true);
});
