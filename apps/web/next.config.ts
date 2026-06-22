import type { NextConfig } from "next";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Autorise les ressources de dev (HMR /_next/webpack-hmr) depuis localhost et
  // 127.0.0.1. Sans cela, Next bloque le WebSocket HMR en cross-origin et le
  // client de dev recharge la page en boucle sur les routes lourdes.
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
