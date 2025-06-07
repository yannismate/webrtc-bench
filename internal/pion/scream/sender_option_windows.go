// Adjusted from https://github.com/pion/interceptor/tree/feat/scream-cgo-update
// Originally authored by @mengelbart

package scream

type SenderOption func(r *SenderInterceptor) error

// SenderQueue sets the factory function to create new RTP Queues for new streams.
func SenderQueue(queueFactory func() RTPQueue) SenderOption {
	panic("not implemented on windows")
}

func MinBitrate(rate float64) SenderOption {
	panic("not implemented on windows")
}

func InitialBitrate(rate float64) SenderOption {
	panic("not implemented on windows")
}

func MaxBitrate(rate float64) SenderOption {
	panic("not implemented on windows")
}

func TotalBitrateChangeNotifier(channel chan int) SenderOption {
	panic("not implemented on windows")
}

func OnSenderInterceptorCreated(fn func(*SenderInterceptor)) SenderOption {
	panic("not implemented on windows")
}
