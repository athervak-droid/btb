import "./globals.css";

export const metadata = {
  title: "BankerToolBench Leaderboard",
  description: "AI agents on investment-banking deliverables, scored against expert rubrics.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
