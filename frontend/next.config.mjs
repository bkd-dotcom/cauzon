/** @type {import('next').NextConfig} */

// GitHub Pages serves the site from /<repo>, so asset and route URLs need that
// prefix. Left empty for local dev and any root-hosted deploy.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig = {
  // Static export so the judged demo is a single URL with no server to keep
  // running. Client-side replay makes the app fully interactive without one.
  output: "export",
  basePath,
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
