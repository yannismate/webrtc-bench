// Adjusted from https://github.com/pion/interceptor/tree/feat/scream-cgo-update
// Originally authored by @mengelbart

package scream

import (
	"github.com/pion/interceptor"
)

type ReceiverInterceptorFactory struct{}

func (f *ReceiverInterceptorFactory) NewInterceptor(id string) (interceptor.Interceptor, error) {
	panic("not implemented on windows")
}

func NewReceiverInterceptor(opts ...ReceiverOption) (*ReceiverInterceptorFactory, error) {
	panic("not implemented on windows")
}

type ReceiverInterceptor struct {
}

func (r *ReceiverInterceptor) BindRTCPWriter(writer interceptor.RTCPWriter) interceptor.RTCPWriter {
	panic("not implemented on windows")
}

func (r *ReceiverInterceptor) BindRemoteStream(_ *interceptor.StreamInfo, reader interceptor.RTPReader) interceptor.RTPReader {
	return reader
}

// UnbindRemoteStream is called when the Stream is removed. It can be used to clean up any data related to that track.
func (r *ReceiverInterceptor) UnbindRemoteStream(info *interceptor.StreamInfo) {
	panic("not implemented on windows")
}

// Close closes the interceptor.
func (r *ReceiverInterceptor) Close() error {
	panic("not implemented on windows")
}

func (r *ReceiverInterceptor) loop(rtcpWriter interceptor.RTCPWriter) {
	panic("not implemented on windows")
}

func (r *ReceiverInterceptor) isClosed() bool {
	panic("not implemented on windows")
}
