import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";
import { ThemeScript } from "@/components/theme";

// Both named for the family they load, and both read by `@theme` under
// those names. The sans one used to be called `--font-sans`, which is also
// the name Tailwind gives the resolved theme value -- one variable
// standing for two things, each defined in terms of the other.
const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Baton", template: "%s · Baton" },
  description:
    "Customer conversations for small businesses, answered by your team and helped along by an assistant that knows your catalogue.",
};

/**
 * `children` typed by hand rather than with Next's generated `LayoutProps`.
 *
 * That global comes from `.next/types`, which only exists once something
 * has built, so a checkout that runs `tsc --noEmit` before `next build` --
 * which is exactly what CI does -- cannot resolve it. The root layout has
 * no route parameters, so the generic bought nothing to pay that with, and
 * this matches the two layouts below it.
 *
 * A screen that does want typed route params has to build first. Worth
 * knowing before adding one, rather than finding out from a red run.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // The script below adds `dark` to this element before React sees it.
      // Without this, that correction is reported as a hydration error on
      // every dark-mode page load.
      suppressHydrationWarning
    >
      <body className="min-h-full">
        <ThemeScript />
        {children}
      </body>
    </html>
  );
}
