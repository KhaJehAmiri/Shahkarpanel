/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  // Dashboard pages will live under /dashboard/, but the subscription page
  // (the hero of phase 9) is served under /subscribe/. We use trailingSlash
  // so the static export produces folder-style URLs that match FastAPI's
  // StaticFiles(html=True) mount semantics.
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: true },
  // Allow embedding the static build under arbitrary FastAPI mount points.
  assetPrefix: process.env.NEXT_ASSET_PREFIX || "",
  basePath: "",
};

module.exports = nextConfig;
