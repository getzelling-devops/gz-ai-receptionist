"use client";

import dynamic from "next/dynamic";

export const preloadWidget = () => import("./news/preview");
const Widget = dynamic(preloadWidget, { ssr: false });

export default function Preview(props) {
  return <Widget {...props} />;
}
