import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't let `next dev` generate an AGENTS.md file in the repository.
  agentRules: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
