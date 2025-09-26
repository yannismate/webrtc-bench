package pinger

import (
	"time"
)

type ICMPPingData struct {
	Pings []Ping
}

type Ping struct {
	ReplyRecvTime time.Time
	Rtt           time.Duration
	Seq           int
	Ttl           int
}
