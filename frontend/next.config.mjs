const isGithubPages = process.env.GITHUB_PAGES === 'true';
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || (isGithubPages ? '/underrail-respec-editor' : '');

const nextConfig = {
  output: 'export',
  trailingSlash: false,
  basePath: basePath || undefined,
  assetPrefix: basePath || undefined,
};

export default nextConfig;
