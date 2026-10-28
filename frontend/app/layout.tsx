import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppNav } from "@/components/AppNav";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TokenPilot",
  description: "Local AI usage, cost, and optimization ledger",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <TooltipProvider>
          <div className="flex min-h-screen flex-col md:flex-row">
            <aside className="border-b p-4 md:w-52 md:shrink-0 md:border-r md:border-b-0">
              <p className="mb-4 px-3 text-base font-semibold">TokenPilot</p>
              <AppNav />
            </aside>
            <main className="min-w-0 flex-1 p-6">{children}</main>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
