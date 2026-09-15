import "./globals.css";

export const metadata = {
  title: "ClawCompany",
  description: "AI Organization OS",
};

export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="vi"><body>{children}</body></html>;
}