// Adjusted from https://github.com/pion/interceptor/tree/feat/scream-cgo-update
// Originally authored by @mengelbart

package scream

import (
	"time"

	"github.com/pion/interceptor"
	"github.com/pion/rtp"
)

type BandwidthEstimator interface {
	GetTargetBitrate(ssrc uint32) (int, error)
	GetStats() map[string]interface{}
}

type NewPeerConnectionCallback func(id string, estimator BandwidthEstimator)

// RTPQueue implements the packet queue which will be used by SCReAM to buffer packets
type RTPQueue interface {
	// Enqueue adds a new packet to the end of the queue.
	Enqueue(packet *rtp.Packet, ts float64)
	// Dequeue removes and returns the first packet in the queue.
	Dequeue() *rtp.Packet
}

type localStream struct {
}

type SenderInterceptorFactory struct {
	opts              []SenderOption
	addPeerConnection NewPeerConnectionCallback
}

func NewSenderInterceptor(opts ...SenderOption) (*SenderInterceptorFactory, error) {
	panic("not implemented on windows")
}

func (f *SenderInterceptorFactory) OnNewPeerConnection(cb NewPeerConnectionCallback) {
	panic("not implemented on windows")
}

func (f *SenderInterceptorFactory) NewInterceptor(id string) (interceptor.Interceptor, error) {
	panic("not implemented on windows")
}

type SenderInterceptor struct {
}

func (s *SenderInterceptor) getTimeNTP(t time.Time) uint64 {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) BindRTCPReader(reader interceptor.RTCPReader) interceptor.RTCPReader {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) BindLocalStream(info *interceptor.StreamInfo, writer interceptor.RTPWriter) interceptor.RTPWriter {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) UnbindLocalStream(info *interceptor.StreamInfo) {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) Close() error {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) GetTargetBitrate(ssrc uint32) (int, error) {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) GetTotalTargetBitrate() int {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) GetStats() map[string]interface{} {
	panic("not implemented on windows")
}

func (s *SenderInterceptor) isClosed() bool {
	panic("not implemented on windows")
}
