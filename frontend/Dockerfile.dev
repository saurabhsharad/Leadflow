# Local-development image for the LeadFlow frontend: runs `next dev`.
# A production image would run `next build` + `next start` instead; since
# NEXT_PUBLIC_API_URL is inlined at build time, it would need to be a build arg.
FROM node:24-slim

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
