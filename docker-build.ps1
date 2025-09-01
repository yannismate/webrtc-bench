docker build . -t "docker.io/yannismate/webrtc-bench:latest"
docker build -f .\auto-receiver.Dockerfile -t "docker.io/yannismate/webrtc-bench-auto-receiver:v1.8" .
docker build -f .\auto-sender.Dockerfile -t "docker.io/yannismate/webrtc-bench-auto-sender:v1.8" .