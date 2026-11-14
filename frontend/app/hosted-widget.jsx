"use client";

import dynamic from "next/dynamic";

const Receptionist = dynamic(() => import("./receptionist"), { ssr: false });

export default function Page() {
  const publicKey = process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY;
  const assistantId = process.env.NEXT_PUBLIC_VAPI_ASSISTANT_ID;
  return <main className="mx-auto flex min-h-dvh w-full max-w-[450px] flex-col gap-5 p-5">
    <h1 className="font-medium text-xl text-navy">Ask Gizelle</h1>
    {publicKey && assistantId ? <Receptionist publicKey={publicKey} assistantId={assistantId} /> :
      <p>The receptionist is currently unavailable. <a className="underline" href="mailto:support@getzelling.com">Contact GetZelling</a>.</p>}
  </main>;
}
