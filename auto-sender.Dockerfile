FROM golang:1.24 AS build

WORKDIR /go/src

RUN go install github.com/heistp/irtt/cmd/irtt@latest

ADD go.mod /go/src
ADD go.sum /go/src
RUN go mod download

ADD cmd /go/src/cmd
ADD internal /go/src/internal
RUN go build -o /go/bin/orchestrator cmd/orchestrator/orchestrator.go
RUN go build -o /go/bin/peer cmd/peer/peer.go


FROM debian:13
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /root
ADD testdata /root/testdata
RUN apt-get update && apt-get install -y libglib2.0-0 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libnss3 libxrandr2 libgbm1 libxkbcommon0 libasound2 iproute2 iperf3 ffmpeg libopenh264-dev libopenh264-8 \
    ca-certificates libavcodec-extra chromium-headless-shell

COPY --from=build /go/bin /bin
ADD bin/gcc_tester_${TARGETARCH} /root/bin/gcc_tester
ADD bin/headless_shell_${TARGETARCH} /root/bin/headless_shell
RUN mv /bin/irtt /root/bin/irtt

CMD ["/bin/peer", "--server", "135.220.32.39:8080", "--name", "sender", "--v"]