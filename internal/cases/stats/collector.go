package stats

import (
	"github.com/pion/interceptor/pkg/gcc"
	"github.com/pion/interceptor/pkg/stats"
	"github.com/rs/zerolog/log"
	"strconv"
	"sync"
	"time"
	"webrtc-bench/internal/pion/scream"
	"webrtc-bench/internal/results"
	"webrtc-bench/internal/util"
)

type StatCollector interface {
	GetPionInterceptorFactory() *stats.InterceptorFactory
	SetInterval(interval time.Duration)
	StartCollection(streamID uint32, rtxID uint32)
	StopCollection()
	RecordRow(row results.ResultRow)
	AddGCCEstimatorCollection(bwe *gcc.SendSideBWE)
	AddScreamSenderCollection(bwe *scream.SenderInterceptor)
}

type statCollector struct {
	statsGetter             stats.Getter
	statsInterceptorFactory *stats.InterceptorFactory
	collectionInterval      time.Duration

	gccBwe   *gcc.SendSideBWE
	screamSi *scream.SenderInterceptor

	usingStopChannel   bool
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

func (sc *statCollector) RecordRow(row results.ResultRow) {
	sc.resultWriter.WriteRow(row)
}

func (sc *statCollector) AddGCCEstimatorCollection(bwe *gcc.SendSideBWE) {
	sc.gccBwe = bwe
}

func (sc *statCollector) AddScreamSenderCollection(screamSi *scream.SenderInterceptor) {
	sc.screamSi = screamSi
}

func (sc *statCollector) StartCollection(streamID uint32, rtxID uint32) {
	go func() {
		sc.usingStopChannel = true
		ticker := time.NewTicker(sc.collectionInterval)
		defer ticker.Stop()
		for {
			select {
			case <-sc.stopCollection:
				return
			case <-ticker.C:
				recordedStats := sc.statsGetter.Get(streamID)
				var gccStats *results.GCCStats
				var screamStats *results.ScreamStats

				if sc.gccBwe != nil {
					gccStatMap := sc.gccBwe.GetStats()
					gccStats = &results.GCCStats{
						LossTargetBitrate:  uint32(gccStatMap["lossTargetBitrate"].(int)),
						AverageLoss:        gccStatMap["averageLoss"].(float64),
						DelayTargetBitrate: uint32(gccStatMap["delayTargetBitrate"].(int)),
						DelayMeasurement:   gccStatMap["delayMeasurement"].(float64),
						DelayEstimate:      gccStatMap["delayEstimate"].(float64),
						DelayThreashold:    gccStatMap["delayThreshold"].(float64),
						Usage:              gccStatMap["usage"].(string),
						State:              gccStatMap["state"].(string),
					}
				}

				if sc.screamSi != nil {
					screamStatMap := sc.screamSi.GetStats()

					if _, ok := screamStatMap["targetBitrate"]; ok {
						if _, castOk := screamStatMap["targetBitrate"].(string); castOk {
							screamStats = &results.ScreamStats{
								QueueDelay:       util.AssumeNoErr(strconv.ParseFloat(screamStatMap["queueDelay"].(string), 64)),
								QueueDelayMax:    util.AssumeNoErr(strconv.ParseFloat(screamStatMap["queueDelayMax"].(string), 64)),
								QueueDelayMinAvg: util.AssumeNoErr(strconv.ParseFloat(screamStatMap["queueDelayMinAvg"].(string), 64)),
								CWND:             uint32(util.AssumeNoErr(strconv.ParseUint(screamStatMap["cwnd"].(string), 10, 32))),
								BytesInFlightLog: uint32(util.AssumeNoErr(strconv.ParseUint(screamStatMap["bytesInFlightLog"].(string), 10, 32))),
								IsInFastStart:    screamStatMap["isInFastStart"].(string) == "1",
								TargetBitrate:    uint32(util.AssumeNoErr(strconv.ParseUint(screamStatMap["targetBitrate"].(string), 10, 32))),
							}
						}
					}
				}

				var rtxBytesReceived uint64
				var rtxPacketsReceived uint64
				var rtxPacketsSent uint64
				var rtxBytesSent uint64
				if streamID != rtxID && rtxID != 0 {
					rtxStats := sc.statsGetter.Get(rtxID)
					if rtxStats != nil {
						rtxBytesReceived = rtxStats.InboundRTPStreamStats.BytesReceived
						rtxPacketsReceived = rtxStats.InboundRTPStreamStats.PacketsReceived
						rtxBytesSent = rtxStats.OutboundRTPStreamStats.BytesSent
						rtxPacketsSent = rtxStats.OutboundRTPStreamStats.PacketsSent
					}
				}

				now := time.Now()
				sc.resultWriter.WriteRow(results.ResultRow{
					Timestamp: now,
					InboundRTP: results.ResultRowInboundRTP{
						PacketsReceived:              recordedStats.InboundRTPStreamStats.PacketsReceived + rtxPacketsReceived,
						PacketsLost:                  recordedStats.InboundRTPStreamStats.PacketsLost,
						RoundTripTime:                float64(recordedStats.RemoteOutboundRTPStreamStats.RoundTripTime.Milliseconds()) / 1000.0,
						Jitter:                       recordedStats.InboundRTPStreamStats.Jitter,
						MillisSinceLastPacket:        uint64(now.Sub(recordedStats.InboundRTPStreamStats.LastPacketReceivedTimestamp).Milliseconds()),
						HeaderBytesReceived:          recordedStats.InboundRTPStreamStats.HeaderBytesReceived,
						BytesReceived:                recordedStats.InboundRTPStreamStats.BytesReceived + rtxBytesReceived,
						FIRCount:                     recordedStats.InboundRTPStreamStats.FIRCount,
						PLICount:                     recordedStats.InboundRTPStreamStats.PLICount,
						NACKCount:                    recordedStats.InboundRTPStreamStats.NACKCount,
						RetransmittedBytesReceived:   &rtxBytesReceived,
						RetransmittedPacketsReceived: &rtxPacketsReceived,
					},
					OutboundRTP: results.ResultRowOutboundRTP{
						PacketsSent:     recordedStats.OutboundRTPStreamStats.PacketsSent + rtxPacketsSent,
						RoundTripTime:   float64(recordedStats.RemoteOutboundRTPStreamStats.RoundTripTime.Milliseconds()) / 1000.0,
						BytesSent:       recordedStats.OutboundRTPStreamStats.BytesSent + rtxBytesSent,
						HeaderBytesSent: recordedStats.OutboundRTPStreamStats.HeaderBytesSent,
						NACKCount:       recordedStats.OutboundRTPStreamStats.NACKCount,
						FIRCount:        recordedStats.OutboundRTPStreamStats.FIRCount,
						PLICount:        recordedStats.OutboundRTPStreamStats.PLICount,
					},
					GCCStats:    gccStats,
					ScreamStats: screamStats,
				})
			}
		}
	}()
}

func (sc *statCollector) StopCollection() {
	sc.stopCollectionOnce.Do(func() {
		if sc.usingStopChannel {
			sc.stopCollection <- true
			close(sc.stopCollection)
		}
		sc.resultWriter.Close()
	})
}
