import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Allows phones/other devices on the LAN to load dev-server resources (HMR, JS chunks)
  // when testing via http://192.168.0.56:3000 instead of localhost.
  allowedDevOrigins: ["192.168.0.56"],
};

export default nextConfig;
