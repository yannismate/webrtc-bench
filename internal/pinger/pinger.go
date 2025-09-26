package pinger

import (
	"encoding/json"
	"github.com/go-ping/ping"
	"github.com/rs/zerolog/log"
	"time"
)

type Pinger interface {
	Start()
	Stop()
	GetResultData() []byte
}

type pinger struct {
	pinger *ping.Pinger
	data   ICMPPingData
}

func NewPinger(targetAddress string, interval time.Duration) (Pinger, error) {
	pingr, err := ping.NewPinger(targetAddress)
	if err != nil {
		return nil, err
	}
	pingr.SetPrivileged(true)

	p := pinger{
		pinger: pingr,
	}

	pingr.OnRecv = func(pkt *ping.Packet) {
		p.data.Pings = append(p.data.Pings, Ping{
			ReplyRecvTime: time.Now(),
			Rtt:           pkt.Rtt,
			Seq:           pkt.Seq,
			Ttl:           pkt.Ttl,
		})
	}
	pingr.Interval = interval
	pingr.RecordRtts = false
	return &p, nil
}

func (p *pinger) Start() {
	log.Info().Msgf("Starting ICMP pinger...")
	go func() {
		err := p.pinger.Run()
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to start pinger")
		}
	}()
}

func (p *pinger) Stop() {
	log.Info().Msgf("Stopping ICMP pinger...")
	p.pinger.Stop()
	log.Info().Msgf("Stopped ICMP pinger")
}

func (p *pinger) GetResultData() []byte {
	data, err := json.Marshal(p.data)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to marshal ping result data")
	}
	return data
}
