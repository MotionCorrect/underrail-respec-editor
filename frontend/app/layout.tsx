import './globals.css';

export const metadata = {
  title: 'Underrail Visual Respec Editor',
  description: 'Local Underrail save respec UI',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
