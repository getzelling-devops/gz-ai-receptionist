"use client";

import dynamic from "next/dynamic";

const Widget = dynamic(() => import("./news/preview"), { ssr: false });

export default function Preview(props) {
  return <Widget {...props} />;
}
