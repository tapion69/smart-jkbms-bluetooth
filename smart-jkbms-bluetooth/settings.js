"use strict";
const bcrypt = require("bcryptjs");
const fs = require("fs");

const user = process.env.NODE_RED_USER;
const password = process.env.NODE_RED_PASSWORD;
if (!user || !password) {
  throw new Error("Configure node_red_user and node_red_password in add-on options");
}

const secretPath = "/data/.nodered_credential_secret";
const secret = fs.readFileSync(secretPath, "utf8").trim();

module.exports = {
  uiHost: "0.0.0.0",
  uiPort: 1895,
  userDir: "/data/node-red",
  flowFile: "flows.json",
  credentialSecret: secret,
  adminAuth: {
    type: "credentials",
    users: [{
      username: user,
      password: bcrypt.hashSync(password, 10),
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
