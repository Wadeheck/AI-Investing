import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI-Investing — Control Room",
  description: "Autonomous trading engine: equity, positions, decisions, and the evolving formula.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
