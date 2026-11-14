"use client";
import {useEffect, useState} from "react";
import {microphoneBrowser, microphoneGuides} from "./microphone-guide.mjs";

export default function MicrophoneHelp({language, blocked, onOpenTab}) {
  const [browser,setBrowser]=useState("other");
  useEffect(()=>setBrowser(microphoneBrowser(navigator.userAgent,navigator.maxTouchPoints)),[]);
  const es=language==="es";
  const guide=microphoneGuides[browser];
  return <section aria-label={es?"Ayuda con el micrófono":"Microphone help"} className="w-full text-xs leading-relaxed text-[#6E6656]">
    <p role={blocked?"alert":undefined}>{blocked
      ? (es?"El navegador no permitió el acceso al micrófono. Revise estos pasos y vuelva a intentarlo.":"Your browser did not allow microphone access. Follow these steps, then try Agree and call again.")
      : (es?"Al iniciar, el navegador puede pedir acceso al micrófono. Elija Permitir.":"Your browser may ask for microphone access when you start. Choose Allow.")}</p>
    {onOpenTab&&<button type="button" onClick={onOpenTab} className="min-h-11 text-navy underline underline-offset-4">{es?"Abrir voz en una pestaña nueva":"Open voice in a new tab"}</button>}
    <details open={blocked} className="mt-1 max-h-[220px] overflow-y-auto">
      <summary className="flex min-h-11 cursor-pointer items-center text-navy underline underline-offset-4">{es?"Cómo permitir el micrófono":"How to allow your microphone"}</summary>
      <label className="block">{es?"Su navegador":"Your browser"}
        <select value={browser} onChange={e=>setBrowser(e.target.value)} className="mt-1 block min-h-11 w-full rounded border border-bronze bg-white px-2 text-navy">
          {Object.entries(microphoneGuides).map(([id,g])=><option value={id} key={id}>{g.label}</option>)}
        </select>
      </label>
      <ol className="mt-3 list-decimal space-y-2 pl-5">{guide[language].map(step=><li key={step}>{step}</li>)}</ol>
      <p className="mt-3">{es?"Los nombres de los menús pueden variar según la versión.":"Menu names may vary with your browser version."}</p>
      {guide.url&&<a href={guide.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-navy underline">{es?"Ayuda oficial del navegador":"Official browser help"}</a>}
    </details>
  </section>;
}
