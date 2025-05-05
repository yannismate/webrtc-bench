package stats

import (
	"github.com/pion/interceptor/pkg/stats"
	"github.com/rs/zerolog/log"
	"sync"
	"time"
	"webrtc-bench/internal/results"
)

type StatCollector interface {
	GetPionInterceptorFactory() *stats.InterceptorFactory
	SetInterval(interval time.Duration)
	StartCollection(streamID uint32)
	StopCollection()
}

type statCollector struct {
	statsGetter             stats.Getter
	statsInterceptorFactory *stats.InterceptorFactory
	collectionInterval      time.Duration

	stopCollection     chan bool
	stopCollectionOnce sync.Once

	resultWriter results.ParquetResultsWriter
}

func NewStatCollector(resultWriter results.ParquetResultsWriter) StatCollector {
	statsInterceptorFactory, err := stats.NewInterceptor()
	if err != nil {
		log.Fatal().Err(err).Msg("stats.NewInterceptor() failed")
		return nil
	}

	sc := &statCollector{
		stopCollection: make(chan bool),
		resultWriter:   resultWriter,
	}

	statsInterceptorFactory.OnNewPeerConnection(func(_ string, g stats.Getter) {
		sc.statsGetter = g
	})

	sc.statsInterceptorFactory = statsInterceptorFactory

	return sc
}

func (sc *statCollector) GetPionInterceptorFactory() *stats.InterceptorFactory {
	return sc.statsInterceptorFactory
}

func (sc *statCollector) SetInterval(interval time.Duration) {
	sc.collectionInterval = interval
}

func (sc *statCollector) StartCollection(streamID uint32) {
	go func() {
		ticker := time.NewTicker(sc.collectionInterval)
		defer ticker.Stop()
		for {
			select {
			case <-sc.stopCollection:
				return
			case <-ticker.C:
				recordedStats := sc.statsGetter.Get(streamID)
				now := time.Now()
				sc.resultWriter.WriteRow(results.ResultRow{
					Timestamp: now,
					InboundRTP: results.ResultRowInboundRTP{
						PacketsReceived:       recordedStats.InboundRTPStreamStats.PacketsReceived,
						PacketsLost:           recordedStats.InboundRTPStreamStats.PacketsLost,
						Jitter:                recordedStats.InboundRTPStreamStats.Jitter,
						MillisSinceLastPacket: uint64(now.Sub(recordedStats.InboundRTPStreamStats.LastPacketReceivedTimestamp).Milliseconds()),
						HeaderBytesReceived:   recordedStats.InboundRTPStreamStats.HeaderBytesReceived,
						BytesReceived:         recordedStats.InboundRTPStreamStats.BytesReceived,
						FIRCount:              recordedStats.InboundRTPStreamStats.FIRCount,
						PLICount:              recordedStats.InboundRTPStreamStats.PLICount,
						NACKCount:             recordedStats.InboundRTPStreamStats.NACKCount,
					},
					OutboundRTP: results.ResultRowOutboundRTP{
						PacketsSent:     recordedStats.OutboundRTPStreamStats.PacketsSent,
						BytesSent:       recordedStats.OutboundRTPStreamStats.BytesSent,
						HeaderBytesSent: recordedStats.OutboundRTPStreamStats.HeaderBytesSent,
						NACKCount:       recordedStats.OutboundRTPStreamStats.NACKCount,
						FIRCount:        recordedStats.OutboundRTPStreamStats.FIRCount,
						PLICount:        recordedStats.OutboundRTPStreamStats.PLICount,
					},
				})
			}
		}
	}()
}

func (sc *statCollector) StopCollection() {
	sc.stopCollectionOnce.Do(func() {
		sc.stopCollection <- true
		close(sc.stopCollection)
		sc.resultWriter.Close()
	})
}
