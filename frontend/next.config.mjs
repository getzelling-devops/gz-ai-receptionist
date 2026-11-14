import { fileURLToPath } from "node:url";

export default phase => ({
  distDir: phase === "phase-development-server" ? ".next-dev" : ".next",
  webpack(config) {
    config.resolve.alias["@vapi-ai/web$"] = fileURLToPath(new URL("./app/vapi-web.cjs", import.meta.url));
    return config;
  },
});
