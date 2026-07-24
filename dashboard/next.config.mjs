/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // "standalone" breaks `next start` (used by local/systemd runs), so it's
  // only enabled for the Docker image build (Dockerfile sets DOCKER_BUILD=1).
  output: process.env.DOCKER_BUILD === "1" ? "standalone" : undefined,
};

export default nextConfig;
