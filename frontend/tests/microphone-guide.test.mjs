import test from "node:test";
import assert from "node:assert/strict";
import {microphoneBrowser,microphoneGuides} from "../app/microphone-guide.mjs";

test("selects the right microphone guidance across mobile browsers",()=>{
  assert.equal(microphoneBrowser("iPhone Safari/604.1"),"ios-safari");
  assert.equal(microphoneBrowser("iPhone CriOS/143 Safari/604.1"),"ios-chrome");
  assert.equal(microphoneBrowser("Macintosh Safari/604.1",5),"ios-safari");
  assert.equal(microphoneBrowser("Android Chrome/143 Mobile Safari/537.36"),"android-chrome");
  assert.equal(microphoneBrowser("Android SamsungBrowser/28 Chrome/143"),"other");
  assert.equal(microphoneBrowser("iPhone GSA/123 Safari/604.1"),"other");
  assert.equal(microphoneBrowser("iPhone FxiOS/130 Safari/604.1"),"other");
});
test("all guidance is bilingual and links only official browser help",()=>{
  for (const guide of Object.values(microphoneGuides)) {
    assert.equal(guide.en.length,3);assert.equal(guide.es.length,3);
    if(guide.url) assert.match(new URL(guide.url).hostname,/^support\.(apple|google)\.com$/);
  }
});
