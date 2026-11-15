import test from "node:test";
import assert from "node:assert/strict";
import {formatTranscriptPhones as format} from "../app/contact-format.mjs";
test("formats complete US callback numbers across fragmented transcripts",()=>{
 for(const value of ["954 77. 0. 8. 428","954-7. 708-428","9547708428","(954) 770-8428","+1 (954) 770-8428"])
   assert.equal(format("Phone: "+value+"."),"Phone: 954-770-8428.");
});
test("does not change email punctuation, dates, international numbers or partial numbers",()=>{
 for(const value of ["jmunoz@getzelling.com","j.munoz@getzelling.com","9547708428@example.com","2026-11-16 at 5:00 PM","954 770","+44 20 7946 0958","$1,000,000"])
   assert.equal(format(value),value);
});
