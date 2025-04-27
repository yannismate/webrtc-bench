package stats

import (
	"github.com/pion/interceptor"
	"github.com/pion/interceptor/pkg/stats"
	"github.com/rs/zerolog/log"
	"sync"
	"time"
)

type StatCollector interface {
	GetInterceptorRegistry() *interceptor.Registry
	SetInterval(interval time.Duration)
	StartCollection(streamID uint32)
	StopCollection()
}

type statCollector struct {
	statsGetter         stats.Getter
	interceptorRegistry *interceptor.Registry
	collectionInterval  time.Duration

	stopCollection     chan bool
	stopCollectionOnce sync.Once
}

func NewStatCollector() StatCollector {
	statsInterceptorFactory, err := stats.NewInterceptor()
	if err != nil {
		log.Fatal().Err(err).Msg("stats.NewInterceptor() failed")
		return nil
	}

	sc := &statCollector{
		stopCollection: make(chan bool),
	}

	statsInterceptorFactory.OnNewPeerConnection(func(_ string, g stats.Getter) {
		sc.statsGetter = g
	})

	interceptorRegistry := &interceptor.Registry{}
	interceptorRegistry.Add(statsInterceptorFactory)

	sc.interceptorRegistry = interceptorRegistry

	return sc
}

func (sc *statCollector) GetInterceptorRegistry() *interceptor.Registry {
	return sc.interceptorRegistry
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
				log.Info().Msgf("stats: %v", recordedStats)
			}
		}
	}()
}

func (sc *statCollector) StopCollection() {
	sc.stopCollectionOnce.Do(func() {
		sc.stopCollection <- true
		close(sc.stopCollection)
	})
}
