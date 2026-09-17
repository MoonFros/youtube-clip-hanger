/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy /api/* to FastAPI backend
  // This is what was failing with ECONNREFUSED - backend must be running on 0.0.0.0:8000
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8001/api/:path*',
      },
      {
        source: '/clips/:path*',
        destination: 'http://127.0.0.1:8001/clips/:path*',
      },
    ];
  },
  // For Arena preview: Next.js 14 binds to 0.0.0.0 via -H flag, which is enough.
  // For Next.js 15+, uncomment allowedDevOrigins:
  // experimental: {
  //   allowedDevOrigins: ['*.e2b.app'],
  // },
};

export default nextConfig;
