module webrtc-bench

go 1.23.0

toolchain go1.23.4

require (
	github.com/chromedp/cdproto v0.0.0-20250530212709-4dcc110a7b92
	github.com/chromedp/chromedp v0.13.6
	github.com/google/uuid v1.6.0
	github.com/gorilla/websocket v1.5.3
	github.com/mengelbart/scream-go v0.4.0
	github.com/mengelbart/syncodec v0.0.0-20220105132658-94ec57e63a65
	github.com/parquet-go/parquet-go v0.25.1
	github.com/pion/interceptor v0.1.38
	github.com/pion/logging v0.2.3
	github.com/pion/rtcp v1.2.15
	github.com/pion/rtp v1.8.18
	github.com/pion/webrtc/v4 v4.1.1
	github.com/rs/zerolog v1.34.0
)

require (
	github.com/andybalholm/brotli v1.1.0 // indirect
	github.com/chromedp/sysutil v1.1.0 // indirect
	github.com/go-json-experiment/json v0.0.0-20250211171154-1ae217ad3535 // indirect
	github.com/gobwas/httphead v0.1.0 // indirect
	github.com/gobwas/pool v0.2.1 // indirect
	github.com/gobwas/ws v1.4.0 // indirect
	github.com/klauspost/compress v1.17.9 // indirect
	github.com/mattn/go-colorable v0.1.14 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/pierrec/lz4/v4 v4.1.21 // indirect
	github.com/pion/datachannel v1.5.10 // indirect
	github.com/pion/dtls/v3 v3.0.6 // indirect
	github.com/pion/ice/v4 v4.0.10 // indirect
	github.com/pion/mdns/v2 v2.0.7 // indirect
	github.com/pion/randutil v0.1.0 // indirect
	github.com/pion/sctp v1.8.39 // indirect
	github.com/pion/sdp/v3 v3.0.13 // indirect
	github.com/pion/srtp/v3 v3.0.5 // indirect
	github.com/pion/stun/v3 v3.0.0 // indirect
	github.com/pion/transport/v3 v3.0.7 // indirect
	github.com/pion/turn/v4 v4.0.2 // indirect
	github.com/wlynxg/anet v0.0.5 // indirect
	golang.org/x/crypto v0.39.0 // indirect
	golang.org/x/net v0.41.0 // indirect
	golang.org/x/sys v0.33.0 // indirect
)

replace github.com/pion/webrtc/v4 => github.com/yannismate/pion-webrtc/v4 v4.0.0-20250607154802-f28561f574be

replace github.com/pion/interceptor => github.com/yannismate/pion-interceptor v0.1.38-0.20250608214943-27e552b832ea
