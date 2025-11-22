docker buildx  build --platform linux/amd64,linux/arm64 . -t "docker.io/yannismate/webrtc-bench:latest"
docker buildx  build --platform linux/amd64,linux/arm64 -f .\auto-receiver.Dockerfile -t "docker.io/yannismate/webrtc-bench-auto-receiver:v1.8" .
docker buildx  build --platform linux/amd64,linux/arm64 -f .\auto-sender.Dockerfile -t "docker.io/yannismate/webrtc-bench-auto-sender:v1.8" .