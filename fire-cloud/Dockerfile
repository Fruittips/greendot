# Use the Node.js 16 Alpine image as a parent image
FROM python:3.11-alpine

WORKDIR /usr/src/app

COPY requirements.txt .

RUN rm -rf /var/cache/apk/*

RUN pip install -r requirements.txt

COPY . .

EXPOSE 3000

ENV NODE_ENV=production