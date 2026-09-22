import http from "node:http";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

function rovCamProxy() {
  return {
    name: "rov-cam-proxy",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const raw = req.url || "";
        if (!raw.startsWith("/rov-cam")) return next();
        let host = "172.20.10.3";
        try {
          host = new URL(raw, "http://127.0.0.1").searchParams.get("host") || host;
        } catch {
          /* keep default */
        }
        if (!/^[A-Za-z0-9.:-]+$/.test(host)) {
          res.statusCode = 400;
          res.end("bad host");
          return;
        }
        const upstream = http.request(
          { hostname: host, port: 5000, path: "/video", method: "GET", timeout: 15000 },
          (up) => {
            res.writeHead(up.statusCode || 200, {
              "Content-Type":
                up.headers["content-type"] || "multipart/x-mixed-replace; boundary=frame",
              "Cache-Control": "no-store",
            });
            up.pipe(res);
          },
        );
        upstream.on("error", () => {
          if (!res.headersSent) res.statusCode = 502;
          res.end();
        });
        req.on("close", () => upstream.destroy());
        upstream.end();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), rovCamProxy()],
});

