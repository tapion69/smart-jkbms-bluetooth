"use strict";
const fs = require("fs");

const secretPath = "/data/.nodered_credential_secret";
const secret = fs.readFileSync(secretPath, "utf8").trim();

module.exports = {
  uiHost: "0.0.0.0",
  uiPort: 1895,
  userDir: "/data/node-red",
  flowFile: "/data/node-red/flows.json",
  credentialSecret: secret,
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
