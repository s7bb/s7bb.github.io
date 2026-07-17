# Build stage: produce the static bundle. Node version matches .nvmrc and CI.
FROM node:22-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: nginx + the built bundle.
FROM nginx:1.27-alpine
# jq is required by docker-entrypoint.sh to write config.json safely.
RUN apk add --no-cache jq
COPY --from=build /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# The nginx image ships its own /docker-entrypoint.sh. Copy ours alongside it
# under a distinct name; ours chains to it so the base init still runs.
COPY docker-entrypoint.sh /docker-entrypoint-s7bb.sh
RUN chmod +x /docker-entrypoint-s7bb.sh
ENTRYPOINT ["/docker-entrypoint-s7bb.sh"]
CMD ["nginx", "-g", "daemon off;"]
