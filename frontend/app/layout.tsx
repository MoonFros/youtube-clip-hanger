import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "../components/AppProvider";
import DisclaimerModal from "../components/DisclaimerModal";

export const metadata: Metadata = {
  title: "FairClip — AI Fair Use video clipping",
  description:
    "Turn long-form video into Shorts, Reels & TikToks with automatic Fair Use transformations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ink-950 font-sans antialiased">
        <AppProvider>
          {children}
          <DisclaimerModal />
        </AppProvider>
      </body>
    </html>
  );
}
