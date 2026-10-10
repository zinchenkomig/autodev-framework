import type { NextConfig } from 'next'

// In production the ingress routes /api to the API service. For local development
// set API_PROXY=http://localhost:8000 to proxy it through Next instead.
const apiProxy = process.env.API_PROXY

const nextConfig: NextConfig = {
  output: 'standalone',
  // FastAPI collection routes end with '/'; don't let Next redirect them away.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    if (!apiProxy) return []
    return [
      // keep the trailing slash: FastAPI collection routes are '/api/tasks/'
      { source: '/api/:path*/', destination: `${apiProxy}/api/:path*/` },
      { source: '/api/:path*', destination: `${apiProxy}/api/:path*` },
    ]
  },
}

export default nextConfig
