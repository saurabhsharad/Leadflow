// Where the end-to-end tests run: the isolated leadflow-e2e stack
// (docker-compose.e2e.yml), never the production or development stacks.

export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3001";
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8001";
export const E2E_PROJECT = "leadflow-e2e";
// docker-compose.e2e.yml pins APP_TIMEZONE to this value.
export const APP_TIMEZONE = "Asia/Kolkata";
