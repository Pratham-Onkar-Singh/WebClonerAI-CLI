import type { Metadata } from "next";
import "./style.css";

export const metadata: Metadata = { title: "WebCloner · Execution audit", description: "Local, read-only policy event viewer" };

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
