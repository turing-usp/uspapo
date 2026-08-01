import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* Testar mobile com cloudflare em dev */
  allowedDevOrigins: ["*.trycloudflare.com", "*.cfargotunnel.com"],
};

export default nextConfig;
