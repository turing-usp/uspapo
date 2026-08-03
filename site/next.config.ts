import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.join(__dirname),
  },
  /* Testar mobile com cloudflare em dev */
  allowedDevOrigins: ["*.trycloudflare.com", "*.cfargotunnel.com"],
};

export default nextConfig;
