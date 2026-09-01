import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sleeper Overseer",
  description: "AFK task overseer for Sleeper Agent on Solari",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
