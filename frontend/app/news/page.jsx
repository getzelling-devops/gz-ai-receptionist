import PreviewAccess from "../preview-access";
import { notFound } from "next/navigation";
import NewsPreview from "../widget-preview";

export const dynamic = "force-dynamic";

export default function Page() {
  if (process.env.WIDGET_HOSTED_PREVIEW === "true") return <PreviewAccess />;
  if (process.env.NODE_ENV !== "development" || process.env.NEWS_PREVIEW_ENABLED !== "true") notFound();
  return <NewsPreview />;
}
