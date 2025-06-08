# Orchestrator requires mounting case file at /root/cases.json and results folder at /root/results
FROM node:24 AS chrome-download

WORKDIR /tmp
RUN npx --yes @puppeteer/browsers install chrome-headless-shell@stable
RUN mv ./chrome-headless-shell/linux-*/chrome-headless-shell-linux64 ./headless-shell

FROM golang:1.24 AS build

WORKDIR /go/src

ADD go.mod /go/src
ADD go.sum /go/src
RUN go mod download

ADD cmd /go/src/cmd
ADD internal /go/src/internal
RUN go build -o /go/bin/orchestrator cmd/orchestrator/orchestrator.go
RUN go build -o /go/bin/peer cmd/peer/peer.go


FROM debian:12

WORKDIR /root
ADD testdata /root/testdata
RUN apt update && apt install -y libglib2.0-0 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libxcomposite1 libxdamage1 libxfixes3 libnss3 libxrandr2 libgbm1 libxkbcommon0 libasound2
COPY --from=chrome-download /tmp/headless-shell /opt/headless-shell
RUN ln -s /opt/headless-shell/chrome-headless-shell /opt/headless-shell/headless-shell
ENV PATH="$PATH:/opt/headless-shell"
COPY --from=build /go/bin /bin

ENTRYPOINT ["/bin/peer"]