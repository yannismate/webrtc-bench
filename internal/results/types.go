package results

import (
	"time"
)

type ResultRow struct {
	Timestamp   time.Time
	InboundRTP  *ResultRowInboundRTP
	OutboundRTP *ResultRowOutboundRTP
	GCCStats    *GCCStats
	ScreamStats *ScreamStats
}

type ResultRowInboundRTP struct {
	PacketsReceived              uint64
	PacketsLost                  int64
	RoundTripTime                float64
	Jitter                       float64
	MillisSinceLastPacket        uint64
	HeaderBytesReceived          uint64
	BytesReceived                uint64
	FIRCount                     uint32
	PLICount                     uint32
	NACKCount                    uint32
	FramesReceived               *uint64
	FramesDropped                *uint64
	KeyFramesDecoded             *uint32
	FreezeCount                  *uint32
	TotalFreezesDuration         *float32
	RetransmittedBytesReceived   *uint64
	RetransmittedPacketsReceived *uint64
}

type ResultRowOutboundRTP struct {
	PacketsSent     uint64
	RoundTripTime   float64
	BytesSent       uint64
	HeaderBytesSent uint64
	NACKCount       uint32
	FIRCount        uint32
	PLICount        uint32
	FramesSent      *uint64
	TargetBitrate   *uint32
}

type GCCStats struct {
	LossTargetBitrate  uint32
	AverageLoss        float64
	DelayTargetBitrate uint32
	DelayMeasurement   float64
	DelayEstimate      float64
	DelayThreashold    float64
	Usage              string
	State              string
}

type ScreamStats struct {
	QueueDelay       float64
	QueueDelayMax    float64
	QueueDelayMinAvg float64
	sRTT             float64
	CWND             uint32
	BytesInFlightLog uint32
	IsInFastStart    bool
	TargetBitrate    uint32
}
