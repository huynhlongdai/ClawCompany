import "./globals.css";

export const metadata = {
  title: "ClawCompany — AI Organization OS",
  description: "Số hoá công ty thật thành đội agent phối hợp làm việc",
};

export default function RootLayout({children}:{children:React.ReactNode}) {
  return (
    <html lang="vi">
      <head>
        {/* Inter cho giao diện, Instrument Serif cho dòng hiển thị lớn. Cặp
            này là ngôn ngữ của design canvas v17: sạch nhưng có chất biên
            tập, không phải font mặc định của hệ điều hành. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&family=Instrument+Serif:ital@0;1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
