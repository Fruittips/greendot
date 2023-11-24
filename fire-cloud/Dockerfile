FROM node:20-alpine

WORKDIR /usr/src/app

COPY package*.json ./

RUN apk add --no-cache \
      python3 make g++ tar cmake

RUN rm -rf /var/cache/apk/*

RUN npm install tar

RUN npm install -g npm@latest && npm install --omit=dev

COPY . .

EXPOSE 3000

ENV NODE_ENV=production