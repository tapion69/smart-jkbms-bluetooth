"use strict";
const fs = require("fs");

const secretPath = "/data/.nodered_credential_secret";
const secret = fs.readFileSync(secretPath, "utf8").trim();
const bcrypt = require("bcryptjs");
const piHash = "$2a$12$fTPLydFlFsX7N6x8zqbnke7eIGdXDHWp4uzzqSdpOJClmFDEw1Ifu";
function manualTempAuth(req,res,next) {
  if (!req.path.startsWith("/jk-bms/temperature")) return next();
  // Separate HTTP routes are NOT secured by Node-RED editor adminAuth.
  const raw = (req.headers.authorization || "").match(/^Basic (.+)$/i);
  let user = "", pass = "";
  try {
    const pair = Buffer.from(raw ? raw[1] : "", "base64").toString("utf8");
    const index = pair.indexOf(":");
    if (index >= 0) { user = pair.slice(0,index); pass = pair.slice(index+1); }
  } catch (_) {}
  if (user !== "pi" || !bcrypt.compareSync(pass,piHash)) {
    res.set("WWW-Authenticate",'Basic realm="JK-BMS manual controls"');
    return res.status(401).send("Authentication required");
  }
  if (req.method === "POST") {
    const origin = req.headers.origin;
    // Same-origin POST and a non-simple custom header prevent CSRF in browsers.
    try {
      if (!origin || new URL(origin).host !== req.headers.host ||
          req.headers["x-requested-with"] !== "JK-BMS-Control" ||
          !String(req.headers["content-type"] || "").startsWith("application/json")) {
        return res.status(403).send("Forbidden origin or headers");
      }
    } catch (_) { return res.status(403).send("Forbidden origin"); }
  }
  return next();
}

module.exports = {
  uiHost: "0.0.0.0",
  uiPort: 1895,
  userDir: "/data/node-red",
  flowFile: "/data/node-red/flows.json",
  credentialSecret: secret,
  httpNodeMiddleware: manualTempAuth,
  adminAuth: {
    type: "credentials",
    users: [{
      username: "pi",
      // Same bcrypt hash as Smart Voltronic. Never put a plaintext password here.
      password: "$2a$12$fTPLydFlFsX7N6x8zqbnke7eIGdXDHWp4uzzqSdpOJClmFDEw1Ifu",
      permissions: "*"
    }]
  },
  contextStorage: {
    default: {module: "localfilesystem"}
  },
  editorTheme: {projects: {enabled: false}},
  logging: {console: {level: "info", metrics: false, audit: false}},
  functionExternalModules: false,
  flowFilePretty: true
};
