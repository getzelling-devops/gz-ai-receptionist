import "./styles.css";

export const metadata = { title: "GetZelling receptionist" };

export default function Layout({ children }) {
  // Browser extensions can add attributes to body before React hydrates.
  // Limit suppression to this element; mismatches inside the app stay visible.
  return <html lang="en"><body suppressHydrationWarning>{children}</body></html>;
}
