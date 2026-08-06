/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export so the judged demo is a single URL with no server to keep
  // running. Client-side mock mode makes the app fully interactive without it.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
