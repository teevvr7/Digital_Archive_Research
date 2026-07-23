import type { NextConfig } from "next";

// The upload page's camera capture (app/(app)/upload/page.tsx) uses a plain
// `<input capture="environment">` file picker, not the getUserMedia() JS API,
// so locking down the `camera` permission here doesn't break it.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(), camera=(), microphone=()" },
];

const nextConfig: NextConfig = {
  /* config options here */
  // Allows phones/other devices on the LAN to load dev-server resources (HMR, JS chunks)
  // when testing via http://192.168.0.56:3000 instead of localhost.
  allowedDevOrigins: ["192.168.0.56"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
