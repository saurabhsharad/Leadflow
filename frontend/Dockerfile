# Production image for the LeadFlow frontend: `next build` with standalone output,
# served by Node. The development image is Dockerfile.dev.
#
# NEXT_PUBLIC_* values are inlined into the browser bundle when the app is built,
# so they are build arguments, not runtime variables: changing them means
# rebuilding the image. They are public by design; never pass secrets here.

# --- Dependencies (including dev tooling needed by the build) -------------------------
FROM node:24-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- Build ---------------------------------------------------------------------------
FROM node:24-slim AS builder

# The URL the *browser* uses to reach the API (not a container hostname).
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_APP_TIMEZONE=Asia/Kolkata

# Fail here rather than ship a bundle that cannot reach the API.
RUN test -n "$NEXT_PUBLIC_API_URL" \
    || { echo "The NEXT_PUBLIC_API_URL build argument is required." >&2; exit 1; }

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_APP_TIMEZONE=$NEXT_PUBLIC_APP_TIMEZONE \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- Runtime: only the standalone server and its static assets ------------------------
FROM node:24-slim AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app
# Owned by the unprivileged user so Next.js can write its runtime cache.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000
CMD ["node", "server.js"]
